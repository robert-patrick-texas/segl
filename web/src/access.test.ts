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

import { afterEach, describe, expect, test, vi } from 'vitest';
import {
	isTyped,
	NO_CODE_NEEDED,
	NOT_REACHED,
	outcomeWords,
	refusalOutcome,
	returnSlot,
	waitWords,
	WRONG_CODE
} from './access.ts';
import { ApiError, requestPass } from './api.ts';
import { resolveConfig } from './config.ts';

const CONFIG = resolveConfig(
	{ root: './', editRequired: true },
	'https://dev.example.com/board/access'
);
const PASS = '1800000000.q0h3JYzXb1cR5tUv7wA9-_Bd';

describe('what the server answered for a code', () => {
	test('a wrong code', () => {
		expect(refusalOutcome(new ApiError(403, 'wrong_code', 'No.'))).toEqual({ kind: 'wrong' });
	});

	test('an address that has to wait, with the wait the server named', () => {
		expect(refusalOutcome(new ApiError(429, 'rate_limited', 'Later.', 900))).toEqual({
			kind: 'wait',
			seconds: 900
		});
		expect(refusalOutcome(new ApiError(429, 'rate_limited', 'Later.'))).toEqual({
			kind: 'wait',
			seconds: null
		});
	});

	test('a segl that asks for no code', () => {
		expect(refusalOutcome(new ApiError(404, 'no_access_codes', 'None.'))).toEqual({
			kind: 'open'
		});
	});

	test.each([
		new ApiError(500, 'internal_error', 'segl could not complete the request.'),
		new ApiError(403, 'bad_origin', 'Another site.'),
		new ApiError(403, 'outside_network', 'Outside.'),
		new ApiError(400, 'bad_request', 'Not a code.'),
		new ApiError(200, 'unexpected', 'No pass.'),
		new ApiError(502, 'not_json', 'A proxy answered.'),
		new TypeError('Failed to fetch'),
		'a string',
		null,
		undefined
	])('anything else is a failure, and promises nothing: %s', (error) => {
		expect(refusalOutcome(error)).toEqual({ kind: 'failed' });
	});
});

describe('the words for an outcome', () => {
	test('a wrong code is said, and the code is not repeated', () => {
		expect(outcomeWords({ kind: 'wrong' })).toBe(WRONG_CODE);
		expect(WRONG_CODE).toBe("That is not one of this segl's access codes.");
	});

	test.each<[number | null, string]>([
		[900, 'in 15 minutes'],
		[899, 'in 15 minutes'],
		[841, 'in 15 minutes'],
		[840, 'in 14 minutes'],
		[120, 'in 2 minutes'],
		[61, 'in 2 minutes'],
		[60, 'in 1 minute'],
		[59, 'in less than a minute'],
		[1, 'in less than a minute'],
		[0, 'in less than a minute'],
		[null, 'later']
	])('a wait of %j seconds is "%s"', (seconds, words) => {
		expect(waitWords(seconds)).toBe(words);
		expect(outcomeWords({ kind: 'wait', seconds })).toBe(
			`Too many wrong codes came from this address. Try again ${words}.`
		);
	});

	test('a segl without codes says that everyone can edit', () => {
		expect(outcomeWords({ kind: 'open' })).toBe(NO_CODE_NEEDED);
		expect(NO_CODE_NEEDED).toBe('This segl asks for no access code. Everyone can edit.');
	});

	test('a failure says to try again, and not that the code was wrong', () => {
		expect(outcomeWords({ kind: 'failed' })).toBe(NOT_REACHED);
		expect(NOT_REACHED).not.toContain('code');
	});

	test('a pass has no words: the page leaves', () => {
		expect(outcomeWords({ kind: 'pass', pass: PASS })).toBe('');
	});
});

describe('what is worth sending', () => {
	test.each(['maple river 42', ' x ', '0'])('%j is', (code) => {
		expect(isTyped(code)).toBe(true);
	});

	test.each(['', ' ', '\t\n', '   '])('%j is not', (code) => {
		expect(isTyped(code)).toBe(false);
	});
});

