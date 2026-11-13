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

import {
	existsSync,
	mkdirSync,
	mkdtempSync,
	readdirSync,
	readFileSync,
	rmSync,
	writeFileSync
} from 'node:fs';
import { tmpdir } from 'node:os';
import { join, sep } from 'node:path';
import { afterEach, beforeEach, expect, test } from 'vitest';
import {
	EDITOR_FONTS,
	REPLACED_FONTS,
	fontFile,
	replaceFonts,
	replacedFonts
} from './editor-fonts.ts';

let root = '';

beforeEach(() => {
	root = mkdtempSync(join(tmpdir(), 'segl-fonts-'));
});

afterEach(() => {
	rmSync(root, { recursive: true, force: true });
});

function write(path: string, text: string): void {
	const file = join(root, path);
	mkdirSync(join(file, '..'), { recursive: true });
	writeFileSync(file, text);
}

test('the pinned editor ships its fonts where the build copies them from', () => {
	expect(existsSync(EDITOR_FONTS)).toBe(true);
	const families = readdirSync(EDITOR_FONTS);

	// The hand-drawn default, and the code font: the editor asks for these by path.
	expect(families).toContain('Excalifont');
	expect(families).toContain('Cascadia');
	expect(existsSync(join(EDITOR_FONTS, 'Cascadia', 'CascadiaCode-Regular.woff2'))).toBe(true);
});

test('a dev-server request names a font file inside the folder', () => {
	expect(fontFile('/Virgil/Virgil-Regular.woff2', '/fonts')).toBe(
		['', 'fonts', 'Virgil', 'Virgil-Regular.woff2'].join(sep)
	);
	expect(fontFile('/Virgil/Virgil-Regular.woff2?v=1', '/fonts')).toBe(
		['', 'fonts', 'Virgil', 'Virgil-Regular.woff2'].join(sep)
	);
});

test.each([
	'/../package.json',
	'/../../secret.woff2',
	'/%2e%2e/%2e%2e/secret.woff2',
	'/Virgil/',
	'/Virgil/notes.txt',
	'/%E0%A4%A'
])('%s is not a font file', (path) => {
	expect(fontFile(path, '/fonts')).toBeNull();
});

test("segl replaces the editor's Liberation Sans, and nothing else", () => {
	expect(replacedFonts()).toEqual(['Liberation/LiberationSans-Regular.woff2']);
});

test('each replaced font is a file the pinned editor ships, and not the same bytes', () => {
	for (const path of replacedFonts()) {
		const own = readFileSync(join(EDITOR_FONTS, path));
		const replacement = readFileSync(join(REPLACED_FONTS, path));

		// A WOFF2 file, and another one than the editor's.
		expect(replacement.subarray(0, 4).toString('latin1')).toBe('wOF2');
		expect(replacement.equals(own)).toBe(false);
	}
});

test('only font files count as replacements, in any family folder', () => {
	write('replaced/Beta/Beta-Regular.woff2', 'new beta');
	write('replaced/Alpha/Alpha-Bold.woff2', 'new alpha');
	write('replaced/Alpha/README.md', 'notes');
	write('replaced/notes.txt', 'notes');

	expect(replacedFonts(join(root, 'replaced'))).toEqual([
		'Alpha/Alpha-Bold.woff2',
		'Beta/Beta-Regular.woff2'
	]);
	expect(replacedFonts(join(root, 'absent'))).toEqual([]);
});

test("a replaced font goes over the copy of the editor's file, and the others stay", () => {
	write('editor/Alpha/Alpha-Regular.woff2', 'editor alpha');
	write('editor/Beta/Beta-Regular.woff2', 'editor beta');
	write('dist/Alpha/Alpha-Regular.woff2', 'editor alpha');
	write('dist/Beta/Beta-Regular.woff2', 'editor beta');
	write('replaced/Beta/Beta-Regular.woff2', 'new beta');

	const replaced = replaceFonts(join(root, 'dist'), join(root, 'replaced'), join(root, 'editor'));

	expect(replaced).toEqual(['Beta/Beta-Regular.woff2']);
	expect(readFileSync(join(root, 'dist/Beta/Beta-Regular.woff2'), 'utf8')).toBe('new beta');
	expect(readFileSync(join(root, 'dist/Alpha/Alpha-Regular.woff2'), 'utf8')).toBe('editor alpha');
	// The editor's own folder is not written to.
	expect(readFileSync(join(root, 'editor/Beta/Beta-Regular.woff2'), 'utf8')).toBe('editor beta');
});

test('a replacement for a file the editor does not ship stops the build, and copies nothing', () => {
	write('editor/Alpha/Alpha-Regular.woff2', 'editor alpha');
	write('dist/Alpha/Alpha-Regular.woff2', 'editor alpha');
	write('replaced/Alpha/Alpha-Regular.woff2', 'new alpha');
	write('replaced/Gone/Gone-Regular.woff2', 'new');

	expect(() =>
		replaceFonts(join(root, 'dist'), join(root, 'replaced'), join(root, 'editor'))
	).toThrow('fonts/Gone/Gone-Regular.woff2 replaces a file the editor does not ship');
	expect(existsSync(join(root, 'dist/Gone'))).toBe(false);
	expect(readFileSync(join(root, 'dist/Alpha/Alpha-Regular.woff2'), 'utf8')).toBe('editor alpha');
});
