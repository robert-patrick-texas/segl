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
import { bytesToDataUrl, dataUrlToBytes } from './dataurl.ts';

const PNG = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0x00, 0xff]);

describe('dataUrlToBytes', () => {
	test('a base64 URL gives its type and its bytes', () => {
		expect(dataUrlToBytes('data:image/png;base64,iVBORw0KGgoA/w==')).toEqual({
			mimeType: 'image/png',
			bytes: PNG
		});
	});

	test('the type is read in lower case, and other parameters are passed over', () => {
		const read = dataUrlToBytes('data:IMAGE/SVG+XML;charset=utf-8;base64,PHN2Zy8+');

		expect(read?.mimeType).toBe('image/svg+xml');
		expect(new TextDecoder().decode(read?.bytes)).toBe('<svg/>');
	});

	test('a URL that is not base64 is percent-encoded text, as UTF-8', () => {
		const read = dataUrlToBytes('data:image/svg+xml,%3Csvg%3E%C3%A9%3C/svg%3E');

		expect(new TextDecoder().decode(read?.bytes)).toBe('<svg>é</svg>');
	});

	test('a URL may name no type, and hold nothing', () => {
		expect(dataUrlToBytes('data:,')).toEqual({ mimeType: '', bytes: new Uint8Array(0) });
		expect(dataUrlToBytes('data:;base64,')).toEqual({ mimeType: '', bytes: new Uint8Array(0) });
	});

	test.each([
		['', 'no text'],
		['image/png;base64,AAAA', 'no scheme'],
		['https://example.com/a.png', 'another scheme'],
		['data:image/png;base64', 'no comma'],
		['data:image/png;base64,@@@', 'not base64'],
		['data:image/png,%E0%A4%A', 'a broken percent sign']
	])('%j is not a data URL (%s)', (url) => {
		expect(dataUrlToBytes(url)).toBeNull();
	});
});

describe('bytesToDataUrl', () => {
	test('bytes become a base64 URL of the type given', () => {
		expect(bytesToDataUrl('image/png', PNG)).toBe('data:image/png;base64,iVBORw0KGgoA/w==');
	});

	test('no bytes are an empty URL', () => {
		expect(bytesToDataUrl('image/gif', new Uint8Array(0))).toBe('data:image/gif;base64,');
	});

	test('every byte value comes back, in a file larger than one piece', () => {
		const bytes = new Uint8Array(200_000);
		for (let index = 0; index < bytes.length; index += 1) bytes[index] = (index * 7) % 256;

		const read = dataUrlToBytes(bytesToDataUrl('image/webp', bytes));

		expect(read?.mimeType).toBe('image/webp');
		expect(read?.bytes).toEqual(bytes);
	});
});
