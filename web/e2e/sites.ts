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
 * Where the browser tests' servers listen (`playwright.config.ts` starts
 * them), and the edit token one of them has. The config and the specs both
 * read this file.
 */

const PORT = Number(process.env['SEGL_E2E_PORT'] ?? 18950);

export const PORTS = {
	/** segl with no edit token, and nginx in front of it at `/board/` and at a host root. */
	direct: PORT,
	board: PORT + 1,
	root: PORT + 2,
	/** The server `durability.spec.ts` starts, kills, and starts again. */
	restart: PORT + 3,
	/** segl with `EDIT_TOKEN`, and its own nginx at `/board/` and at a host root. */
	token: PORT + 4,
	tokenBoard: PORT + 5,
	tokenRoot: PORT + 6
} as const;

/** The base URL of each project. Each ends in a slash, and the specs open paths relative to it. */
export const SITES = {
	direct: `http://127.0.0.1:${PORTS.direct}/`,
	root: `https://127.0.0.1:${PORTS.root}/`,
	board: `https://127.0.0.1:${PORTS.board}/board/`,
	restart: `http://127.0.0.1:${PORTS.restart}/`,
	'token-direct': `http://127.0.0.1:${PORTS.token}/`,
	'token-root': `https://127.0.0.1:${PORTS.tokenRoot}/`,
	'token-board': `https://127.0.0.1:${PORTS.tokenBoard}/board/`
} as const;

export type ProjectName = keyof typeof SITES;

/**
 * The token of the server the `token-` projects run against. It has the
 * characters of a base64 secret, as `openssl rand -base64` writes one: a plus
 * that must not be read as a space, a slash, and equals signs.
 */
export const EDIT_TOKEN = 'S3gl+e2e/Token==';
