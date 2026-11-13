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

import { readFileSync } from 'node:fs';
import { describe, expect, test } from 'vitest';
import {
	beats,
	isWireElement,
	knownFrom,
	note,
	pendingElements,
	sceneElements,
	type WireElement
} from './elements.ts';

interface Case {
	name: string;
	stored: WireElement[];
	incoming: WireElement[];
	winners: string[];
}

// The table the server's rule and the editor's helper are held to as well
// (tests/test_reconcile.py, web/e2e/reconcile.spec.ts).
const { cases } = JSON.parse(
	readFileSync(new URL('../../../tests/reconcile_cases.json', import.meta.url), 'utf8')
) as { cases: Case[] };

function element(id: string, version: number, versionNonce = 1): WireElement {
	return { id, version, versionNonce };
}

describe('beats', () => {
	test('the table has cases', () => {
		expect(cases.length).toBeGreaterThanOrEqual(15);
	});

	test.each(cases)('$name', ({ stored, incoming, winners }) => {
		const held = new Map(stored.map((each) => [each.id, each]));

		const won = incoming.filter((each) => beats(each, held.get(each.id)));

		expect(won.map((each) => each.id)).toEqual(winners);
	});

	test('the higher version wins, whatever the nonces', () => {
		expect(beats(element('a', 2, 9), element('a', 1, 1))).toBe(true);
		expect(beats(element('a', 1, 1), element('a', 2, 9))).toBe(false);
	});

	test('on equal versions the lower nonce wins', () => {
		expect(beats(element('a', 2, 1), element('a', 2, 9))).toBe(true);
		expect(beats(element('a', 2, 9), element('a', 2, 1))).toBe(false);
	});

	test('the same copy does not win, and anything wins over nothing', () => {
		expect(beats(element('a', 2, 5), element('a', 2, 5))).toBe(false);
		expect(beats(element('a', 0, 0), undefined)).toBe(true);
	});
});

describe('pendingElements', () => {
	test('what the server has not seen, and what it holds an older copy of', () => {
		const known = knownFrom([element('same', 3, 5), element('older', 1), element('tied', 2, 9)]);
		const local = [
			element('same', 3, 5),
			element('older', 2),
			element('tied', 2, 4),
			element('new', 1)
		];

		expect(pendingElements(local, known).map((each) => each.id)).toEqual(['older', 'tied', 'new']);
	});

	test('an element the server holds a newer copy of is not sent', () => {
		const known = knownFrom([element('a', 5), element('b', 2, 1)]);

		expect(pendingElements([element('a', 4), element('b', 2, 9)], known)).toEqual([]);
	});

	test('a deleted element is sent like any other', () => {
		const known = knownFrom([element('a', 1)]);
		const deleted = { ...element('a', 2), isDeleted: true };

		expect(pendingElements([deleted], known)).toEqual([deleted]);
	});

	test('with nothing known, everything is pending', () => {
		const local = [element('a', 1), element('b', 1)];

		expect(pendingElements(local, new Map())).toEqual(local);
	});
});

describe('note', () => {
	test('keeps the winning copy of each element', () => {
		const known = knownFrom([element('a', 2, 5), element('b', 2, 5)]);

		note(known, [element('a', 3, 9), element('b', 1, 1), element('c', 1, 7)]);

		expect(Object.fromEntries(known)).toEqual({
			a: { version: 3, versionNonce: 9 },
			b: { version: 2, versionNonce: 5 },
			c: { version: 1, versionNonce: 7 }
		});
	});

	test('what was sent is not pending again', () => {
		const known = new Map();
		const local = [element('a', 1), element('b', 4)];

		note(known, pendingElements(local, known));

		expect(pendingElements(local, known)).toEqual([]);
	});
});

describe('isWireElement', () => {
	test('an element has an id, a version, and a nonce', () => {
		expect(isWireElement({ id: 'a', version: 1, versionNonce: -7, type: 'rectangle' })).toBe(true);
	});

	test.each([
		null,
		'a',
		7,
		[],
		{},
		{ id: '', version: 1, versionNonce: 1 },
		{ id: 7, version: 1, versionNonce: 1 },
		{ id: 'a', version: '1', versionNonce: 1 },
		{ id: 'a', version: 1.5, versionNonce: 1 },
		{ id: 'a', version: 1 },
		{ id: 'a', versionNonce: 1 },
		{ id: 'a', version: 1, versionNonce: null }
	])('%j is not one', (value) => {
		expect(isWireElement(value)).toBe(false);
	});
});

describe('sceneElements', () => {
	test('a stored scene gives its elements, deleted ones among them', () => {
		const kept = { id: 'a', version: 3, versionNonce: 9, type: 'rectangle' };
		const deleted = { id: 'b', version: 2, versionNonce: 4, isDeleted: true };
		const document = { type: 'excalidraw', elements: [kept, deleted], appState: {} };
		expect(sceneElements(document)).toEqual([kept, deleted]);
	});

	test('what is not an element is left out, and the rest is kept', () => {
		const good = { id: 'a', version: 1, versionNonce: 1 };
		const document = { elements: [null, 'a', { id: 'x' }, good, { id: 'y', version: '2' }] };
		expect(sceneElements(document)).toEqual([good]);
	});

	test.each([null, undefined, 7, 'scene', [], {}, { elements: null }, { elements: { a: 1 } }])(
		'%j has none',
		(document) => {
			expect(sceneElements(document)).toEqual([]);
		}
	);
});
