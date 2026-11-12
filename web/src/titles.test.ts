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

import { expect, test } from 'vitest';
import { cleanTitle, MAX_TITLE_LENGTH } from './titles.ts';

test("the limit is the server's", () => {
	expect(MAX_TITLE_LENGTH).toBe(80);
});

test.each([
	['Core network', 'Core network'],
	['  padded\t', 'padded'],
	['x'.repeat(80), 'x'.repeat(80)],
	[` ${'x'.repeat(80)} `, 'x'.repeat(80)],
	// 80 characters, 160 UTF-16 units: the server counts characters.
	['😀'.repeat(80), '😀'.repeat(80)],
	['Réseau cœur', 'Réseau cœur']
])('%j is kept as %j', (typed, kept) => {
	expect(cleanTitle(typed)).toBe(kept);
});

test.each(['', '   ', '\t\n', 'x'.repeat(81), '😀'.repeat(81)])('%j is not a title', (typed) => {
	expect(cleanTitle(typed)).toBeNull();
});
