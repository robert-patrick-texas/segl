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
import { markOf, MAX_MARK_LENGTH, parseServerMessage } from './protocol.ts';

const parse = (message: unknown) => parseServerMessage(JSON.stringify(message));

const welcome = {
	type: 'welcome',
	slot: 3,
	title: 'Workspace 3',
	epoch: 1,
	viewOnly: false,
	editEndsIn: 43199.75,
	connectionId: 'c1',
	participants: [
		{ connectionId: 'c1', displayName: 'Guest1' },
		{ connectionId: 'c2', displayName: null }
	],
	version: '0.9.0'
};
const rectangle = { id: 'a', version: 1, versionNonce: 5, type: 'rectangle' };
const png = { id: 'f'.repeat(40), hash: 'a'.repeat(64), mimeType: 'image/png' };

describe('parseServerMessage', () => {
	test('a welcome', () => {
		expect(parse(welcome)).toEqual(welcome);
	});

	test('a welcome whose pass has no end, and one that is about to end', () => {
		expect(parse({ ...welcome, editEndsIn: null })).toEqual({ ...welcome, editEndsIn: null });
		expect(parse({ ...welcome, editEndsIn: 0 })).toEqual({ ...welcome, editEndsIn: 0 });
		expect(parse({ ...welcome, editEndsIn: 0.001 })).toEqual({ ...welcome, editEndsIn: 0.001 });
	});

	test.each([undefined, '60', -1, -0.001, true, [60], { seconds: 60 }])(
		'a welcome with %j where the length goes is still a welcome, with no length',
		(editEndsIn) => {
			// The server refuses an edit after the end whatever the page knows.
			const { editEndsIn: _left, ...without } = welcome;
			const sent = editEndsIn === undefined ? without : { ...welcome, editEndsIn };

			expect(parse(sent)).toEqual({ ...welcome, editEndsIn: null });
		}
	);

	test.each([undefined, null, '', 9, ['0.9.0']])(
		'a welcome with %j where the version goes is still a welcome, of no known version',
		(version) => {
			const { version: _left, ...without } = welcome;
			const sent = version === undefined ? without : { ...welcome, version };

			expect(parse(sent)).toEqual({ ...welcome, version: null });
		}
	);

	test('a length too large to hold is no length', () => {
		// JSON text can say it, and a browser reads it as infinity.
		const text = JSON.stringify(welcome).replace('43199.75', '1e999');
		expect(text).toContain('"editEndsIn":1e999');

		expect(parseServerMessage(text)).toEqual({ ...welcome, editEndsIn: null });
	});

	test('a scene and elements keep every field of an element', () => {
		expect(parse({ type: 'scene', epoch: 2, elements: [rectangle], files: [] })).toEqual({
			type: 'scene',
			epoch: 2,
			elements: [rectangle],
			files: [],
			whole: true,
			mark: null
		});
		expect(parse({ type: 'elements', epoch: 2, elements: [rectangle] })).toEqual({
			type: 'elements',
			epoch: 2,
			elements: [rectangle]
		});
	});

	test('a scene carries the files its images name', () => {
		expect(parse({ type: 'scene', epoch: 1, elements: [], files: [png] })).toEqual({
			type: 'scene',
			epoch: 1,
			elements: [],
			files: [png],
			whole: true,
			mark: null
		});
		// A scene from a segl older than the file list has no such field.
		expect(parse({ type: 'scene', epoch: 1, elements: [] })).toEqual({
			type: 'scene',
			epoch: 1,
			elements: [],
			files: [],
			whole: true,
			mark: null
		});
	});

	test('a scene says whether it is whole, and carries its mark', () => {
		const changes = { type: 'scene', epoch: 1, elements: [], files: [], whole: false };
		expect(parse({ ...changes, mark: 'c0ffee.1.7' })).toEqual({ ...changes, mark: 'c0ffee.1.7' });
		expect(parse({ ...changes, whole: true, mark: 'c0ffee.1.7' })).toMatchObject({
			whole: true
		});
	});

	test.each([undefined, null, 0, 'false', []])(
		'a scene with %j where whole goes is whole',
		(whole) => {
			// Only a scene that says it is not whole is laid over what the page has.
			expect(parse({ type: 'scene', epoch: 1, elements: [], files: [], whole })).toMatchObject({
				whole: true
			});
		}
	);

	test.each([undefined, null, 7, ['a'], { mark: 'a' }, 'x'.repeat(MAX_MARK_LENGTH + 1)])(
		'a scene with %j where the mark goes has none',
		(mark) => {
			// The server refuses a hello whose mark is not one, so the page never sends it.
			expect(parse({ type: 'scene', epoch: 1, elements: [], files: [], mark })).toMatchObject({
				mark: null
			});
		}
	);

	test('files another browser added', () => {
		expect(parse({ type: 'files', epoch: 1, files: [png] })).toEqual({
			type: 'files',
			epoch: 1,
			files: [png]
		});
		// Only the three fields are kept.
		expect(parse({ type: 'files', epoch: 1, files: [{ ...png, dataURL: 'data:,' }] })).toEqual({
			type: 'files',
			epoch: 1,
			files: [png]
		});
	});

	test('saved, with the number of the newest message that is on the disk', () => {
		const saved = { type: 'saved', epoch: 1, savedAt: '2026-11-12T09:00:00.000Z', seq: 4 };

		expect(parse(saved)).toEqual(saved);
	});

	test('a slot title', () => {
		expect(parse({ type: 'slot', slot: 4, title: 'Core' })).toEqual({
			type: 'slot',
			slot: 4,
			title: 'Core'
		});
	});

	test('presence, with a cursor and without', () => {
		const who = { connectionId: 'c2', displayName: 'Staff2' };

		expect(parse({ type: 'presence', ...who, cursor: { x: 1.5, y: -2 } })).toEqual({
			type: 'presence',
			...who,
			cursor: { x: 1.5, y: -2 }
		});
		expect(parse({ type: 'presence', ...who, cursor: null })).toEqual({
			type: 'presence',
			...who,
			cursor: null
		});
	});

	test('a departure', () => {
		expect(parse({ type: 'presence-end', connectionId: 'c2' })).toEqual({
			type: 'presence-end',
			connectionId: 'c2'
		});
	});

	test('a cursor on slot 9, with its page or with none', () => {
		const who = { connectionId: 'c2', displayName: 'Staff2' };
		expect(parse({ type: 'presence', ...who, cursor: { x: 1, y: 2, page: 'p1' } })).toEqual({
			type: 'presence',
			...who,
			cursor: { x: 1, y: 2, page: 'p1' }
		});
		expect(parse({ type: 'presence', ...who, cursor: { x: 1, y: 2, page: null } })).toEqual({
			type: 'presence',
			...who,
			cursor: { x: 1, y: 2, page: null }
		});
	});

	test('how many follow, and a view to follow (T18)', () => {
		expect(parse({ type: 'followers', count: 2 })).toEqual({ type: 'followers', count: 2 });
		const view = { x: -10, y: 4.5, width: 800, height: 600 };
		expect(parse({ type: 'view', connectionId: 'c2', view })).toEqual({
			type: 'view',
			connectionId: 'c2',
			view
		});
		expect(parse({ type: 'view', connectionId: 'c2', view: { ...view, page: 'p1' } })).toEqual({
			type: 'view',
			connectionId: 'c2',
			view: { ...view, page: 'p1' }
		});
	});

	test('an error', () => {
		expect(
			parse({ type: 'error', error: 'view_only', message: 'Editing needs an access code.' })
		).toEqual({ type: 'error', error: 'view_only', message: 'Editing needs an access code.' });
		expect(parse({ type: 'error', error: 'view_only' })).toEqual({
			type: 'error',
			error: 'view_only',
			message: 'view_only'
		});
	});

	test.each([
		// A type from a later segl is ignored, not an error.
		{ type: 'restored', epoch: 2 },
		{ type: 'saved', epoch: 1, savedAt: '2026-11-12T09:00:00.000Z' },
		{ type: 'saved', epoch: 1, savedAt: '2026-11-12T09:00:00.000Z', seq: '4' },
		{ type: 'saved', epoch: 1, savedAt: 1794474000, seq: 4 },
		{ type: 'saved', epoch: null, savedAt: '2026-11-12T09:00:00.000Z', seq: 4 },
		{ type: 'files', files: [] },
		{ type: 'files', epoch: 1 },
		{ type: 'files', epoch: 1, files: {} },
		{ type: 'files', epoch: 1, files: [{ ...png, hash: 'A'.repeat(64) }] },
		{ type: 'files', epoch: 1, files: [{ ...png, mimeType: 'text/html' }] },
		{ type: 'files', epoch: 1, files: [png, { id: png.id }] },
		{ type: 'scene', epoch: 1, elements: [], files: [{ ...png, id: '../x' }] },
		{ type: 'scene', epoch: 1, elements: [], files: 'none' },
		{},
		[],
		null,
		'welcome',
		{ ...welcome, slot: '3' },
		{ ...welcome, title: null },
		{ ...welcome, epoch: 1.5 },
		{ ...welcome, viewOnly: 'no' },
		{ ...welcome, connectionId: 7 },
		{ ...welcome, participants: {} },
		{ ...welcome, participants: [{ connectionId: 'c1' }] },
		{ ...welcome, participants: [{ connectionId: '', displayName: 'x' }] },
		{ ...welcome, participants: [{ connectionId: 'c1', displayName: 7 }] },
		{ type: 'scene', epoch: 1 },
		{ type: 'scene', epoch: '1', elements: [] },
		{ type: 'scene', epoch: 1, elements: [{ id: 'a' }] },
		{ type: 'elements', epoch: 1, elements: {} },
		{ type: 'elements', epoch: 1, elements: [rectangle, 'b'] },
		{ type: 'slot', slot: 4 },
		{ type: 'slot', title: 'Core' },
		{ type: 'presence', connectionId: 'c2', displayName: 'x' },
		{ type: 'presence', connectionId: 'c2', displayName: 'x', cursor: 'here' },
		{ type: 'presence', connectionId: 'c2', displayName: 'x', cursor: { x: 1 } },
		{ type: 'presence', connectionId: 'c2', displayName: 'x', cursor: { x: '1', y: 2 } },
		{ type: 'presence', displayName: 'x', cursor: null },
		{ type: 'presence', connectionId: 'c2', displayName: 'x', cursor: { x: 1, y: 2, page: 3 } },
		{ type: 'presence', connectionId: 'c2', displayName: 'x', cursor: { x: 1, y: 2, page: '' } },
		{ type: 'presence-end' },
		{ type: 'followers' },
		{ type: 'followers', count: -1 },
		{ type: 'followers', count: 1.5 },
		{ type: 'view', view: { x: 0, y: 0, width: 1, height: 1 } },
		{ type: 'view', connectionId: 'c2' },
		{ type: 'view', connectionId: 'c2', view: { x: 0, y: 0, width: 0, height: 1 } },
		{ type: 'view', connectionId: 'c2', view: { x: 0, y: 0, width: 1, height: -1 } },
		{ type: 'view', connectionId: 'c2', view: { x: '0', y: 0, width: 1, height: 1 } },
		{ type: 'view', connectionId: 'c2', view: { x: 0, y: 0, width: 1, height: 1, page: 7 } },
		{ type: 'error' }
	])('%j is not a message this page acts on', (message) => {
		expect(parse(message)).toBeNull();
	});

	test.each(['', '{', 'NaN', undefined, null, 7, new ArrayBuffer(4)])(
		'%j is not a message at all',
		(data) => {
			expect(parseServerMessage(data)).toBeNull();
		}
	);
});

describe('markOf', () => {
	test('a mark is text of at most 64 characters, handed back as it came', () => {
		expect(markOf('c0ffee.1.7')).toBe('c0ffee.1.7');
		expect(markOf('')).toBe('');
		expect(markOf('x'.repeat(MAX_MARK_LENGTH))).toBe('x'.repeat(MAX_MARK_LENGTH));
	});

	test.each([undefined, null, 7, true, ['a'], 'x'.repeat(MAX_MARK_LENGTH + 1)])(
		'%j is no mark',
		(value) => {
			expect(markOf(value)).toBeNull();
		}
	);
});
