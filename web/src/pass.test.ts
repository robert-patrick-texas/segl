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
import { isSendable, readPass, writePass } from './pass.ts';
import type { SlotStorage } from './slots.ts';

// What a page can, and cannot, send in a header. tests/test_access.py reads the same file.
const CASES = (
	JSON.parse(
		readFileSync(new URL('../../tests/header_value_cases.json', import.meta.url), 'utf8')
	) as { cases: [string, boolean][] }
).cases;

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

// The key's last part is from when it held a token.
const KEY = 'segl:/board/:editToken';
// A pass as the server issues one: the second of its issue, and a signature.
const PASS = '1800000000.q0h3JYzXb1cR5tUv7wA9-_Bd';

describe('what a page can send in a header', () => {
	test('the table has both kinds', () => {
		expect(CASES.filter(([, sendable]) => sendable).length).toBeGreaterThanOrEqual(5);
		expect(CASES.filter(([, sendable]) => !sendable).length).toBeGreaterThanOrEqual(5);
	});

	test.each(CASES)('%j: %j', (text, sendable) => {
		expect(isSendable(text)).toBe(sendable);
	});

	test('a pass is well inside it', () => {
		expect(isSendable(PASS)).toBe(true);
		expect(PASS.length).toBeLessThan(256);
	});
});

describe('the stored pass', () => {
	test('it is read as stored, and is empty when there is none', () => {
		expect(readPass(memory({ [KEY]: PASS }), KEY)).toBe(PASS);
		expect(readPass(memory(), KEY)).toBe('');
		expect(readPass(blocked, KEY)).toBe('');
		expect(readPass(null, KEY)).toBe('');
	});

	test.each(['k€', ' x', 'x ', 'a\nb', 'x'.repeat(257)])(
		'a stored %j is no pass: a header could not carry it',
		(stored) => {
			expect(readPass(memory({ [KEY]: stored }), KEY)).toBe('');
		}
	);

	test('what an earlier build stored there, a token, is sent as it is, and the server says no', () => {
		// The page does not judge a pass. The server does, and the bar then
		// says that this browser's access has ended.
		expect(readPass(memory({ [KEY]: 'S3gl+e2e/Token==' }), KEY)).toBe('S3gl+e2e/Token==');
	});

	test('the key carries the mount, so another mount on the same host has its own', () => {
		const storage = memory({ 'segl:/:editToken': PASS });

		expect(readPass(storage, KEY)).toBe('');
	});

	test('a pass is written under the key', () => {
		const storage = memory();

		writePass(storage, KEY, PASS);

		expect(storage.data).toEqual(new Map([[KEY, PASS]]));
		expect(readPass(storage, KEY)).toBe(PASS);
	});

	test('a newer pass takes the place of the one stored before', () => {
		const storage = memory({ [KEY]: PASS });

		writePass(storage, KEY, '1800043200.AAAAAAAAAAAAAAAAAAAAAAAA');

		expect(readPass(storage, KEY)).toBe('1800043200.AAAAAAAAAAAAAAAAAAAAAAAA');
	});

	test('a browser that refuses storage does not stop the page', () => {
		expect(() => writePass(blocked, KEY, PASS)).not.toThrow();
		expect(() => writePass(null, KEY, PASS)).not.toThrow();
	});
});
