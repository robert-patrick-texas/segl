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
 * Browser tests against the real server and the production build
 * (docs/DEVELOPMENT.md, docs/TEST-PLAN.md T-010 and T-013).
 *
 * Playwright starts `uv run segl --config <temporary TOML>`, which serves
 * `web/dist`, and then nginx in front of it with the files in `deploy/nginx/`
 * (`tests/e2e_nginx.py`, the harness the mount tests use). Every spec runs
 * three times: against Python directly, through nginx at a host root
 * (`site-root.example.conf`), and through nginx at `/board/`
 * (`site-board.example.conf`). Each site example has an nginx of its own on a
 * loopback port, so the browser needs no name for it. Build first:
 * `npm run build`.
 *
 * Three specs are apart, and the three projects above leave them out.
 * `e2e/durability.spec.ts` and `e2e/expiry.spec.ts` are the `restart` project.
 * Each of their tests runs a segl of its own, on the next port: one kills the
 * server and starts it again, and the other needs passes that last seconds.
 * `e2e/access.spec.ts` is the three `access-` projects (docs/TEST-PLAN.md
 * T-008 and T-019): a second segl, started here with `access_codes`, directly
 * and behind an nginx of its own at a host root and at `/board/`.
 *
 * Set `PW_WS_ENDPOINT` to use a browser running elsewhere, such as the
 * Playwright container on a host without Chromium's system libraries. The
 * container's Playwright version must equal this one.
 */
import { mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { defineConfig, devices } from '@playwright/test';
import { ACCESS_CODE, ACCESS_SECRET, PORTS, SITES } from './e2e/sites.ts';

/** The specs whose tests each start a segl of their own. */
const OWN_SERVER_SPECS = ['durability.spec.ts', 'expiry.spec.ts'];
const ACCESS_SPEC = 'access.spec.ts';
/** The specs the three open projects leave out. */
const APART = [...OWN_SERVER_SPECS, ACCESS_SPEC];
const ws = process.env['PW_WS_ENDPOINT'];

// The servers' data goes to a fresh folder, never to var/.
const WORK = join(tmpdir(), `segl-e2e-${PORTS.direct}`);
const ACCESS_WORK = join(WORK, 'access');
const CONFIG = join(WORK, 'segl.toml');
const ACCESS_CONFIG = join(ACCESS_WORK, 'segl.toml');

/** Write the TOML of a test server that keeps everything in `folder`. */
function writeConfig(folder: string, port: number, more: string[] = []): void {
	mkdirSync(folder, { recursive: true });
	// The two-word file of docs/TEST-PLAN.md T-014: labels are Guest1, Staff2, and on.
	writeFileSync(join(folder, 'display-names.txt'), 'Guest\nStaff\n');
	writeFileSync(
		join(folder, 'segl.toml'),
		[
			`bind = "127.0.0.1:${port}"`,
			`database = ${JSON.stringify(join(folder, 'segl.sqlite'))}`,
			`assets_dir = ${JSON.stringify(join(folder, 'assets'))}`,
			`display_names = ${JSON.stringify(join(folder, 'display-names.txt'))}`,
			`web_dir = ${JSON.stringify(resolve('dist'))}`,
			...more,
			''
		].join('\n')
	);
}

// Workers load this file too. Only the first process, which starts the servers, writes.
if (process.env['TEST_WORKER_INDEX'] === undefined) {
	rmSync(WORK, { recursive: true, force: true });
	writeConfig(WORK, PORTS.direct);
	writeConfig(ACCESS_WORK, PORTS.access, [
		`access_codes = [${JSON.stringify(ACCESS_CODE)}]`,
		`access_secret = ${JSON.stringify(ACCESS_SECRET)}`
	]);
}

/** `uv run segl` over one of the two TOML files. */
function seglServer(name: string, config: string, port: number) {
	return {
		name,
		command: `uv run segl --config ${config}`,
		cwd: '..',
		url: `http://127.0.0.1:${port}/api/v1/health`,
		reuseExistingServer: false,
		gracefulShutdown: { signal: 'SIGTERM' as const, timeout: 10_000 },
		timeout: 60_000
	};
}

/** nginx with the `deploy/nginx/` files in front of one segl, a site example to a port. */
function nginxServer(name: string, prefix: string, upstream: number, board: number, root: number) {
	return {
		name,
		command:
			`uv run python tests/e2e_nginx.py --prefix ${prefix} ` +
			`--upstream-port ${upstream} --board-port ${board} --root-port ${root}`,
		cwd: '..',
		wait: { stdout: /nginx is serving/ },
		reuseExistingServer: false,
		gracefulShutdown: { signal: 'SIGTERM' as const, timeout: 10_000 },
		timeout: 60_000
	};
}

const desktop = { ...devices['Desktop Chrome'], viewport: { width: 1280, height: 800 } };

export default defineConfig({
	testDir: 'e2e',
	outputDir: 'test-results',
	timeout: 30_000,
	// One test at a time. Every project talks to the one server, whose slots
	// are shared by design: what one test draws on a slot, another test on that
	// slot would see arrive, and each would count the other's connection.
	workers: 1,
	fullyParallel: false,
	forbidOnly: Boolean(process.env['CI']),
	reporter: [['list']],
	use: {
		trace: 'retain-on-failure',
		// The test certificate is self-signed, and names the sites, not 127.0.0.1.
		// tests/test_mount.py verifies it under the site names.
		ignoreHTTPSErrors: true,
		...(ws ? { connectOptions: { wsEndpoint: ws } } : {})
	},
	// Each base URL ends in a slash, and the specs open paths relative to it.
	projects: [
		...(['direct', 'root', 'board'] as const).map((name) => ({
			name,
			testIgnore: APART,
			use: { ...desktop, baseURL: SITES[name] }
		})),
		{
			name: 'restart',
			testMatch: OWN_SERVER_SPECS,
			use: { ...desktop, baseURL: SITES.restart }
		},
		...(['access-direct', 'access-root', 'access-board'] as const).map((name) => ({
			name,
			testMatch: ACCESS_SPEC,
			use: { ...desktop, baseURL: SITES[name] }
		}))
	],
	webServer: [
		seglServer('segl', CONFIG, PORTS.direct),
		nginxServer('nginx', join(WORK, 'proxy'), PORTS.direct, PORTS.board, PORTS.root),
		seglServer('segl-access', ACCESS_CONFIG, PORTS.access),
		nginxServer(
			'nginx-access',
			join(ACCESS_WORK, 'proxy'),
			PORTS.access,
			PORTS.accessBoard,
			PORTS.accessRoot
		)
	]
});
