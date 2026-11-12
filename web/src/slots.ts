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

/** The nine slots, and the one this browser opened last (D2-005, D2-006). */

export const SLOT_NUMBERS = [1, 2, 3, 4, 5, 6, 7, 8, 9] as const;

export const FIRST_SLOT = 1;

/**
 * Return the slot a URL segment or a stored value names, or null.
 *
 * Only the nine texts `1` to `9` name a slot, as on the server: `01`, `+1`,
 * `10`, and `abc` do not.
 */
export function parseSlot(text: string | null | undefined): number | null {
	return typeof text === 'string' && /^[1-9]$/.test(text) ? Number(text) : null;
}

/** The part of `Storage` this module uses. `localStorage` may be unavailable. */
export type SlotStorage = Pick<Storage, 'getItem' | 'setItem'>;

/** Return the last slot this browser opened, or null when none is stored. */
export function readLastSlot(storage: SlotStorage | null, key: string): number | null {
	try {
		return parseSlot(storage?.getItem(key));
	} catch {
		return null;
	}
}

/** Remember the slot. A browser that refuses storage just opens slot 1 next time. */
export function writeLastSlot(storage: SlotStorage | null, key: string, slot: number): void {
	try {
		storage?.setItem(key, String(slot));
	} catch {
		// Storage is full or blocked. The slot still opens.
	}
}

/** `window.localStorage`, or null where reading the property throws. */
export function browserStorage(): Storage | null {
	try {
		return window.localStorage;
	} catch {
		return null;
	}
}
