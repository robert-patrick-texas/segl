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
import { ApiError } from './api.ts';
import {
	assignName,
	MAX_NAME_LENGTH,
	readStoredName,
	retryDelay,
	titleCaseName,
	usableName,
	writeStoredName
} from './names.ts';
import type { SlotStorage } from './slots.ts';

// The table the server is held to as well (tests/test_names.py).
const { cases } = JSON.parse(
	readFileSync(new URL('../../tests/display_name_cases.json', import.meta.url), 'utf8')
) as { cases: [string, string | null][] };

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

const KEY = 'segl:/board/:displayName';

describe('titleCaseName', () => {
	test('the table has the examples in the manual', () => {
		const table = new Map(cases);

		expect(table.get('john smith')).toBe('John Smith');
		expect(table.get('NASA')).toBe('Nasa');
		expect(cases.length).toBeGreaterThan(20);
	});

	test.each(cases)('%j is shown as %j', (text, shown) => {
		expect(titleCaseName(text)).toBe(shown);
	});

	test('a title-cased name is not changed by a second pass', () => {
		for (const [, shown] of cases) {
			if (shown !== null) expect(titleCaseName(shown)).toBe(shown);
		}
	});

	test('the limit is 40 characters', () => {
		expect(MAX_NAME_LENGTH).toBe(40);
	});
});

describe('usableName', () => {
	test('a label from the word file keeps its spelling', () => {
		expect(usableName('McKinley7')).toBe('McKinley7');
		expect(usableName('  Alpha1 ')).toBe('Alpha1');
	});

	test.each([null, undefined, 7, '', '   ', 'a'.repeat(41)])('%j is not a label', (value) => {
		expect(usableName(value)).toBeNull();
	});

	test('40 characters are counted as the server counts them', () => {
		expect(usableName('😀'.repeat(40))).toBe('😀'.repeat(40));
		expect(usableName('😀'.repeat(41))).toBeNull();
	});
});

describe('the stored label', () => {
	test('is null until one is stored', () => {
		expect(readStoredName(memory(), KEY)).toBeNull();
	});

	test('is what was stored, under the key that carries the mount', () => {
		const storage = memory();

		writeStoredName(storage, KEY, 'Alpha1');

		expect(storage.data.get(KEY)).toBe('Alpha1');
		expect(readStoredName(storage, KEY)).toBe('Alpha1');
		expect(readStoredName(storage, 'segl:/:displayName')).toBeNull();
	});

	test('a stored value that is not a label is ignored', () => {
		expect(readStoredName(memory({ [KEY]: '' }), KEY)).toBeNull();
		expect(readStoredName(memory({ [KEY]: 'x'.repeat(200) }), KEY)).toBeNull();
	});

	test('a browser without storage does not fail', () => {
		expect(readStoredName(null, KEY)).toBeNull();
		expect(readStoredName(blocked, KEY)).toBeNull();
		expect(() => writeStoredName(null, KEY, 'Alpha1')).not.toThrow();
		expect(() => writeStoredName(blocked, KEY, 'Alpha1')).not.toThrow();
	});
});

/** A stand-in for the server: each call takes the next name. */
function server(words = ['Guest', 'Staff']) {
	let calls = 0;
	const allocate = () => {
		calls += 1;
		return Promise.resolve(`${words[(calls - 1) % words.length]}${calls}`);
	};
	return { allocate, calls: () => calls };
}

describe('assignName', () => {
	test('a new browser asks once and stores the answer', async () => {
		const storage = memory();
		const { allocate, calls } = server();

		expect(await assignName(storage, KEY, allocate)).toBe('Guest1');
		expect(storage.data.get(KEY)).toBe('Guest1');
		expect(calls()).toBe(1);
	});

	test('a browser with a label does not ask', async () => {
		const storage = memory({ [KEY]: 'John Smith' });
		const { allocate, calls } = server();

		expect(await assignName(storage, KEY, allocate)).toBe('John Smith');
		expect(await assignName(storage, KEY, allocate)).toBe('John Smith');
		expect(calls()).toBe(0);
	});

	test('a later visit keeps the first label', async () => {
		const storage = memory();
		const { allocate, calls } = server();

		const first = await assignName(storage, KEY, allocate);
		const second = await assignName(storage, KEY, allocate);

		expect([first, second]).toEqual(['Guest1', 'Guest1']);
		expect(calls()).toBe(1);
	});

	test('callers that arrive together share one request', async () => {
		const storage = memory();
		const { allocate, calls } = server();

		const names = await Promise.all([
			assignName(storage, KEY, allocate),
			assignName(storage, KEY, allocate),
			assignName(storage, KEY, allocate)
		]);

		expect(names).toEqual(['Guest1', 'Guest1', 'Guest1']);
		expect(calls()).toBe(1);
	});

	test('two mounts on one origin each get a label', async () => {
		const storage = memory();
		const { allocate } = server();

		const names = await Promise.all([
			assignName(storage, KEY, allocate),
			assignName(storage, 'segl:/:displayName', allocate)
		]);

		expect(names).toEqual(['Guest1', 'Staff2']);
	});

	test('a label stored while the request was out stays', async () => {
		const storage = memory();
		let answer: (name: string) => void = () => {};
		const waiting = assignName(storage, KEY, () => new Promise((resolve) => (answer = resolve)));

		// Another tab finished first, or the person typed a name.
		writeStoredName(storage, KEY, 'John Smith');
		answer('Guest1');

		expect(await waiting).toBe('John Smith');
		expect(storage.data.get(KEY)).toBe('John Smith');
	});

	test('a refusal stores nothing, and the next call asks again', async () => {
		const storage = memory();
		const refused = new ApiError(429, 'rate_limited', 'Too many names.', 12);
		const { allocate, calls } = server();

		await expect(assignName(storage, KEY, () => Promise.reject(refused))).rejects.toBe(refused);
		expect(storage.data.has(KEY)).toBe(false);

		expect(await assignName(storage, KEY, allocate)).toBe('Guest1');
		expect(calls()).toBe(1);
	});

	test('an answer that is not a label is refused and not stored', async () => {
		const storage = memory();

		await expect(assignName(storage, KEY, () => Promise.resolve('   '))).rejects.toThrow(
			'cannot use'
		);
		expect(storage.data.has(KEY)).toBe(false);
	});

	test('without storage the page still gets a label', async () => {
		const { allocate } = server();

		expect(await assignName(null, KEY, allocate)).toBe('Guest1');
		expect(await assignName(blocked, KEY, allocate)).toBe('Staff2');
	});
});

describe('retryDelay', () => {
	test('a refusal for asking too often says when', () => {
		expect(retryDelay(new ApiError(429, 'rate_limited', 'Too many names.', 12))).toBe(12_000);
	});

	test('anything else is tried again in half a minute', () => {
		expect(retryDelay(new TypeError('Failed to fetch'))).toBe(30_000);
		expect(retryDelay(new ApiError(500, 'internal_error', 'segl failed.'))).toBe(30_000);
	});

	test('the wait is at least a second and at most five minutes', () => {
		expect(retryDelay(new ApiError(429, 'rate_limited', 'Too many names.', 0))).toBe(1_000);
		expect(retryDelay(new ApiError(429, 'rate_limited', 'Too many names.', 86_400))).toBe(300_000);
	});
});
