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
import { parseServerMessage } from './protocol.ts';

const parse = (message: unknown) => parseServerMessage(JSON.stringify(message));

const welcome = {
	type: 'welcome',
	slot: 3,
	title: 'Workspace 3',
	epoch: 1,
	viewOnly: false,
	connectionId: 'c1',
	participants: [
		{ connectionId: 'c1', displayName: 'Guest1' },
		{ connectionId: 'c2', displayName: null }
	]
};
const rectangle = { id: 'a', version: 1, versionNonce: 5, type: 'rectangle' };

describe('parseServerMessage', () => {
	test('a welcome', () => {
		expect(parse(welcome)).toEqual(welcome);
	});

	test('a scene and elements keep every field of an element', () => {
		expect(parse({ type: 'scene', epoch: 2, elements: [rectangle], files: [] })).toEqual({
			type: 'scene',
			epoch: 2,
			elements: [rectangle]
		});
		expect(parse({ type: 'elements', epoch: 2, elements: [rectangle] })).toEqual({
			type: 'elements',
			epoch: 2,
			elements: [rectangle]
		});
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

	test('an error', () => {
		expect(
			parse({ type: 'error', error: 'view_only', message: 'Editing needs the token.' })
		).toEqual({ type: 'error', error: 'view_only', message: 'Editing needs the token.' });
		expect(parse({ type: 'error', error: 'view_only' })).toEqual({
			type: 'error',
			error: 'view_only',
			message: 'view_only'
		});
	});

	test.each([
		// A type from a later segl is ignored, not an error.
		{ type: 'saved', epoch: 1, savedAt: '2026-11-12T09:00:00.000Z' },
		{ type: 'files', files: [] },
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
		{ type: 'presence-end' },
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
