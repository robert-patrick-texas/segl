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
 * What segl reads of an element, and which copy of one is kept
 * (docs/ARCHITECTURE.md, "Collaboration"; D2-025).
 *
 * An element is the record the editor produces. segl reads its `id`,
 * `version`, and `versionNonce`, and passes the rest on as it is. The copy
 * with the higher version wins, and on equal versions the copy with the lower
 * nonce: the rule of the editor's `reconcileElements`, which the canvas
 * adapter calls, and of `src/segl/reconcile.py` on the server.
 */

export interface WireElement {
	id: string;
	version: number;
	versionNonce: number;
	[field: string]: unknown;
}

/** The two numbers that say which copy of an element this is. */
export interface Stamp {
	version: number;
	versionNonce: number;
}

export function isWireElement(value: unknown): value is WireElement {
	if (typeof value !== 'object' || value === null) return false;
	const { id, version, versionNonce } = value as Record<string, unknown>;
	return (
		typeof id === 'string' &&
		id !== '' &&
		Number.isInteger(version) &&
		Number.isInteger(versionNonce)
	);
}

/** Whether copy `a` replaces copy `b` of the same element. The same copy does not. */
export function beats(a: Stamp, b: Stamp | undefined): boolean {
	if (b === undefined) return true;
	if (a.version !== b.version) return a.version > b.version;
	return a.versionNonce < b.versionNonce;
}

/** The copy of each element the server is known to hold, by element id. */
export type Known = Map<string, Stamp>;

/** What the server holds once it has sent, or been sent, these elements. */
export function note(known: Known, elements: readonly WireElement[]): void {
	for (const { id, version, versionNonce } of elements) {
		if (beats({ version, versionNonce }, known.get(id))) known.set(id, { version, versionNonce });
	}
}

export function knownFrom(elements: readonly WireElement[]): Known {
	const known: Known = new Map();
	note(known, elements);
	return known;
}

/**
 * The elements this browser holds that the server has not seen, or holds an
 * older copy of. They are what an edit sends, and what a reconnect sends: the
 * edits made while the socket was down. An element the server holds a newer
 * copy of is not among them, so a reconnect never overwrites a newer edit.
 */
export function pendingElements(
	local: readonly WireElement[],
	known: ReadonlyMap<string, Stamp>
): WireElement[] {
	return local.filter((element) => beats(element, known.get(element.id)));
}
