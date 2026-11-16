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
 * Helpers for the network objects' browser tests (docs/TEST-PLAN.md T-022):
 * the library, placing and moving an object, the panel, and reading records
 * and tags from the scene.
 *
 * The expected kinds and line styles are written out here, from the task's
 * table, rather than imported from `web/src/network/`, so a test can catch a
 * wrong table there.
 */
import { expect, type Locator, type Page } from '@playwright/test';
import { sceneDocument } from './pages.ts';

export const DEVICES = [
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
] as const;
export const LINKS = ['cable', 'circuit', 'neighbor', 'relationship', 'connector'] as const;

/** Each device's label as placed, which is its name until someone edits it. */
export const DEVICE_NAMES: Readonly<Record<(typeof DEVICES)[number], string>> = {
	router: 'Router',
	switch: 'Switch',
	firewall: 'Firewall',
	wireless_ap: 'Wi-Fi AP',
	server: 'Server',
	workstation: 'Workstation',
	printer: 'Printer',
	voip_phone: 'VoIP phone',
	mobile: 'Mobile',
	host: 'Host',
	cloud: 'Cloud',
	other: 'Other'
};

/** The task's table of line styles. Each kind sets these, and nothing else. */
export const LINE_STYLES = {
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
} as const;

/** The editor's default ink. The library draws in it, and segl sets no other color. */
export const DEFAULT_INK = '#1e1e1e';

export const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

export interface Binding {
	elementId: string;
}

/** An element as the scene document has it, with the fields these tests read. */
export interface Element {
	id: string;
	type: string;
	version: number;
	x: number;
	y: number;
	width: number;
	height: number;
	groupIds: string[];
	strokeColor: string;
	strokeStyle: string;
	strokeWidth: number;
	customData?: { segl?: Record<string, unknown> };
	containerId?: string | null;
	originalText?: string;
	points?: [number, number][];
	startArrowhead?: string | null;
	endArrowhead?: string | null;
	startBinding?: Binding | null;
	endBinding?: Binding | null;
	boundElements?: { id: string; type: string }[] | null;
}

/** The elements on the canvas, without the deleted ones. */
export async function scene(page: Page): Promise<Element[]> {
	return (await sceneDocument(page)).elements as unknown as Element[];
}

/** The `customData.segl` of an element, or undefined. */
export function seglOf(element: Element): Record<string, unknown> | undefined {
	return element.customData?.segl;
}

/** The elements that carry an object's record: each device's card and each link's line. */
export async function objects(page: Page): Promise<Element[]> {
	return (await scene(page)).filter((element) => seglOf(element)?.['objectType'] !== undefined);
}

export function objectIdOf(element: Element): string {
	return seglOf(element)!['objectId'] as string;
}

/** The card or line that carries this object's record. */
export async function holder(page: Page, objectId: string): Promise<Element | undefined> {
	return (await objects(page)).find((element) => objectIdOf(element) === objectId);
}

/** The tags on the canvas that name this object. */
export async function tagsOf(page: Page, objectId: string): Promise<Element[]> {
	return (await scene(page)).filter(
		(element) => seglOf(element)?.['part'] === 'tag' && seglOf(element)?.['objectId'] === objectId
	);
}

/** The label of a card or a line, or undefined. */
export async function labelOf(page: Page, elementId: string): Promise<Element | undefined> {
	return (await scene(page)).find((element) => element.containerId === elementId);
}

/** What the tests compare across a reload, a restore, and an import: records and tags. */
export interface Seen {
	record: Record<string, unknown>;
	/** The text of the device's tags. */
	tags: string[];
	/** The label of the card or line: a device's name, or a link's tag and words. */
	label: string | null;
}

export async function seen(page: Page, objectIds: readonly string[]): Promise<Seen[]> {
	const all = await scene(page);
	return objectIds.map((objectId) => {
		const element = all.find(
			(each) => seglOf(each)?.['objectType'] !== undefined && objectIdOf(each) === objectId
		);
		if (element === undefined) return { record: {}, tags: [], label: null };
		const tags = all.filter(
			(each) => seglOf(each)?.['part'] === 'tag' && seglOf(each)?.['objectId'] === objectId
		);
		const label = all.find((each) => each.containerId === element.id);
		return {
			record: seglOf(element)!,
			tags: tags.map((tag) => tag.originalText ?? ''),
			label: label?.originalText ?? null
		};
	});
}

interface View {
	scrollX: number;
	scrollY: number;
	zoom: number;
}

async function view(page: Page): Promise<View> {
	return JSON.parse(await page.evaluate(() => window.SEGL_CANVAS!.view())) as View;
}

async function canvasBox(page: Page) {
	return (await page.locator('.excalidraw canvas.interactive').boundingBox())!;
}

/** Where a scene point is on the page. */
export async function onPage(page: Page, x: number, y: number): Promise<{ x: number; y: number }> {
	const box = await canvasBox(page);
	const { scrollX, scrollY, zoom } = await view(page);
	return { x: box.x + (x + scrollX) * zoom, y: box.y + (y + scrollY) * zoom };
}

/**
 * Scroll the canvas so the scene point is in the middle of the view. The
 * tests share their slot with others, and draw away from what those draw.
 */
