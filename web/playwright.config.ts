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
 * Set `PW_WS_ENDPOINT` to use a browser running elsewhere, such as the
 * Playwright container on a host without Chromium's system libraries. The
 * container's Playwright version must equal this one.
 */
import { mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { defineConfig, devices } from '@playwright/test';

const PORT = Number(process.env['SEGL_E2E_PORT'] ?? 18950);
const BOARD_PORT = PORT + 1;
const ROOT_PORT = PORT + 2;
const ws = process.env['PW_WS_ENDPOINT'];

// The server's data goes to a fresh folder, never to var/.
const WORK = join(tmpdir(), `segl-e2e-${PORT}`);
const CONFIG = join(WORK, 'segl.toml');
// Workers load this file too. Only the first process, which starts the servers, writes.
if (process.env['TEST_WORKER_INDEX'] === undefined) {
	rmSync(WORK, { recursive: true, force: true });
	mkdirSync(WORK, { recursive: true });
	// The two-word file of docs/TEST-PLAN.md T-014: labels are Guest1, Staff2, and on.
	writeFileSync(join(WORK, 'display-names.txt'), 'Guest\nStaff\n');
	writeFileSync(
		CONFIG,
		[
			`bind = "127.0.0.1:${PORT}"`,
			`database = ${JSON.stringify(join(WORK, 'segl.sqlite'))}`,
			`assets_dir = ${JSON.stringify(join(WORK, 'assets'))}`,
			`display_names = ${JSON.stringify(join(WORK, 'display-names.txt'))}`,
			`web_dir = ${JSON.stringify(resolve('dist'))}`,
			''
		].join('\n')
	);
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
		{ name: 'direct', use: { ...desktop, baseURL: `http://127.0.0.1:${PORT}/` } },
		{ name: 'root', use: { ...desktop, baseURL: `https://127.0.0.1:${ROOT_PORT}/` } },
		{ name: 'board', use: { ...desktop, baseURL: `https://127.0.0.1:${BOARD_PORT}/board/` } }
	],
	webServer: [
		{
			name: 'segl',
			command: `uv run segl --config ${CONFIG}`,
			cwd: '..',
			url: `http://127.0.0.1:${PORT}/api/v1/health`,
			reuseExistingServer: false,
			gracefulShutdown: { signal: 'SIGTERM', timeout: 10_000 },
			timeout: 60_000
		},
		{
			name: 'nginx',
			command:
				`uv run python tests/e2e_nginx.py --prefix ${join(WORK, 'proxy')} ` +
				`--upstream-port ${PORT} --board-port ${BOARD_PORT} --root-port ${ROOT_PORT}`,
			cwd: '..',
			wait: { stdout: /nginx is serving/ },
			reuseExistingServer: false,
			gracefulShutdown: { signal: 'SIGTERM', timeout: 10_000 },
			timeout: 60_000
		}
	]
});
