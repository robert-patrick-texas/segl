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

/**
 * segl's network symbols, as plain shapes (N-001, N-002; D2-038). The canvas
 * adapter, `web/src/canvas/network.ts`, turns them into the editor's elements.
 *
 * A device is a card: a rounded rectangle that holds the device's name as
 * its label, at the bottom, with a glyph above it. The glyph is drawn with
 * lines only. The editor binds a link's end to a shape near its outline, and
 * never to a line, so a link drawn to a device ends on its card.
 *
 * No symbol names a color. The editor's default ink draws them, and color is
 * the team's (D2-038).
 */
import { DEVICE_KINDS, LINK_KINDS, type DeviceKind, type LinkKind } from './kinds.ts';

export type Point = readonly [number, number];

/** A line through its points, straight or curved. A path whose ends meet is closed. */
export interface Path {
	readonly points: readonly Point[];
	readonly curved: boolean;
}

export interface DeviceSymbol {
	readonly kind: DeviceKind;
	/** The lines drawn on the card, in the card's own coordinates. */
	readonly glyph: readonly Path[];
}

/** Every card's size. The glyph stays in its top part, clear of the tag's corner. */
export const CARD = { width: 120, height: 100 } as const;

/** Where the glyph may draw: above the label, and left of the tag. */
export const GLYPH_AREA = { left: 24, top: 6, right: 96, bottom: 64 } as const;

/** The size of a label's and a tag's text, the editor's small size. */
export const TEXT_SIZE = 16;

/** How far a device's tag sits from the card's top and right edges. */
export const TAG_INSET = 6;

/** How long a link from the library is. */
export const LINK_LENGTH = 160;

const straight = (...points: Point[]): Path => ({ points, curved: false });
const curved = (...points: Point[]): Path => ({ points, curved: true });

/** A closed box from one corner to the other. */
function box(left: number, top: number, right: number, bottom: number): Path {
	return straight([left, top], [right, top], [right, bottom], [left, bottom], [left, top]);
}

/** A closed curve that reads as a circle. */
function ring(cx: number, cy: number, r: number): Path {
	const points: Point[] = [];
	for (let step = 0; step <= 12; step += 1) {
		const angle = (step % 12) * (Math.PI / 6);
		points.push([round(cx + r * Math.cos(angle)), round(cy + r * Math.sin(angle))]);
	}
	return curved(...points);
}

function round(value: number): number {
	return Math.round(value * 10) / 10;
}

const GLYPHS: Readonly<Record<DeviceKind, readonly Path[]>> = {
	// A circle with two crossed arrows.
	router: [
		ring(60, 36, 24),
		straight([52, 22], [46, 22], [46, 28], [46, 22], [74, 50], [68, 50], [74, 50], [74, 44]),
		straight([68, 22], [74, 22], [74, 28], [74, 22], [46, 50], [52, 50], [46, 50], [46, 44])
	],
	// A box with two arrows the opposite way.
	switch: [
		box(32, 16, 88, 56),
		straight([42, 29], [78, 29], [72, 24], [78, 29], [72, 34]),
		straight([78, 43], [42, 43], [48, 38], [42, 43], [48, 48])
	],
	// A brick wall.
	firewall: [
		box(32, 14, 88, 56),
		straight([32, 28], [46, 28], [46, 42], [46, 28], [74, 28], [74, 42], [74, 28], [88, 28]),
		straight([32, 42], [60, 42], [60, 56], [60, 42], [88, 42]),
		straight([60, 14], [60, 28])
	],
	// A base with a mast and two waves.
	wireless_ap: [
		box(44, 46, 76, 58),
		straight([60, 46], [60, 38]),
		curved([50, 34], [60, 28], [70, 34]),
		curved([42, 26], [60, 16], [78, 26])
	],
	// A tower of three bays.
	server: [box(44, 8, 76, 60), straight([44, 25], [76, 25], [76, 42], [44, 42])],
	// A screen on a stand.
	workstation: [box(34, 12, 86, 46), straight([60, 46], [60, 56], [46, 56], [74, 56])],
	// Paper in, the printer, paper out.
	printer: [
		straight([46, 24], [46, 10], [74, 10], [74, 24]),
		box(34, 24, 86, 46),
		straight([46, 40], [46, 58], [74, 58], [74, 40])
	],
	// A handset over a base with keys.
	voip_phone: [
		curved([34, 30], [40, 20], [60, 16], [80, 20], [86, 30]),
		box(38, 34, 82, 58),
		box(52, 40, 68, 52)
	],
	// A phone: the case, the speaker, the button.
	mobile: [box(48, 6, 72, 60), straight([56, 12], [64, 12]), ring(60, 54, 2.5)],
	// A box with a prompt.
	host: [box(36, 14, 84, 56), straight([44, 26], [52, 33], [44, 40]), straight([56, 40], [68, 40])],
	// A cloud: a provider's transport.
	cloud: [
		curved(
			[38, 52],
			[30, 45],
			[34, 35],
			[44, 31],
			[50, 21],
			[63, 18],
			[73, 24],
			[78, 31],
			[88, 36],
			[89, 46],
			[82, 52],
			[38, 52]
		)
	],
	// A question mark: none of the other kinds.
	other: [
		curved([50, 24], [53, 15], [61, 12], [69, 16], [70, 25], [62, 32], [60, 42]),
		ring(60, 52, 2.5)
	]
};

/** The 12 device symbols, in the order the library shows them. */
export const DEVICE_SYMBOLS: readonly DeviceSymbol[] = DEVICE_KINDS.map((kind) => ({
	kind,
	glyph: GLYPHS[kind]
}));

/** What a link's kind sets on its line, and nothing else (D2-038). */
export interface LineStyle {
	readonly strokeStyle: 'solid' | 'dashed' | 'dotted';
	/** The editor's widths: 1 thin, 2 its default, 4 its widest. */
	readonly strokeWidth: 1 | 2 | 4;
	readonly startArrowhead: 'circle' | null;
	readonly endArrowhead: 'circle' | null;
}

export const LINE_STYLES: Readonly<Record<LinkKind, LineStyle>> = {
	cable: { strokeStyle: 'solid', strokeWidth: 1, startArrowhead: null, endArrowhead: null },
	circuit: { strokeStyle: 'solid', strokeWidth: 4, startArrowhead: null, endArrowhead: null },
	neighbor: { strokeStyle: 'dashed', strokeWidth: 2, startArrowhead: null, endArrowhead: null },
	relationship: { strokeStyle: 'dotted', strokeWidth: 2, startArrowhead: null, endArrowhead: null },
	connector: {
		strokeStyle: 'solid',
		strokeWidth: 1,
		startArrowhead: 'circle',
		endArrowhead: 'circle'
	}
};

/** The 5 link kinds, in the order the library shows them. */
export const LINK_SYMBOLS: readonly LinkKind[] = LINK_KINDS;

/** Where a device's tag goes: inside its card's top right corner. */
export function tagPlace(
	card: { x: number; y: number; width: number },
	tag: { width: number }
): { x: number; y: number } {
	return { x: card.x + card.width - TAG_INSET - tag.width, y: card.y + TAG_INSET };
}
