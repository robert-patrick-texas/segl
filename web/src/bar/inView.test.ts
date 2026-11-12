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
import { EDGE_MARGIN, shiftIntoView } from './inView.ts';

test('a panel with room to the right stays under its button', () => {
	expect(shiftIntoView(575, 352, 1280)).toBe(0);
	// Exactly the margin left over is still room.
	expect(shiftIntoView(100, 352, 100 + 352 + EDGE_MARGIN)).toBe(0);
});

test('a panel that would pass the right edge moves left by what it is over', () => {
	// At 390 pixels the button is at 222: the panel would end at 574.
	expect(shiftIntoView(222, 352, 390)).toBe(196);
	expect(222 - 196 + 352).toBe(390 - EDGE_MARGIN);
	// One pixel over is one pixel moved.
	expect(shiftIntoView(100, 352, 100 + 352 + EDGE_MARGIN - 1)).toBe(1);
	// A long title pushes the button right on a wide screen too.
	expect(shiftIntoView(1100, 352, 1280)).toBe(184);
});

test('it never moves past the left margin', () => {
	// A panel wider than the page starts at the margin, and is cut off on the right.
	expect(shiftIntoView(200, 600, 390)).toBe(200 - EDGE_MARGIN);
	// A button already left of the margin is not moved right either.
	expect(shiftIntoView(4, 600, 390)).toBe(0);
});

test('the margin can be another', () => {
	expect(shiftIntoView(222, 352, 390, 0)).toBe(184);
	expect(shiftIntoView(222, 352, 390, 24)).toBe(198);
});
