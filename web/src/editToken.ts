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
 * The edit token in this browser (docs/ARCHITECTURE.md, "Edit gate"; S-008).
 *
 * A shared link carries the token in its fragment, `#e=...`. The page takes
 * the fragment out of the address at once, and keeps the token for this page.
 * It is written to `localStorage` only once the server has let a `hello` with
 * it edit (D2-032). So a link with a wrong token, which any page on the web
 * can make this browser open, never takes the place of a token that works.
 *
 * The token goes to the server in the `X-Segl-Edit-Token` header and in the
 * socket's `hello`, and nowhere else: never in a URL the browser asks for.
 */
import type { SlotStorage } from './slots.ts';

/**
 * What the server takes as a token (`src/segl/config.py`): 1 to 256 printable
 * ASCII characters, with no space at either end. A request header carries
 * nothing else whole. `tests/edit_token_cases.json` holds both to one table.
 */
const TOKEN = /^[\x21-\x7e](?:[\x20-\x7e]{0,254}[\x21-\x7e])?$/;

export function isToken(text: string): boolean {
	return TOKEN.test(text);
}

/** What a link's fragment starts with when it carries a token. */
const LINK = '#e=';

/**
 * Read the fragment of an address, such as `#e=s3cret`.
 *
 * Null: not an edit link, and none of segl's business. Otherwise the token
 * the link carries, percent-decoded, or `''` when what it carries could not
 * be a token. Everything after `#e=` is the token: a `+`, a `/`, an `=`, or
 * an `&` in it is itself.
 */
export function tokenFromFragment(hash: string): string | null {
	if (!hash.startsWith(LINK)) return null;
	let token: string;
	try {
		token = decodeURIComponent(hash.slice(LINK.length));
	} catch {
		// A `%` that starts no escape. The link was not encoded, or was cut.
		return '';
	}
	return isToken(token) ? token : '';
}

/** The parts of `window` an edit link is taken from. */
export interface LinkTarget {
	location: Pick<Location, 'hash' | 'pathname' | 'search'>;
	history: Pick<History, 'state' | 'replaceState'>;
}

/**
 * Take the token out of the page's address. Returns it, or null when the
 * address is not an edit link or carries no usable token.
 *
 * The fragment of an edit link goes whether or not its token is usable, so
 * that no token stays in the address bar to be copied, bookmarked, or read
 * over a shoulder. The history entry is replaced, not added to, and keeps its
 * state, which is the router's.
 */
export function takeEditLink(target: LinkTarget): string | null {
	const token = tokenFromFragment(target.location.hash);
	if (token === null) return null;
	target.history.replaceState(
		target.history.state,
		'',
		target.location.pathname + target.location.search
	);
	return token === '' ? null : token;
}

/** Return the edit token this browser has stored, or `''`. */
export function readEditToken(storage: SlotStorage | null, key: string): string {
	try {
		const stored = storage?.getItem(key) ?? '';
		return isToken(stored) ? stored : '';
	} catch {
		return '';
	}
}

/** Store a token the server took. A browser that refuses storage keeps it for the page. */
export function writeEditToken(storage: SlotStorage | null, key: string, token: string): void {
	try {
		storage?.setItem(key, token);
	} catch {
		// Storage is full or blocked. The page still has the token.
	}
}

export interface TokenState {
	/** What this page sends, in `hello` and in the header. `''` for none. */
	token: string;
	/** True while `token` came from a link and the server has not answered for it. */
	unproven: boolean;
}

/** The state a page starts in: with the token of the link it was opened by, or the stored one. */
export function startingToken(link: string | null, stored: string): TokenState {
	if (link === null || link === stored) return { token: stored, unproven: false };
	return { token: link, unproven: true };
}

/** A link was opened in this tab while the page was open. */
export function afterLink(state: TokenState, link: string): TokenState {
	// The same token proves nothing new, and needs no new `hello`.
	return link === state.token ? state : { token: link, unproven: true };
}

/**
 * The server answered a `hello` that carried `sent`: `viewOnly`, or not.
 * `stored` is what `localStorage` holds now. Returns the state from here on,
 * and the token to store, or null.
 *
 * - A link's token that the server took is stored.
 * - One it refused gives way to the stored token, which may still work.
 * - With nothing stored, the refused one stays for this page, so the bar can
 *   say that the token is wrong, and is not stored.
 *
 * An answer for any other token is late: the page has moved on.
 */
export function afterAnswer(
	state: TokenState,
	sent: string,
	viewOnly: boolean,
	stored: string
): { state: TokenState; store: string | null } {
	if (!state.unproven || sent !== state.token) return { state, store: null };
	if (!viewOnly) return { state: { token: sent, unproven: false }, store: sent };
	if (stored !== '' && stored !== sent) {
		return { state: { token: stored, unproven: false }, store: null };
	}
	return { state: { token: sent, unproven: false }, store: null };
}

/**
 * `localStorage` changed in another tab of this browser: a token the server
 * took there, or the site's data cleared. This page says `hello` with it too.
 */
export function afterStorage(state: TokenState, stored: string): TokenState {
	return stored === state.token && !state.unproven ? state : { token: stored, unproven: false };
}
