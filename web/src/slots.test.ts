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
import { parseSlot, readLastSlot, SLOT_NUMBERS, writeLastSlot, type SlotStorage } from './slots.ts';

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

const KEY = 'segl:/board/:lastSlot';

describe('parseSlot', () => {
	test('the nine slots', () => {
		expect(SLOT_NUMBERS.map((number) => parseSlot(String(number)))).toEqual([...SLOT_NUMBERS]);
	});

	// The same texts the server refuses (tests/test_slots.py).
	test.each(['0', '10', '-1', '99', '01', '+1', '1.0', '1e0', 'abc', ' 1', '1 ', '', '١', '１'])(
		'%j is not a slot',
		(text) => {
			expect(parseSlot(text)).toBeNull();
		}
	);

	test('nothing is not a slot', () => {
		expect(parseSlot(undefined)).toBeNull();
		expect(parseSlot(null)).toBeNull();
	});
});

describe('the last slot', () => {
	test('is null until one is stored', () => {
		expect(readLastSlot(memory(), KEY)).toBeNull();
	});

	test('is what was stored, under the key it was stored with', () => {
		const storage = memory();

		writeLastSlot(storage, KEY, 4);

		expect(storage.data.get(KEY)).toBe('4');
		expect(readLastSlot(storage, KEY)).toBe(4);
		expect(readLastSlot(storage, 'segl:/:lastSlot')).toBeNull();
	});

	test('a stored value that is not a slot is ignored', () => {
		expect(readLastSlot(memory({ [KEY]: '12' }), KEY)).toBeNull();
		expect(readLastSlot(memory({ [KEY]: 'abc' }), KEY)).toBeNull();
	});

	test('a browser without storage opens slot 1 and does not fail', () => {
		expect(readLastSlot(null, KEY)).toBeNull();
		expect(readLastSlot(blocked, KEY)).toBeNull();
		expect(() => writeLastSlot(null, KEY, 3)).not.toThrow();
		expect(() => writeLastSlot(blocked, KEY, 3)).not.toThrow();
	});
});
