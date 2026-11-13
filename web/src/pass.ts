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
 * The pass in this browser (docs/ARCHITECTURE.md, "Edit gate"; S-008, D2-033).
 *
 * A person enters an access code on the access page, and the server issues a
 * pass: the time of issue, signed. The page stores it in `localStorage`, under
 * a key that carries the mount, and sends it in the `X-Segl-Edit-Token` header
 * and in the socket's `hello`. Those two names are from when they carried a
 * token. The pass is in no URL the browser asks for, and nothing hands one
 * from a browser to another.
 */
import type { SlotStorage } from './slots.ts';

/**
 * What a page can send whole in a request header: 1 to 256 printable ASCII
 * characters, with no space at either end. A browser throws for any other
 * character, and drops a space at an end. A pass the server issues is well
 * inside this, so a stored value outside it is not a pass, and is not sent.
 * `tests/header_value_cases.json` holds this rule to one table.
 */
const SENDABLE = /^[\x21-\x7e](?:[\x20-\x7e]{0,254}[\x21-\x7e])?$/;

export function isSendable(text: string): boolean {
	return SENDABLE.test(text);
}

/** Return the pass this browser has stored, or `''`. */
export function readPass(storage: SlotStorage | null, key: string): string {
	try {
		const stored = storage?.getItem(key) ?? '';
		return isSendable(stored) ? stored : '';
	} catch {
		return '';
	}
}

/** Store a pass the server issued. A browser that refuses storage keeps it for the page. */
export function writePass(storage: SlotStorage | null, key: string, pass: string): void {
	try {
		storage?.setItem(key, pass);
	} catch {
		// Storage is full or blocked. The page still has the pass.
	}
}
