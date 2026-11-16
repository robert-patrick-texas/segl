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
import { DEVICE_KINDS, KIND_NAMES, LINK_KINDS } from './kinds.ts';
import {
	CARD,
	DEVICE_SYMBOLS,
	GLYPH_AREA,
	LINE_STYLES,
	LINK_SYMBOLS,
	TAG_INSET,
	tagPlace
} from './symbols.ts';

describe('the 12 device symbols', () => {
	test('are the 12 kinds, in order, with "other" for the rest and no "unknown"', () => {
		expect(DEVICE_SYMBOLS.map((symbol) => symbol.kind)).toEqual([
			'router',
			'switch',
			'firewall',
			'wireless_ap',
			'server',
			'workstation',
			'printer',
			'voip_phone',
			'mobile',
			'host',
			'cloud',
			'other'
		]);
		expect(DEVICE_KINDS).toHaveLength(12);
		expect(DEVICE_KINDS as readonly string[]).not.toContain('unknown');
	});

	test.each(DEVICE_SYMBOLS)('$kind has a name and a glyph inside its area', ({ kind, glyph }) => {
		expect(KIND_NAMES[kind]).toMatch(/^\S/);
		expect(glyph.length).toBeGreaterThan(0);
		for (const path of glyph) {
			expect(path.points.length).toBeGreaterThanOrEqual(2);
			for (const [x, y] of path.points) {
				expect(x).toBeGreaterThanOrEqual(GLYPH_AREA.left);
				expect(x).toBeLessThanOrEqual(GLYPH_AREA.right);
				expect(y).toBeGreaterThanOrEqual(GLYPH_AREA.top);
				expect(y).toBeLessThanOrEqual(GLYPH_AREA.bottom);
			}
		}
	});

	test('no two kinds share a glyph', () => {
		const drawn = DEVICE_SYMBOLS.map(({ glyph }) => JSON.stringify(glyph));
		expect(new Set(drawn).size).toBe(12);
	});

	test('the glyph area is inside the card', () => {
		expect(GLYPH_AREA.left).toBeGreaterThan(0);
		expect(GLYPH_AREA.top).toBeGreaterThan(0);
		expect(GLYPH_AREA.right).toBeLessThan(CARD.width);
		expect(GLYPH_AREA.bottom).toBeLessThan(CARD.height);
	});
});

describe('the 5 line styles', () => {
	test('are the 5 kinds, in order', () => {
		expect(LINK_SYMBOLS).toEqual(['cable', 'circuit', 'neighbor', 'relationship', 'connector']);
		expect(LINK_KINDS).toHaveLength(5);
	});

	// The table in draft2/TASKS.md, T15.
	test.each([
		['cable', 'solid', 1, null],
		['circuit', 'solid', 4, null],
		['neighbor', 'dashed', 2, null],
		['relationship', 'dotted', 2, null],
		['connector', 'solid', 1, 'circle']
	] as const)('%s: %s, width %d, ends %s', (kind, strokeStyle, strokeWidth, end) => {
		expect(LINE_STYLES[kind]).toEqual({
			strokeStyle,
			strokeWidth,
			startArrowhead: end,
			endArrowhead: end
		});
	});

	test('cable is thinner than circuit, and no two kinds look alike', () => {
		expect(LINE_STYLES.cable.strokeWidth).toBeLessThan(LINE_STYLES.circuit.strokeWidth);
		const looks = LINK_KINDS.map((kind) => JSON.stringify(LINE_STYLES[kind]));
		expect(new Set(looks).size).toBe(5);
	});

	test('no line style names a color', () => {
		for (const kind of LINK_KINDS) {
			expect(Object.keys(LINE_STYLES[kind]).sort()).toEqual([
				'endArrowhead',
				'startArrowhead',
				'strokeStyle',
				'strokeWidth'
			]);
		}
	});
});

describe("a device's tag", () => {
	test('sits inside the top right corner of the card', () => {
		const card = { x: 100, y: 50, width: CARD.width };
		expect(tagPlace(card, { width: 10 })).toEqual({
			x: 100 + CARD.width - TAG_INSET - 10,
			y: 50 + TAG_INSET
		});
	});

	test('is clear of every glyph', () => {
		// The editor's widest tag letter at the label size is under 12 px.
		const { x } = tagPlace({ x: 0, y: 0, width: CARD.width }, { width: 12 });
		expect(x).toBeGreaterThan(GLYPH_AREA.right);
	});

	test('follows a card that was made wider', () => {
		expect(tagPlace({ x: 0, y: 0, width: 300 }, { width: 10 }).x).toBe(300 - TAG_INSET - 10);
	});
});