export async function lookAt(page: Page, x: number, y: number): Promise<void> {
	const box = await canvasBox(page);
	await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
	const { scrollX, scrollY, zoom } = await view(page);
	const middle = { x: box.width / 2 / zoom - scrollX, y: box.height / 2 / zoom - scrollY };
	await page.mouse.wheel((x - middle.x) * zoom, (y - middle.y) * zoom);
	await expect
		.poll(async () => {
			const now = await view(page);
			return Math.round(box.width / 2 / now.zoom - now.scrollX - x);
		})
		.toBe(0);
}

/** The library's items, without the editor's offer to add what is selected. */
export function libraryItems(page: Page): Locator {
	return page.locator('.library-unit__dragger:not(.library-unit__pulse)');
}

export async function openLibrary(page: Page): Promise<void> {
	if (!(await libraryItems(page).first().isVisible())) {
		await page.locator('.default-sidebar-trigger').click();
	}
	await expect(libraryItems(page).first()).toBeVisible();
}

export async function closeLibrary(page: Page): Promise<void> {
	const close = page.getByTestId('sidebar-close');
	if (await close.isVisible()) await close.click();
	await expect(libraryItems(page)).toHaveCount(0);
}

/**
 * A point to press on an object: a card's middle, far from the edges where
 * links end, or a quarter along a line, clear of its middle, where the editor
 * offers to bend it.
 */
async function grip(page: Page, element: Element): Promise<{ x: number; y: number }> {
	if (element.type === 'arrow') {
		const [, end] = element.points!;
		return onPage(page, element.x + end![0] / 4, element.y + end![1] / 4);
	}
	return onPage(page, element.x + element.width / 2, element.y + element.height / 2);
}

/** Click on the canvas where nothing is drawn: the editor selects nothing. */
export async function clickEmpty(page: Page, x: number, y: number): Promise<void> {
	const at = await onPage(page, x, y);
	await page.mouse.click(at.x, at.y);
}

/** Press on an object and move it by (dx, dy) on the scene. */
export async function drag(page: Page, element: Element, dx: number, dy: number): Promise<void> {
	const from = await grip(page, element);
	const { zoom } = await view(page);
	await page.mouse.move(from.x, from.y);
	await page.mouse.down();
	await page.mouse.move(from.x + dx * zoom, from.y + dy * zoom, { steps: 8 });
	await page.mouse.up();
}

/**
 * Select an object by a click on it: a device's name, or a line. The editor
 * selects a device's whole group. A click on the empty middle of a device
 * that is already selected would clear the selection: the editor treats a
 * click inside a selected group that hits none of its lines as a click on
 * nothing. A click on the name does not.
 */
export async function select(page: Page, element: Element): Promise<void> {
	await page.keyboard.press('Escape');
	const at =
		element.type === 'arrow'
			? await grip(page, element)
			: await onPage(page, element.x + element.width / 2, element.y + element.height - 15);
	await page.mouse.click(at.x, at.y);
}

/**
 * Place library item `index` (devices 0 to 11, then links 12 to 16) and move
 * it so its top left is at the scene point. Return its card or line.
 */
export async function place(
	page: Page,
	index: number,
	to?: { x: number; y: number }
): Promise<Element> {
	await page.keyboard.press('Escape');
	const before = new Set((await objects(page)).map((element) => element.id));
	await openLibrary(page);
	await libraryItems(page).nth(index).click();
	let placed: Element | undefined;
	await expect
		.poll(async () => {
			placed = (await objects(page)).find((element) => !before.has(element.id));
			return placed !== undefined;
		})
		.toBe(true);
	await closeLibrary(page);
	if (to === undefined) return placed!;
	// It lands in the middle of the view, selected, and moves with its group.
	await drag(page, placed!, to.x - placed!.x, to.y - placed!.y);
	await page.keyboard.press('Escape');
	const moved = (await holder(page, objectIdOf(placed!)))!;
	expect(Math.abs(moved.x - to.x), 'how far from where it was moved').toBeLessThan(2);
	expect(Math.abs(moved.y - to.y), 'how far from where it was moved').toBeLessThan(2);
	return moved;
}

export function panel(page: Page): Locator {
	return page.getByRole('region', { name: 'Network object' });
}

/** Set the selected object's state in segl's panel. */
export async function setState(
	page: Page,
	state: 'Existing' | 'Planned' | 'To remove'
): Promise<void> {
	await panel(page).getByRole('button', { name: state, exact: true }).click();
	await expect(panel(page).getByRole('button', { name: state, exact: true })).toHaveAttribute(
		'aria-pressed',
		'true'
	);
}

/** Drag one end of a selected line onto a card, just inside its left or right edge. */
export async function attach(
	page: Page,
	line: Element,
	end: 'start' | 'end',
	card: Element,
	side: 'left' | 'right'
): Promise<void> {
	await select(page, line);
	const [first, last] = [line.points![0]!, line.points![line.points!.length - 1]!];
	const point = end === 'start' ? first : last;
	const from = await onPage(page, line.x + point[0], line.y + point[1]);
	const target = await onPage(
		page,
		side === 'left' ? card.x + 6 : card.x + card.width - 6,
		card.y + card.height / 2
	);
	await page.mouse.move(from.x, from.y);
	await page.mouse.down();
	await page.mouse.move(target.x, target.y, { steps: 10 });
	await page.mouse.up();
	await page.keyboard.press('Escape');
}
