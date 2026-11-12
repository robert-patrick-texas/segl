// Copyright 2026 segl contributors
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

/**
 * A segl process a test may kill and start again (docs/TEST-PLAN.md T-006,
 * T-007). The other browser tests share the server Playwright starts, which
 * cannot be restarted under them, so `durability.spec.ts` runs this one, on a
 * port and in a folder of its own.
 */
import { spawn, type ChildProcess } from 'node:child_process';
import { mkdtempSync, openSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';

/** How long a start, or a stop, may take. */
const PATIENCE_MS = 30_000;

export class RestartableServer {
	readonly url: string;
	/** Where the database and the uploaded files are. A restart finds them again. */
	readonly folder: string;
	private readonly config: string;
	private child: ChildProcess | null = null;

	constructor(baseURL: string) {
		this.url = baseURL;
		this.folder = mkdtempSync(join(tmpdir(), 'segl-e2e-restart-'));
		this.config = join(this.folder, 'segl.toml');
		writeFileSync(join(this.folder, 'display-names.txt'), 'Guest\nStaff\n');
		writeFileSync(
			this.config,
			[
				`bind = "127.0.0.1:${new URL(baseURL).port}"`,
				`database = ${JSON.stringify(join(this.folder, 'segl.sqlite'))}`,
				`assets_dir = ${JSON.stringify(join(this.folder, 'assets'))}`,
				`display_names = ${JSON.stringify(join(this.folder, 'display-names.txt'))}`,
				// The tests run from web/, and the build is web/dist.
				`web_dir = ${JSON.stringify(resolve('dist'))}`,
				''
			].join('\n')
		);
	}

	/** Start segl over the folder, and wait until it answers. */
	async start(): Promise<void> {
		if (this.child !== null) throw new Error('the server is already running');
		const log = openSync(join(this.folder, 'segl.log'), 'a');
		// A process group of its own: `uv run` is the parent of the Python
		// process, and a kill must reach both.
		const child = spawn('uv', ['run', 'segl', '--config', this.config], {
			cwd: resolve('..'),
			detached: true,
			stdio: ['ignore', log, log]
		});
		this.child = child;
		const deadline = Date.now() + PATIENCE_MS;
		for (;;) {
			try {
				const response = await fetch(new URL('api/v1/health', this.url));
				if (response.ok) return;
			} catch {
				// Not listening yet.
			}
			if (child.exitCode !== null || Date.now() > deadline) {
				throw new Error(`segl did not start:\n${this.log()}`);
			}
			await new Promise((done) => setTimeout(done, 100));
		}
	}

	/**
	 * End the process with SIGKILL: no flush on the way out and no close of
	 * the database, as a crash or a lost host.
	 */
	async kill(): Promise<void> {
		await this.signal('SIGKILL');
	}

	/** Stop whatever is running, and remove the folder. */
	async remove(): Promise<void> {
		await this.signal('SIGKILL');
		rmSync(this.folder, { recursive: true, force: true });
	}

	log(): string {
		try {
			return readFileSync(join(this.folder, 'segl.log'), 'utf8');
		} catch {
			return '';
		}
	}

	private async signal(signal: NodeJS.Signals): Promise<void> {
		const child = this.child;
		if (child === null || child.pid === undefined) return;
		this.child = null;
		const gone = new Promise<void>((done) => {
			if (child.exitCode !== null || child.signalCode !== null) done();
			else child.once('exit', () => done());
		});
		try {
			// The whole group: a negative id.
			process.kill(-child.pid, signal);
		} catch {
			// It had already gone.
		}
		const late = setTimeout(() => {
			try {
				process.kill(-child.pid!, 'SIGKILL');
			} catch {
				// Gone.
			}
		}, PATIENCE_MS);
		await gone;
		clearTimeout(late);
		// The port is free once the Python process, the child of `uv run`, has gone.
		const deadline = Date.now() + PATIENCE_MS;
		while (Date.now() < deadline) {
			try {
				await fetch(new URL('api/v1/health', this.url));
			} catch {
				return;
			}
			await new Promise((done) => setTimeout(done, 50));
		}
		throw new Error('segl is still answering after it was stopped');
	}
}
