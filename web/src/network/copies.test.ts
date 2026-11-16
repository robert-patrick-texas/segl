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

import { describe, expect, test } from 'vitest';
import { copyIds, type Placed } from './copies.ts';
import { UNPLACED } from './record.ts';

const A = 'aaaaaaaa-0000-4000-8000-000000000001';
const B = 'bbbbbbbb-0000-4000-8000-000000000002';

function card(id: string, objectId: string, group: string, isDeleted = false): Placed {
	return {
		id,
		type: 'rectangle',
		isDeleted,
		groupIds: [group],
		customData: { segl: { schemaVersion: 1, objectId, objectType: 'router', state: 'planned' } }
	};
}

function tag(id: string, objectId: string, group: string, isDeleted = false): Placed {
	return {
		id,
		type: 'text',
		isDeleted,
		groupIds: [group],
		customData: { segl: { schemaVersion: 1, objectId, part: 'tag' } }
	};
}

function link(id: string, objectId: string, isDeleted = false): Placed {
	return {
		id,
		type: 'arrow',
		isDeleted,
		groupIds: [],
		customData: { segl: { schemaVersion: 1, objectId, objectType: 'cable', state: 'existing' } }
	};
}

function line(id: string, group: string): Placed {
	return { id, type: 'line', isDeleted: false, groupIds: [group] };
}

/** New ids in the order they are asked for: n1, n2, ... */
function counter(): () => string {
	let n = 0;
	return () => `new-${(n += 1)}`;
}

describe('a new id for each kind of copy', () => {
	test('a device placed from the library', () => {
		const prev = [card('c1', A, 'g1')];
		const next = [...prev, card('lib', UNPLACED, 'g9'), line('glyph', 'g9')];
		expect(copyIds(next, prev, counter())).toEqual(new Map([['lib', 'new-1']]));
	});

	test('a link placed from the library, onto an empty canvas', () => {
		expect(copyIds([link('l1', UNPLACED)], [], counter())).toEqual(new Map([['l1', 'new-1']]));
	});

	test('the same library item, placed twice: each copy is new', () => {
		const make = counter();
		const first = copyIds([card('x1', UNPLACED, 'g1')], [], make);
		const prev = [card('x1', first.get('x1')!, 'g1')];
		const second = copyIds([...prev, card('x2', UNPLACED, 'g2')], prev, make);
		expect(first.get('x1')).toBe('new-1');
		expect(second).toEqual(new Map([['x2', 'new-2']]));
	});

	test("a paste, or the editor's duplicate, while the source is on the canvas", () => {
		const prev = [card('c1', A, 'g1'), tag('t1', A, 'g1'), line('l1', 'g1')];
		const next = [...prev, card('c2', A, 'g2'), tag('t2', A, 'g2'), line('l2', 'g2')];
		expect(copyIds(next, prev, counter())).toEqual(
			new Map([
				['c2', 'new-1'],
				['t2', 'new-1']
			])
		);
	});

	test('Alt-drag: the copy stays behind, and the dragged source keeps its id', () => {
		// The editor leaves the copy where the source was and moves the source.
		const prev = [card('c1', A, 'g1'), tag('t1', A, 'g1')];
		const next = [card('dup', A, 'g2'), tag('dupTag', A, 'g2'), ...prev];
		const ids = copyIds(next, prev, counter());
		expect(ids).toEqual(
			new Map([
				['dup', 'new-1'],
				['dupTag', 'new-1']
			])
		);
		expect(ids.has('c1')).toBe(false);
	});

	test('a link pasted beside its source', () => {
		const prev = [link('l1', B)];
		expect(copyIds([...prev, link('l2', B)], prev, counter())).toEqual(new Map([['l2', 'new-1']]));
	});

	test('two copies of one object at once: each takes the tag in its group', () => {
		const prev = [card('c1', A, 'g1'), tag('t1', A, 'g1')];
		const next = [
			...prev,
			card('c2', A, 'g2'),
			tag('t2', A, 'g2'),
			card('c3', A, 'g3'),
			tag('t3', A, 'g3')
		];
		expect(copyIds(next, prev, counter())).toEqual(
			new Map([
				['c2', 'new-1'],
				['t2', 'new-1'],
				['c3', 'new-2'],
				['t3', 'new-2']
			])
		);
	});

	test('two copies at once, one tag outside any group: it gets an id of its own', () => {
		const prev = [card('c1', A, 'g1')];
		const loose: Placed = { ...tag('t9', A, 'g9'), groupIds: [] };
		const next = [...prev, card('c2', A, 'g2'), card('c3', A, 'g3'), loose];
		expect(copyIds(next, prev, counter()).get('t9')).toBe('new-3');
	});

	test('one copy of a device that was ungrouped keeps its tag', () => {
		const prev = [card('c1', A, 'g1')];
		const next = [
			...prev,
			{ ...card('c2', A, 'x'), groupIds: [] },
			{ ...tag('t2', A, 'y'), groupIds: [] }
		];
		expect(copyIds(next, prev, counter())).toEqual(
			new Map([
				['c2', 'new-1'],
				['t2', 'new-1']
			])
		);
	});

	test('a tag copied without its device', () => {
		const prev = [card('c1', A, 'g1'), tag('t1', A, 'g1')];
		expect(copyIds([...prev, tag('t2', A, 'g1')], prev, counter())).toEqual(
			new Map([['t2', 'new-1']])
		);
	});
});

describe('no new id', () => {
	test('a cut and a paste: the first copy is gone', () => {
		const prev = [card('c1', A, 'g1', true), tag('t1', A, 'g1', true)];
		const next = [...prev, card('c2', A, 'g2'), tag('t2', A, 'g2')];
		expect(copyIds(next, prev, counter()).size).toBe(0);
	});

	test('a paste from another slot, where the id is new', () => {
		const prev = [card('c1', A, 'g1')];
		expect(copyIds([...prev, card('c2', B, 'g2')], prev, counter()).size).toBe(0);
	});

	test('elements already on the canvas, as those from the socket are, even when they share an id', () => {
		// Another browser's copy arrived with the id it was given there.
		const prev = [card('c1', A, 'g1'), card('c2', A, 'g2'), link('l1', B), link('l2', B)];
		expect(copyIds([...prev], prev, counter()).size).toBe(0);
		// A copy made here renames only itself, never what was already here.
		const ids = copyIds([...prev, card('c3', A, 'g3')], prev, counter());
		expect(ids).toEqual(new Map([['c3', 'new-1']]));
	});

	test('freeform shapes and lines', () => {
		const freeform: Placed = { id: 'f', type: 'rectangle', isDeleted: false, groupIds: [] };
		const unread: Placed = { ...card('u', A, 'g1'), customData: { segl: { objectId: A } } };
		const prev = [card('c1', A, 'g1')];
		expect(copyIds([...prev, freeform, unread, line('l', 'g1')], prev, counter()).size).toBe(0);
	});

	test('a copy that is deleted', () => {
		const prev = [card('c1', A, 'g1')];
		expect(copyIds([...prev, card('c2', A, 'g2', true)], prev, counter()).size).toBe(0);
	});
});

test('the default ids are random UUIDs', () => {
	const ids = copyIds([card('c1', UNPLACED, 'g1')], []);
	expect(ids.get('c1')).toMatch(
		/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/
	);
});
