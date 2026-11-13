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
import { ApiError } from '../api.ts';
import type { AppConfig } from '../config.ts';
import { Refused } from './files.ts';
import { httpTransport, isFinal } from './transport.ts';

const CONFIG: AppConfig = {
	rootUrl: new URL('https://dev.example.com/board/'),
	basePath: '/board/',
	editRequired: false
};
const HASH = 'a'.repeat(64);
const PNG = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0x00, 0xff]);
const FILE = {
	id: 'f'.repeat(40),
	mimeType: 'image/png',
	dataURL: 'data:image/png;base64,iVBORw0KGgoA/w=='
};
const REF = { id: FILE.id, hash: HASH, mimeType: 'image/png' };

interface Call {
	url: string;
	method: string;
	headers: Record<string, string>;
	body: Uint8Array | null;
}

/** Answer every `fetch` with one response, and keep what was asked. */
function serve(status: number, body: BodyInit, headers: Record<string, string> = {}): Call[] {
	const calls: Call[] = [];
	vi.stubGlobal('fetch', async (url: URL | string, init: RequestInit = {}) => {
		const sent = init.body instanceof Blob ? new Uint8Array(await init.body.arrayBuffer()) : null;
		calls.push({
			url: String(url),
			method: init.method ?? 'GET',
			headers: { ...(init.headers as Record<string, string>) },
			body: sent
		});
		return new Response(body, { status, headers });
	});
	return calls;
}

function json(status: number, body: unknown): Call[] {
	return serve(status, JSON.stringify(body), { 'Content-Type': 'application/json' });
}

afterEach(() => {
	vi.unstubAllGlobals();
});

describe('isFinal', () => {
	test.each([400, 403, 404, 413, 415])('a %d will not change by asking again', (status) => {
		expect(isFinal(new ApiError(status, 'refused', 'no'))).toBe(true);
	});

	test.each([408, 429, 500, 502, 503, 200])('a %d may', (status) => {
		expect(isFinal(new ApiError(status, 'busy', 'later'))).toBe(false);
	});

	test('a network failure may', () => {
		expect(isFinal(new TypeError('Failed to fetch'))).toBe(false);
	});
});

describe('upload', () => {
	test('the bytes of the data URL are posted under the mount, with their type', async () => {
		const calls = json(200, { hash: HASH, mediaType: 'image/png' });

		const hash = await httpTransport(CONFIG, 3, () => '').upload(FILE);

		expect(hash).toBe(HASH);
		expect(calls).toHaveLength(1);
		expect(calls[0]).toMatchObject({
			url: 'https://dev.example.com/board/api/v1/slots/3/assets',
			method: 'POST',
			body: PNG
		});
		expect(calls[0]!.headers['Content-Type']).toBe('image/png');
		// No pass is stored, so its header is not sent, and never a query string.
		expect(calls[0]!.headers).not.toHaveProperty('X-Segl-Edit-Token');
	});

	test('the stored pass goes in the header, read at the time of the upload', async () => {
		const calls = json(200, { hash: HASH, mediaType: 'image/png' });
		let pass = '';
		const transport = httpTransport(CONFIG, 3, () => pass);
		pass = '1800000000.q0h3JYzXb1cR5tUv7wA9-_Bd';

		await transport.upload(FILE);

		expect(calls[0]!.headers['X-Segl-Edit-Token']).toBe('1800000000.q0h3JYzXb1cR5tUv7wA9-_Bd');
		expect(calls[0]!.url).not.toContain('correct-horse');
	});

	test('a file the server refuses is refused for good', async () => {
		json(413, { error: 'payload_too_large', message: 'The body is larger than 10 bytes.' });

		const refused = httpTransport(CONFIG, 3, () => '').upload(FILE);

		await expect(refused).rejects.toBeInstanceOf(Refused);
		await expect(refused).rejects.toThrow('The body is larger than 10 bytes.');
	});

	test('a failing server is not a refusal', async () => {
		json(500, { error: 'internal_error', message: 'segl could not complete the request.' });

		const failed = httpTransport(CONFIG, 3, () => '')
			.upload(FILE)
			.catch((error) => error);

		expect(await failed).toBeInstanceOf(ApiError);
		expect(await failed).not.toBeInstanceOf(Refused);
	});

	test('an answer without a hash is not taken for one', async () => {
		json(200, { hash: '../etc/passwd' });

		await expect(httpTransport(CONFIG, 3, () => '').upload(FILE)).rejects.toThrow(
			'did not return a hash'
		);
	});

	test('a file that is not a data URL is refused without asking the server', async () => {
		const calls = json(200, { hash: HASH });
		const file = { ...FILE, dataURL: 'https://example.com/a.png' };

		await expect(httpTransport(CONFIG, 3, () => '').upload(file)).rejects.toBeInstanceOf(Refused);
		expect(calls).toEqual([]);
	});
});

describe('download', () => {
	test('the bytes come back as a data URL of the type the list names', async () => {
		// The server sends bytes and no type of its own.
		const calls = serve(200, PNG, { 'Content-Type': 'application/octet-stream' });

		const dataURL = await httpTransport(CONFIG, 3, () => 'correct-horse').download(REF);

		expect(dataURL).toBe(FILE.dataURL);
		expect(calls).toHaveLength(1);
		expect(calls[0]!.url).toBe(`https://dev.example.com/board/api/v1/assets/${HASH}`);
		// Reading a file needs no pass, and none is sent.
		expect(calls[0]!.headers).toEqual({});
	});

	test('a file the server does not have is refused for good', async () => {
		json(404, { error: 'not_found', message: 'Not Found.' });

		await expect(httpTransport(CONFIG, 3, () => '').download(REF)).rejects.toBeInstanceOf(Refused);
	});

	test('a failing server is not a refusal', async () => {
		serve(502, 'Bad Gateway');

		const failed = httpTransport(CONFIG, 3, () => '')
			.download(REF)
			.catch((error) => error);

		expect(await failed).toBeInstanceOf(ApiError);
		expect(await failed).not.toBeInstanceOf(Refused);
	});
});
