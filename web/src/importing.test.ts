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
import { ApiError, importScene } from './api.ts';
import type { AppConfig } from './config.ts';
import {
	dropGoesTo,
	exportName,
	goesToImport,
	IMPORT_NEEDS_TOKEN,
	importProblem,
	nameHeader
} from './importing.ts';

describe('a drop on the canvas', () => {
	const SCENE = { name: 'network.excalidraw', type: '' };
	const IMAGE = { name: 'photo.png', type: 'image/png' };
	const LIBRARY = { name: 'shapes.excalidrawlib', type: '' };

	test('an editor: a scene file goes to the import, and the rest to the editor', () => {
		expect(dropGoesTo(SCENE, false)).toBe('import');
		expect(dropGoesTo(IMAGE, false)).toBe('editor');
		expect(dropGoesTo(LIBRARY, false)).toBe('editor');
		// A dragged link, or a shape out of the library: no file at all.
		expect(dropGoesTo(null, false)).toBe('editor');
	});

	test("a viewer: nothing reaches the editor, which would place it on the viewer's canvas alone", () => {
		expect(dropGoesTo(IMAGE, true)).toBe('nowhere');
		expect(dropGoesTo(LIBRARY, true)).toBe('nowhere');
		expect(dropGoesTo(null, true)).toBe('nowhere');
	});

	test('a viewer: a scene file still goes to the import, which says what it needs', () => {
		expect(dropGoesTo(SCENE, true)).toBe('import');
	});
});

describe('a file dropped on the canvas', () => {
	test.each([
		['network.excalidraw', ''],
		['network.excalidraw', 'application/vnd.excalidraw+json'],
		['network.json', 'application/json'],
		['NETWORK.EXCALIDRAW', ''],
		['scene', ''],
		['notes.txt', 'text/plain'],
		['report.pdf', 'application/pdf'],
		// Not a type the editor places as an image, so it would try to open it.
		['scan.tiff', 'image/tiff'],
		// Named like an image, and of another type: the type is what the editor goes by.
		['notes.png', 'text/plain'],
		['png', '']
	])('%s of type "%s" goes to the import', (name, type) => {
		expect(goesToImport({ name, type })).toBe(true);
	});

	test.each([
		['photo.png', 'image/png'],
		['photo.jpg', 'image/jpeg'],
		['logo.svg', 'image/svg+xml'],
		['photo.PNG', 'IMAGE/PNG'],
		// Named like a scene, and an image by its type: the editor places it.
		['odd.excalidraw', 'image/webp'],
		// No type from the browser: the name says it is an image.
		['photo.avif', ''],
		['PHOTO.JPEG', ''],
		['old.jfif', '']
	])('%s of type "%s" is an image, and stays the editor\'s', (name, type) => {
		expect(goesToImport({ name, type })).toBe(false);
	});

	test.each([
		['shapes.excalidrawlib', ''],
		['SHAPES.EXCALIDRAWLIB', 'application/json'],
		['shapes', 'application/vnd.excalidrawlib+json']
	])('%s of type "%s" is a library, and stays the editor\'s', (name, type) => {
		expect(goesToImport({ name, type })).toBe(false);
	});
});

describe('the name of an exported file', () => {
	test.each([
		['Core network', 'Core network'],
		['  Core   network  ', 'Core network'],
		['Workspace 4', 'Workspace 4'],
		['Zürich – 北京', 'Zürich – 北京'],
		['a/b\\c:d*e?f"g<h>i|j', 'a b c d e f g h i j'],
		['../../etc/passwd', 'etc passwd'],
		['.hidden', 'hidden'],
		['ends with dots...', 'ends with dots'],
		['tab\there', 'tab here'],
		['bell\u0007here', 'bell here'],
		['v1.2 draft', 'v1.2 draft']
	])('the title %j gives %j', (title, name) => {
		expect(exportName(title, 4)).toBe(name);
	});

	test.each([undefined, '', '   ', '...', '///', '?'])(
		'the title %j has nothing a file name keeps, so the slot names it',
		(title) => {
			expect(exportName(title, 4)).toBe('slot-4');
		}
	);
});

test('a display name is a header as percent-encoded text', () => {
	expect(nameHeader('Guest1')).toBe('Guest1');
	expect(nameHeader('John Smith')).toBe('John%20Smith');
	expect(nameHeader('José')).toBe('Jos%C3%A9');
	// Nothing in it can end the header or start another.
	expect(nameHeader('a\r\nX-Segl-Edit-Token: b')).toBe('a%0D%0AX-Segl-Edit-Token%3A%20b');
	expect(nameHeader('北京')).toMatch(/^[\x21-\x7e]+$/);
});

class Refused extends Error {
	readonly code: string;

	constructor(code: string, message: string) {
		super(message);
		this.code = code;
	}
}

