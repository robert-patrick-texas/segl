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
 * Display names (docs/ARCHITECTURE.md, "Display names").
 *
 * A new browser asks the server for a label once, such as `Alpha1`, and keeps
 * it in `localStorage`. A person may type another, which is title-cased. A
 * label from the server is shown as the server spelled it.
 */
import { ApiError } from './api.ts';
import type { SlotStorage } from './slots.ts';

/** The longest name, in characters. The server has the same limit. */
export const MAX_NAME_LENGTH = 40;

/** Characters, not UTF-16 units: the server counts code points. */
function characters(text: string): string[] {
	return Array.from(text);
}

function titleWord(word: string): string {
	const [first = '', ...rest] = characters(word);
	// A few characters are more than one when uppercased: ß is SS. Only the
	// first of those stays uppercase, so ßeta is Sseta, and stays Sseta.
	const [head = '', ...more] = characters(first.toUpperCase());
	return head + (more.join('') + rest.join('')).toLowerCase();
}

/**
 * Return a name a person typed as segl shows it, or null when it is not 1 to
 * 40 characters.
 *
 * The words are split on whitespace and joined with one space. Each gets an
 * uppercase first character and a lowercase rest: `john smith` is
 * `John Smith`, and `NASA` is `Nasa`. `src/segl/names.py` applies the same
 * rule, and `tests/display_name_cases.json` holds both to one table.
 */
export function titleCaseName(text: string): string | null {
	const name = text
		.split(/\s+/u)
		.filter((word) => word !== '')
		.map(titleWord)
		.join(' ');
	const length = characters(name).length;
	return length >= 1 && length <= MAX_NAME_LENGTH ? name : null;
}

/**
 * Return a label as it may be shown, or null: a string of 1 to 40 characters
 * once the spaces around it are dropped. The spelling is not changed, so a
 * label from the server's word file, such as `McKinley7`, stays as written.
 */
export function usableName(value: unknown): string | null {
	if (typeof value !== 'string') return null;
	const name = value.trim();
	const length = characters(name).length;
	return length >= 1 && length <= MAX_NAME_LENGTH ? name : null;
}

/** Return this browser's label, or null when none is stored. */
export function readStoredName(storage: SlotStorage | null, key: string): string | null {
	try {
		return usableName(storage?.getItem(key));
	} catch {
		return null;
	}
}

/** Keep the label. A browser that refuses storage is given a new one on its next visit. */
export function writeStoredName(storage: SlotStorage | null, key: string, name: string): void {
	try {
		storage?.setItem(key, name);
	} catch {
		// Storage is full or blocked. The label still shows on this page.
	}
}

/** One request per storage key at a time, however many callers are waiting. */
const asking = new Map<string, Promise<string>>();

/**
 * Return this browser's label, asking the server for one only when none is
 * stored.
 *
 * `allocate` is the call that takes the next name from the server. Callers
 * that arrive while it is out share its answer, so a page asks once. If a
 * label was stored in the meantime, by another tab or by a rename, that one
 * stays and the answer is dropped.
 */
export function assignName(
	storage: SlotStorage | null,
	key: string,
	allocate: () => Promise<string>
): Promise<string> {
	const stored = readStoredName(storage, key);
	if (stored !== null) return Promise.resolve(stored);
	let request = asking.get(key);
	if (request === undefined) {
		request = allocate()
			.then((assigned) => {
				const name = usableName(assigned);
				if (name === null) throw new Error('segl sent a display name this page cannot use');
				const kept = readStoredName(storage, key);
				if (kept !== null) return kept;
				writeStoredName(storage, key, name);
				return name;
			})
			.finally(() => asking.delete(key));
		asking.set(key, request);
	}
	return request;
}

const RETRY_SECONDS = 30;
const LONGEST_RETRY_SECONDS = 300;

/**
 * How long to wait before asking for a label again, in milliseconds. A
 * refusal for asking too often says when (`Retry-After`). Anything else, such
 * as a server that is restarting, is tried again in half a minute.
 */
export function retryDelay(error: unknown): number {
	const seconds =
		error instanceof ApiError && error.retryAfter !== null ? error.retryAfter : RETRY_SECONDS;
	return Math.min(Math.max(seconds, 1), LONGEST_RETRY_SECONDS) * 1000;
}