describe('where the person goes afterwards', () => {
	test('back to the slot the bar handed over', () => {
		expect(returnSlot({ slot: 7 }, 3)).toBe(7);
		expect(returnSlot({ slot: 1 }, null)).toBe(1);
		expect(returnSlot({ slot: 9 }, 2)).toBe(9);
	});

	test.each([
		null,
		undefined,
		{},
		'7',
		7,
		{ slot: 0 },
		{ slot: 10 },
		{ slot: '07' },
		{ slot: 'abc' },
		{ slot: null },
		{ slot: 2.5 },
		{ slot: [4] },
		{ from: 4 }
	])('with %j in the history entry, to the last slot this browser opened', (state) => {
		expect(returnSlot(state, 4)).toBe(4);
	});

	test('and to slot 1 when it has opened none', () => {
		expect(returnSlot(null, null)).toBe(1);
		expect(returnSlot({ slot: 'x' }, null)).toBe(1);
	});

	test('a slot written as text in the entry is a slot', () => {
		expect(returnSlot({ slot: '6' }, 1)).toBe(6);
	});
});

interface Call {
	url: string;
	method: string | undefined;
	headers: Record<string, string>;
	body: string;
}

/** A `fetch` that records each call and answers with `status` and `body`. */
function answering(status: number, body: unknown, headers: Record<string, string> = {}): Call[] {
	const calls: Call[] = [];
	vi.stubGlobal('fetch', (url: URL | string, init: RequestInit = {}) => {
		calls.push({
			url: String(url),
			method: init.method,
			headers: { ...(init.headers as Record<string, string>) },
			body: String(init.body)
		});
		return Promise.resolve(
			new Response(typeof body === 'string' ? body : JSON.stringify(body), { status, headers })
		);
	});
	return calls;
}

describe('asking the server', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	test("the code goes in the body of a POST under segl's root, and in no address", async () => {
		const calls = answering(200, { pass: PASS, expiresAt: '2027-01-15T20:00:00.000Z' });

		await expect(requestPass(CONFIG, 'Maple River 42')).resolves.toBe(PASS);

		expect(calls).toHaveLength(1);
		expect(calls[0]!.url).toBe('https://dev.example.com/board/api/v1/access');
		expect(calls[0]!.method).toBe('POST');
		expect(JSON.parse(calls[0]!.body)).toEqual({ code: 'Maple River 42' });
		expect(calls[0]!.headers['Content-Type']).toBe('application/json');
		// No pass is sent to buy a pass, and the code is in no header.
		expect(Object.keys(calls[0]!.headers).sort()).toEqual(['Accept', 'Content-Type']);
		expect(calls[0]!.url).not.toContain('Maple');
	});

	test('the code is sent as typed: the server is the one that compares', async () => {
		const calls = answering(200, { pass: PASS, expiresAt: null });

		await requestPass(CONFIG, '  MAPLE-river  42 ');

		expect(JSON.parse(calls[0]!.body)).toEqual({ code: '  MAPLE-river  42 ' });
	});

	test.each<[number, unknown, Record<string, string>, unknown]>([
		[403, { error: 'wrong_code', message: 'No.' }, {}, { kind: 'wrong' }],
		[
			429,
			{ error: 'rate_limited', message: 'Later.' },
			{ 'Retry-After': '900' },
			{ kind: 'wait', seconds: 900 }
		],
		[404, { error: 'no_access_codes', message: 'None.' }, {}, { kind: 'open' }],
		[403, { error: 'bad_origin', message: 'Another site.' }, {}, { kind: 'failed' }],
		[502, '<html>Bad Gateway</html>', {}, { kind: 'failed' }],
		// An answer that is not what docs/API.md says buys nothing.
		[200, {}, {}, { kind: 'failed' }],
		[200, { pass: '' }, {}, { kind: 'failed' }],
		[200, { pass: 7 }, {}, { kind: 'failed' }],
		[200, null, {}, { kind: 'failed' }]
	])('an answer of %i %j is %j', async (status, body, headers, outcome) => {
		answering(status, body, headers);

		const error = await requestPass(CONFIG, 'a code').then(
			() => null,
			(thrown: unknown) => thrown
		);

		expect(error).not.toBeNull();
		expect(refusalOutcome(error)).toEqual(outcome);
	});

	test('a server that cannot be reached is a failure', async () => {
		vi.stubGlobal('fetch', () => Promise.reject(new TypeError('Failed to fetch')));

		const error = await requestPass(CONFIG, 'a code').catch((thrown: unknown) => thrown);

		expect(refusalOutcome(error)).toEqual({ kind: 'failed' });
	});
});
