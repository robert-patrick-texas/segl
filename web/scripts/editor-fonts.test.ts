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

import { existsSync, readdirSync } from 'node:fs';
import { join, sep } from 'node:path';
import { expect, test } from 'vitest';
import { EDITOR_FONTS, fontFile } from './editor-fonts.ts';

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
