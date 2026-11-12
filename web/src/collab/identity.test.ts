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

import { expect, test } from 'vitest';
import type { SlotStorage } from '../slots.ts';
import { newClientId, readClientId, readEditToken } from './identity.ts';

function memory(initial: Record<string, string> = {}): SlotStorage & { data: Map<string, string> } {
	const data = new Map(Object.entries(initial));
	return {
		data,
		getItem: (key) => data.get(key) ?? null,
		setItem: (key, value) => void data.set(key, value)
	};
}

const blocked: SlotStorage = {
	getItem: () => {
		throw new Error('storage is blocked');
	},
	setItem: () => {
		throw new Error('storage is blocked');
	}
};

const KEY = 'segl:/board/:clientId';
// What the server takes in `hello` (src/segl/room.py).
const SERVER_SHAPE = /^[A-Za-z0-9_-]{1,64}$/;

test('a new id has the shape the server takes, and is not the last one', () => {
	const one = newClientId();
	const two = newClientId();

	expect(one).toMatch(/^[0-9a-f]{32}$/);
	expect(one).toMatch(SERVER_SHAPE);
	expect(two).not.toBe(one);
});

test('the first call makes an id and stores it', () => {
	const storage = memory();

	const id = readClientId(storage, KEY, () => 'made-1');

	expect(id).toBe('made-1');
	expect(storage.data.get(KEY)).toBe('made-1');
});

test('a stored id is kept', () => {
	const storage = memory({ [KEY]: 'stored-1' });

	expect(readClientId(storage, KEY, () => 'made-1')).toBe('stored-1');
	expect(storage.data.get(KEY)).toBe('stored-1');
});

test.each(['', 'has space', 'x'.repeat(65), 'né'])(
	'a stored %j is not an id, and is replaced',
	(stored) => {
		const storage = memory({ [KEY]: stored });

		expect(readClientId(storage, KEY, () => 'made-1')).toBe('made-1');
		expect(storage.data.get(KEY)).toBe('made-1');
	}
);

test('a browser without storage gets an id for the page', () => {
	expect(readClientId(blocked, KEY, () => 'made-1')).toBe('made-1');
	expect(readClientId(null, KEY, () => 'made-2')).toBe('made-2');
});

test('the edit token is read as stored, and is empty when there is none', () => {
	const key = 'segl:/board/:editToken';

	expect(readEditToken(memory({ [key]: 'correct-horse' }), key)).toBe('correct-horse');
	expect(readEditToken(memory(), key)).toBe('');
	expect(readEditToken(blocked, key)).toBe('');
	expect(readEditToken(null, key)).toBe('');
});
