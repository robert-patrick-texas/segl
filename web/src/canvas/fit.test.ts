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
import { fitArea, MAX_ZOOM, MIN_ZOOM, visibleArea } from './fit.ts';

test('a canvas shows the scene from minus its scroll, across its size over the zoom', () => {
	expect(visibleArea({ scrollX: 100, scrollY: -50, zoom: 2, width: 800, height: 600 })).toEqual({
		x: -100,
		y: 50,
		width: 400,
		height: 300
	});
});

test('a canvas of the same size fits the leader’s area exactly', () => {
	const leader = { scrollX: 120, scrollY: -40, zoom: 1.5, width: 1200, height: 700 };
	const fit = fitArea(visibleArea(leader), 1200, 700);
	expect(fit.zoom).toBeCloseTo(1.5);
	expect(fit.scrollX).toBeCloseTo(120);
	expect(fit.scrollY).toBeCloseTo(-40);
});

test('a smaller canvas shows all of the leader’s area, centred', () => {
	const view = { x: 0, y: 0, width: 1000, height: 500 };
	// Half as wide and as tall: half the zoom.
	const fit = fitArea(view, 500, 400);
	expect(fit.zoom).toBeCloseTo(0.5);
	const shown = visibleArea({ ...fit, width: 500, height: 400 });
	// All of its width, and more height than the leader's, around the same centre.
	expect(shown.x).toBeCloseTo(0);
	expect(shown.width).toBeCloseTo(1000);
	expect(shown.height).toBeCloseTo(800);
	expect(shown.y + shown.height / 2).toBeCloseTo(250);
});

test('the zoom stays within the editor’s limits', () => {
	expect(fitArea({ x: 0, y: 0, width: 1, height: 1 }, 800, 600).zoom).toBe(MAX_ZOOM);
	expect(fitArea({ x: 0, y: 0, width: 1e7, height: 1e7 }, 800, 600).zoom).toBe(MIN_ZOOM);
});
