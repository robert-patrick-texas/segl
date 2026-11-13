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
 * them), and the access code one of them asks for. The config and the specs
 * both read this file.
 */

const PORT = Number(process.env['SEGL_E2E_PORT'] ?? 18950);

export const PORTS = {
	/** segl with no access codes, and nginx in front of it at `/board/` and at a host root. */
	direct: PORT,
	board: PORT + 1,
	root: PORT + 2,
	/** The server a spec starts for itself: `durability.spec.ts` and `expiry.spec.ts`. */
	restart: PORT + 3,
	/** segl with `ACCESS_CODE`, and its own nginx at `/board/` and at a host root. */
	access: PORT + 4,
	accessBoard: PORT + 5,
	accessRoot: PORT + 6
} as const;

/** The base URL of each project. Each ends in a slash, and the specs open paths relative to it. */
export const SITES = {
	direct: `http://127.0.0.1:${PORTS.direct}/`,
	root: `https://127.0.0.1:${PORTS.root}/`,
	board: `https://127.0.0.1:${PORTS.board}/board/`,
	restart: `http://127.0.0.1:${PORTS.restart}/`,
	'access-direct': `http://127.0.0.1:${PORTS.access}/`,
	'access-root': `https://127.0.0.1:${PORTS.accessRoot}/`,
	'access-board': `https://127.0.0.1:${PORTS.accessBoard}/board/`
} as const;

export type ProjectName = keyof typeof SITES;

/**
 * An access code of the server the `access-` projects run against, as the
 * site wrote it in `access_codes`: a phrase. A person may type it in any case
 * and with any separators.
 */
export const ACCESS_CODE = 'Maple River 42';

/** The secret that signs that server's passes. Not a real one. */
export const ACCESS_SECRET = 'segl-e2e-secret-7c1e5b9d3f0a2468-not-a-real-one';

/** What such a server issues: the second of its issue, a dot, and a signature. */
export const PASS_SHAPE = /^[0-9]{10}\.[A-Za-z0-9_-]{24}$/;