describe('an import that failed', () => {
	test('a refusal is put in words by its code', () => {
		expect(importProblem(new Refused('view_only', 'Editing needs the edit token.'))).toBe(
			IMPORT_NEEDS_TOKEN
		);
		expect(importProblem(new Refused('payload_too_large', 'The body is larger.'))).toBe(
			'That file is larger than this segl takes.'
		);
		expect(importProblem(new Refused('invalid_document', 'element 2 is not…'))).toBe(
			'That is not an Excalidraw file.'
		);
		expect(importProblem(new Refused('bad_request', 'The body is a JSON object.'))).toBe(
			'That is not an Excalidraw file.'
		);
	});

	test('any other failure is told in its own words', () => {
		expect(
			importProblem(new Refused('internal_error', 'segl could not complete the request.'))
		).toBe('segl could not complete the request.');
		expect(importProblem(new TypeError('Failed to fetch'))).toBe('Failed to fetch');
	});

	test('a failure with no words gets some', () => {
		expect(importProblem(new Error(''))).toBe('segl could not import that file.');
		expect(importProblem('no')).toBe('segl could not import that file.');
		expect(importProblem(null)).toBe('segl could not import that file.');
		expect(importProblem({ code: 7 })).toBe('segl could not import that file.');
	});
});

const CONFIG: AppConfig = {
	rootUrl: new URL('https://dev.example.com/board/'),
	basePath: '/board/',
	editRequired: false
};
const TOKEN = 'correct-horse-battery';
const EXPORTED = '{\n  "type": "excalidraw",\n  "elements": []\n}';

interface Call {
	url: string;
	method: string;
	headers: Record<string, string>;
	body: string | null;
}

/** Answer every `fetch` with one response, and keep what was asked. */
function serve(status: number, body: unknown): Call[] {
	const calls: Call[] = [];
	vi.stubGlobal('fetch', async (url: URL | string, init: RequestInit = {}) => {
		calls.push({
			url: String(url),
			method: init.method ?? 'GET',
			headers: { ...(init.headers as Record<string, string>) },
			body: init.body instanceof Blob ? await init.body.text() : null
		});
		return new Response(typeof body === 'string' ? body : JSON.stringify(body), { status });
	});
	return calls;
}

describe('the import call', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	test('the file goes to the import route under the mount, as it is', async () => {
		const calls = serve(200, { revision: 4, epoch: 3, savedAt: '2026-11-12T09:00:00.000Z' });
		const file = new File([EXPORTED], 'network.excalidraw');

		const result = await importScene(CONFIG, 7, file, 'José Ana', '');

		expect(result).toEqual({ revision: 4, epoch: 3 });
		expect(calls).toEqual([
			{
				url: 'https://dev.example.com/board/api/v1/slots/7/import',
				method: 'POST',
				headers: {
					Accept: 'application/json',
					'Content-Type': 'application/json',
					'X-Segl-Display-Name': 'Jos%C3%A9%20Ana'
				},
				body: EXPORTED
			}
		]);
	});

	test('the edit token goes in its header, and never in the URL', async () => {
		const calls = serve(200, { revision: 1, epoch: 2 });

		await importScene(CONFIG, 7, new Blob([EXPORTED]), 'Guest1', TOKEN);

		expect(calls[0]!.headers['X-Segl-Edit-Token']).toBe(TOKEN);
		expect(calls[0]!.url).not.toContain(TOKEN);
		expect(calls[0]!.body).not.toContain(TOKEN);
	});

	test('a browser without a name sends no name header', async () => {
		const calls = serve(200, { revision: 1, epoch: 2 });

		await importScene(CONFIG, 7, new Blob([EXPORTED]), null, '');

		expect(Object.keys(calls[0]!.headers).sort()).toEqual(['Accept', 'Content-Type']);
	});

	test.each([
		[403, 'view_only', IMPORT_NEEDS_TOKEN],
		[413, 'payload_too_large', 'That file is larger than this segl takes.'],
		[422, 'invalid_document', 'That is not an Excalidraw file.'],
		[400, 'bad_request', 'That is not an Excalidraw file.']
	])('a %d with %s is thrown with its code', async (status, code, words) => {
		serve(status, { error: code, message: 'no' });

		const thrown = await importScene(CONFIG, 7, new Blob(['x']), 'Guest1', '').catch(
			(error: unknown) => error
		);

		expect(thrown).toBeInstanceOf(ApiError);
		expect([(thrown as ApiError).status, (thrown as ApiError).code]).toEqual([status, code]);
		expect(importProblem(thrown)).toBe(words);
	});

	test.each([{}, { revision: 4 }, { revision: '4', epoch: 3 }, { revision: 4, epoch: 1.5 }, null])(
		'an answer of %j is not what an import answers',
		async (body) => {
			serve(200, body);

			await expect(importScene(CONFIG, 7, new Blob(['x']), 'Guest1', '')).rejects.toMatchObject({
				code: 'unexpected'
			});
		}
	);
});
