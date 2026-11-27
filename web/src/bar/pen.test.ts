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
import { penHolder, penLabel } from './pen.ts';

test('the bar says who holds the pen', () => {
	expect(penLabel(null, false)).toBe('Pen free');
	expect(penLabel('Alpha1', true)).toBe('You have the pen');
	expect(penLabel('Bravo2', false)).toBe('Pen: Bravo2');
});

test('the holder is named from who is here', () => {
	const people = [
		{ connectionId: 'a', displayName: 'Alpha1' },
		{ connectionId: 'b', displayName: null }
	];

	expect(penHolder(null, people)).toBeNull();
	expect(penHolder('a', people)).toBe('Alpha1');
	// Not yet named, or not yet in the list.
	expect(penHolder('b', people)).toBe('someone');
	expect(penHolder('z', people)).toBe('someone');
});
