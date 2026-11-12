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
 * What this browser tells the server about itself in `hello`, beside its
 * display name: an id of its own, and the edit token when it has one. Both
 * are in `localStorage`, under keys that carry the mount (docs/ARCHITECTURE.md).
 */
import type { SlotStorage } from '../slots.ts';

/** The shape the server takes: 1 to 64 letters, digits, `_` and `-`. */
const CLIENT_ID = /^[A-Za-z0-9_-]{1,64}$/;

/** 32 hexadecimal digits. `crypto.randomUUID` needs HTTPS, and this does not. */
export function newClientId(): string {
	const bytes = crypto.getRandomValues(new Uint8Array(16));
	return Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
}

/**
 * Return this browser's id, making and storing one on the first call. A
 * browser that refuses storage gets a new one for each page.
 */
export function readClientId(
	storage: SlotStorage | null,
	key: string,
	make: () => string = newClientId
): string {
	try {
		const stored = storage?.getItem(key);
		if (typeof stored === 'string' && CLIENT_ID.test(stored)) return stored;
	} catch {
		// Storage is blocked. An id for this page will do.
	}
	const id = make();
	try {
		storage?.setItem(key, id);
	} catch {
		// Storage is full or blocked.
	}
	return id;
}

/** Return the edit token this browser has stored, or `''` (T10 stores it). */
export function readEditToken(storage: SlotStorage | null, key: string): string {
	try {
		return storage?.getItem(key) ?? '';
	} catch {
		return '';
	}
}
