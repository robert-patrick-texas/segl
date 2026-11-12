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
	afterAnswer,
	afterLink,
	afterStorage,
	isToken,
	readEditToken,
	startingToken,
	takeEditLink,
	tokenFromFragment,
	writeEditToken,
	type LinkTarget,
	type TokenState
} from './editToken.ts';
import type { SlotStorage } from './slots.ts';

// What is, and is not, an edit token. tests/test_config.py reads the same file.
const CASES = (
	JSON.parse(
		readFileSync(new URL('../../tests/edit_token_cases.json', import.meta.url), 'utf8')
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

const KEY = 'segl:/board/:editToken';

describe('what a token is', () => {
	test('the table has both kinds', () => {
		expect(CASES.filter(([, usable]) => usable).length).toBeGreaterThanOrEqual(5);
		expect(CASES.filter(([, usable]) => !usable).length).toBeGreaterThanOrEqual(5);
	});

	test.each(CASES)('%j: %j, as on the server', (text, usable) => {
		expect(isToken(text)).toBe(usable);
	});
});

describe('the fragment of a link', () => {
	test.each([
		['#e=s3cret', 's3cret'],
		// What `openssl rand -base64` writes: none of these is an escape or a separator.
		['#e=S3gl+e2e/Token==', 'S3gl+e2e/Token=='],
		['#e=S3gl%2Be2e%2FToken%3D%3D', 'S3gl+e2e/Token=='],
		// A browser writes a typed space as %20.
		['#e=correct%20horse%20battery', 'correct horse battery'],
		// A plus is a plus. Only a form turns it into a space.
		['#e=a+b', 'a+b'],
		// The rest of the fragment is the token, whatever is in it.
		['#e=a&b=c', 'a&b=c'],
		['#e=a#b', 'a#b'],
		['#e=e=', 'e='],
		['#e=100%25', '100%'],
		['#e=%41', 'A']
	])('%s carries %j', (hash, token) => {
		expect(tokenFromFragment(hash)).toBe(token);
	});

	test.each([
		'',
		'#',
		'#e',
		'#E=s3cret',
		'#x=1&e=s3cret',
		'#edit=s3cret',
		'# e=s3cret',
		'#json=abc',
		'e=s3cret'
	])('%j is not an edit link, and is left alone', (hash) => {
		expect(tokenFromFragment(hash)).toBeNull();
	});

	test.each([
		// No token at all.
		'#e=',
		// A percent sign that starts no escape: the link was not encoded, or was cut.
		'#e=100%',
		'#e=%',
		'#e=%zz',
		// Half a character.
		'#e=%C3',
		// Decoded, these are not tokens: a space at an end, a line break, a
		// letter a header cannot carry, and one too long.
		'#e=%20x',
		'#e=x%20',
		'#e=a%0Ab',
		'#e=kve%C3%B0ja',
		'#e=k%E2%82%AC',
		`#e=${'x'.repeat(257)}`
	])('%j is an edit link with no usable token', (hash) => {
		expect(tokenFromFragment(hash)).toBe('');
	});

	test('every token in the table comes back out of a link made with encodeURIComponent', () => {
		for (const [text, usable] of CASES) {
			if (usable) expect(tokenFromFragment(`#e=${encodeURIComponent(text)}`)).toBe(text);
		}
	});

	test('nothing in the table that is not a token comes out of a link', () => {
		for (const [text, usable] of CASES) {
			if (!usable) expect(tokenFromFragment(`#e=${encodeURIComponent(text)}`)).toBe('');
		}
	});
});

/** An address bar and its history entry. */
function address(hash: string, state: unknown = { idx: 0 }) {
	const replaced: { state: unknown; title: string; url: string }[] = [];
	const target: LinkTarget = {
		location: { hash, pathname: '/board/s/3', search: '' },
		history: {
			state,
			replaceState: (next: unknown, title: string, url?: string | URL | null) => {
				replaced.push({ state: next, title, url: String(url) });
			}
		}
	};
	return { target, replaced };
}

describe('taking the token out of the address', () => {
	test('the token is returned, and the fragment goes', () => {
		const { target, replaced } = address('#e=S3gl+e2e/Token==');

		expect(takeEditLink(target)).toBe('S3gl+e2e/Token==');
		// The entry is replaced, so Back does not bring the link back. The
		// router's state in it is kept.
		expect(replaced).toEqual([{ state: { idx: 0 }, title: '', url: '/board/s/3' }]);
	});

	test('a query string stays', () => {
		const { target, replaced } = address('#e=s3cret');
		target.location = { hash: '#e=s3cret', pathname: '/s/1', search: '?x=1' };

		takeEditLink(target);

		expect(replaced.map((entry) => entry.url)).toEqual(['/s/1?x=1']);
	});

	test.each(['#e=', '#e=100%', '#e=kve%C3%B0ja', '#e=a%0Ab'])(
		'the fragment of %j goes too, though it gives no token',
		(hash) => {
			const { target, replaced } = address(hash);

			expect(takeEditLink(target)).toBeNull();
			expect(replaced.map((entry) => entry.url)).toEqual(['/board/s/3']);
		}
	);

	test.each(['', '#', '#json=abc', '#x=1&e=s3cret'])(
		'an address with %j is not touched',
		(hash) => {
			const { target, replaced } = address(hash);

			expect(takeEditLink(target)).toBeNull();
			expect(replaced).toEqual([]);
		}
	);

	test('a history entry without a state keeps none', () => {
		const { target, replaced } = address('#e=s3cret', null);

		takeEditLink(target);

		expect(replaced).toEqual([{ state: null, title: '', url: '/board/s/3' }]);
	});
});

describe('the stored token', () => {
	test('it is read as stored, and is empty when there is none', () => {
		expect(readEditToken(memory({ [KEY]: 'correct horse' }), KEY)).toBe('correct horse');
		expect(readEditToken(memory(), KEY)).toBe('');
		expect(readEditToken(blocked, KEY)).toBe('');
		expect(readEditToken(null, KEY)).toBe('');
	});

	test.each(['k€', ' x', 'a\nb', 'x'.repeat(257)])(
		'a stored %j is no token: a header could not carry it',
		(stored) => {
			expect(readEditToken(memory({ [KEY]: stored }), KEY)).toBe('');
		}
	);

	test('the key carries the mount, so another mount on the same host has its own', () => {
		const storage = memory({ 'segl:/:editToken': 'the-root-one' });

		expect(readEditToken(storage, KEY)).toBe('');
	});

	test('a token is written under the key', () => {
		const storage = memory();

		writeEditToken(storage, KEY, 's3cret');

		expect(storage.data).toEqual(new Map([[KEY, 's3cret']]));
	});

	test('a browser that refuses storage does not stop the page', () => {
		expect(() => writeEditToken(blocked, KEY, 's3cret')).not.toThrow();
		expect(() => writeEditToken(null, KEY, 's3cret')).not.toThrow();
	});
});

const STORED: TokenState = { token: 'stored', unproven: false };
const NONE: TokenState = { token: '', unproven: false };
const LINKED: TokenState = { token: 'linked', unproven: true };

describe('where a page starts', () => {
	test('with the stored token', () => {
		expect(startingToken(null, 'stored')).toEqual(STORED);
	});

	test('with none', () => {
		expect(startingToken(null, '')).toEqual(NONE);
	});

	test('with the token of the link it was opened by, which is still to be proven', () => {
		expect(startingToken('linked', '')).toEqual(LINKED);
		expect(startingToken('linked', 'stored')).toEqual(LINKED);
	});

	test('a link with the stored token proves nothing new', () => {
		expect(startingToken('stored', 'stored')).toEqual(STORED);
	});
});

describe('a link opened in the tab while the page is open', () => {
	test('its token is the one to say hello with, and is still to be proven', () => {
		expect(afterLink(STORED, 'linked')).toEqual(LINKED);
		expect(afterLink(NONE, 'linked')).toEqual(LINKED);
	});

	test('the same token again changes nothing, so there is no new hello', () => {
		expect(afterLink(STORED, 'stored')).toBe(STORED);
		expect(afterLink(LINKED, 'linked')).toBe(LINKED);
	});
});

describe('what the server answered', () => {
	test("a link's token that the server took is stored", () => {
		expect(afterAnswer(LINKED, 'linked', false, '')).toEqual({
			state: { token: 'linked', unproven: false },
			store: 'linked'
		});
	});

	test('and takes the place of the one stored before', () => {
		expect(afterAnswer(LINKED, 'linked', false, 'stored')).toEqual({
			state: { token: 'linked', unproven: false },
			store: 'linked'
		});
	});

	test("a link's token that the server refused is not stored, and the stored one is back", () => {
		// The link that any page on the web can make a browser open.
		expect(afterAnswer(LINKED, 'linked', true, 'stored')).toEqual({
			state: STORED,
			store: null
		});
	});

	test('with nothing stored, a refused token stays for the page, and is not stored', () => {
		// So the bar can say that this browser has a token, and that it is wrong.
		expect(afterAnswer(LINKED, 'linked', true, '')).toEqual({
			state: { token: 'linked', unproven: false },
			store: null
		});
	});

	test('a refused token that is the stored one stays too, with nothing better to go back to', () => {
		const state: TokenState = { token: 'stored', unproven: true };

		expect(afterAnswer(state, 'stored', true, 'stored')).toEqual({
			state: { token: 'stored', unproven: false },
			store: null
		});
	});

	test('an answer for a token the page has moved on from is late, and changes nothing', () => {
		expect(afterAnswer(LINKED, 'stored', false, 'stored')).toEqual({ state: LINKED, store: null });
		expect(afterAnswer(LINKED, '', true, '')).toEqual({ state: LINKED, store: null });
	});

	test('an answer for a token that is not from a link stores nothing', () => {
		// Also when the server refuses the stored token: it stays where it is,
		// and the bar says that it is wrong.
		expect(afterAnswer(STORED, 'stored', false, 'stored')).toEqual({ state: STORED, store: null });
		expect(afterAnswer(STORED, 'stored', true, 'stored')).toEqual({ state: STORED, store: null });
		expect(afterAnswer(NONE, '', true, '')).toEqual({ state: NONE, store: null });
	});

	test('the same state object comes back when nothing changed', () => {
		expect(afterAnswer(STORED, 'stored', false, 'stored').state).toBe(STORED);
	});
});

describe('another tab stored a token', () => {
	test('this page takes it', () => {
		expect(afterStorage(NONE, 'stored')).toEqual(STORED);
	});

	test("also over a link's token the server has not answered for: the stored one is proven", () => {
		expect(afterStorage(LINKED, 'stored')).toEqual(STORED);
	});

	test("the site's data was cleared: this page has no token either", () => {
		expect(afterStorage(STORED, '')).toEqual(NONE);
	});

	test('the same token changes nothing', () => {
		expect(afterStorage(STORED, 'stored')).toBe(STORED);
	});
});
