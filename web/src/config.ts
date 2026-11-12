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
 * Where this page is, and everything derived from that (docs/ARCHITECTURE.md,
 * "Mount and navigation").
 *
 * segl has no setting for the path it is mounted under. Python injects
 * `window.SEGL_CONFIG.root`, the relative path from this page to segl's root:
 * `./` on `/`, `../` on `/s/N`. Resolved once against the page's address it
 * gives the root URL, such as `https://dev.example.com/board/`, and the API,
 * the WebSocket, the router, the storage keys, and the editor's assets all
 * come from that URL.
 */

/** What Python writes into the page. The edit token is never part of it. */
export interface InjectedConfig {
	root: string;
	editRequired: boolean;
}

export interface AppConfig {
	/** segl's root, ending in a slash: `https://dev.example.com/board/`. */
	rootUrl: URL;
	/** The path of the root URL: `/board/`, or `/` at a host root. */
	basePath: string;
	/** True when the server has an edit token. */
	editRequired: boolean;
}

declare global {
	interface Window {
		SEGL_CONFIG?: unknown;
	}
}

/** `./`, or one or more `../`: the only shapes Python injects. */
const RELATIVE_ROOT = /^(?:\.\/|(?:\.\.\/)+)$/;

export function isInjectedConfig(value: unknown): value is InjectedConfig {
	if (typeof value !== 'object' || value === null) return false;
	const { root, editRequired } = value as Record<string, unknown>;
	return typeof root === 'string' && RELATIVE_ROOT.test(root) && typeof editRequired === 'boolean';
}

/** Resolve the injected config against the address of the page it came with. */
export function resolveConfig(injected: InjectedConfig, pageUrl: string): AppConfig {
	const rootUrl = new URL(injected.root, pageUrl);
	rootUrl.search = '';
	rootUrl.hash = '';
	return { rootUrl, basePath: rootUrl.pathname, editRequired: injected.editRequired };
}

/**
 * Return this page's config.
 *
 * The Vite dev server serves the page itself, at the host root and without
 * `SEGL_CONFIG`. There the root is the host root, and `editRequired` comes
 * from `GET api/v1/config`, which holds the same fact.
 */
export async function loadConfig(
	injected: unknown,
	pageUrl: string,
	fetcher: typeof fetch = fetch
): Promise<AppConfig> {
	if (isInjectedConfig(injected)) return resolveConfig(injected, pageUrl);
	const development = resolveConfig(
		{ root: './', editRequired: false },
		new URL('/', pageUrl).href
	);
	const response = await fetcher(apiUrl(development, 'config'));
	if (!response.ok) throw new Error(`segl answered ${response.status} for its config`);
	const body = (await response.json()) as { editRequired?: unknown };
	return { ...development, editRequired: body.editRequired === true };
}

/** `apiUrl(config, 'slots/4/scene')` is `<root>api/v1/slots/4/scene`. */
export function apiUrl(config: AppConfig, path: string): URL {
	return new URL(`api/v1/${path}`, config.rootUrl);
}

/** The collaboration socket for a slot. `wss:` when the page is `https:`. */
export function collabUrl(config: AppConfig, slot: number): URL {
	const url = new URL(`collab?slot=${slot}`, config.rootUrl);
	url.protocol = config.rootUrl.protocol === 'https:' ? 'wss:' : 'ws:';
	return url;
}

/** The React Router basename: `/board`, or `/` at a host root. */
export function routerBasename(config: AppConfig): string {
	return config.basePath === '/' ? '/' : config.basePath.replace(/\/$/, '');
}

/**
 * A `localStorage` key. The base path is part of it, so two mounts on one
 * origin stay separate: `segl:/board/:lastSlot`.
 */
export function storageKey(config: AppConfig, name: string): string {
	return `segl:${config.basePath}:${name}`;
}
