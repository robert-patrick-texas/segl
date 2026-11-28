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
 * Diagram mode in a browser test (T-024): drawio's editor in its frame on
 * slot 9. A test draws by clicking the first shape of drawio's General set,
 * a rectangle, which adds one vertex. It reads the diagram through
 * `window.SEGL_DIAGRAM` and counts the vertices, since the slot is shared and
 * outlasts a test.
 *
 * drawio has no handle of its own, so a test reads its pages and cells from
 * the diagram's XML, and where a cell is on the screen from the view the
 * frame last reported (T18): the area of the diagram it shows.
 */
import { expect, type FrameLocator, type Locator, type Page } from '@playwright/test';
import { expectLive, SLOTS } from './pages.ts';

/** drawio's frame. */
export function drawio(page: Page): FrameLocator {
	return page.frameLocator('iframe.segl-diagram');
}

/** The shapes of drawio's panel. The first is a rectangle. */
export function shapes(page: Page): Locator {
	return drawio(page).locator('.geSidebarContainer .geSidebar a');
}

/**
 * How long drawio may take to start in its frame. It loads 22 MB of script,
 * which took over 5 seconds on a busy CI runner (run 46038213846).
 */
export const DRAWIO_START_MS = 30_000;

/** Open slot 9, or another path to it, and wait until drawio and the room are ready. */
export async function openDiagram(page: Page, path = `s/${SLOTS.diagram}`): Promise<void> {
	await page.goto(path);
	await diagramReady(page);
}

/** Wait until the page's drawio and its room are ready, after a load of the page. */
export async function diagramReady(page: Page): Promise<void> {
	await page.waitForFunction(() => window.SEGL_DIAGRAM !== undefined);
	await expect(shapes(page).first()).toBeVisible({ timeout: DRAWIO_START_MS });
	await expectLive(page);
}

/** The frame's whole diagram, as drawio's XML. */
export async function diagramXml(page: Page): Promise<string> {
	return page.evaluate(() => window.SEGL_DIAGRAM!.xml());
}

/** How many vertices a diagram's XML holds. */
export function vertexCount(xml: string): number {
	return (xml.match(/vertex="1"/g) ?? []).length;
}

export async function vertices(page: Page): Promise<number> {
	return vertexCount(await diagramXml(page));
}

/** Wait until the page's diagram holds this many vertices. */
export async function expectVertices(page: Page, count: number): Promise<void> {
	await expect.poll(() => vertices(page)).toBe(count);
}

/** Draw one rectangle. drawio puts it in the middle of the view and selects it. */
export async function drawShape(page: Page): Promise<void> {
	await shapes(page).first().click();
}

/** What the bar says of the pen. */
export function penStatus(page: Page): Locator {
	return page.locator('header.segl-bar .segl-bar__pen');
}

/** `{ mismatches, reloads }` of this page. */
export async function diagramCounts(page: Page): Promise<{ mismatches: number; reloads: number }> {
	return JSON.parse(await page.evaluate(() => window.SEGL_DIAGRAM!.counts())) as {
		mismatches: number;
		reloads: number;
	};
}

/** Load the whole diagram again, as after a drift (T19). It waits for a press and a label. */
export async function repair(page: Page): Promise<void> {
	await page.evaluate(() => window.SEGL_DIAGRAM!.repair());
}

/**
 * Wait until the page has loaded this many whole diagrams since it joined,
 * and drawio has put the last one in place. The count goes up as a load
 * starts. The frame answers one action at a time, so an export asked for
 * once the load is under way is answered after it.
 */
export async function expectLoads(page: Page, count: number): Promise<void> {
	await expect.poll(async () => (await diagramCounts(page)).reloads).toBe(count);
	await page.waitForTimeout(300);
	await diagramXml(page);
}

/** Slot 9's head, as the scene route answers: drawio's XML. */
export async function headXml(page: Page): Promise<string> {
	const reply = await page.request.get(`api/v1/slots/${SLOTS.diagram}/scene`);
	expect(reply.status()).toBe(200);
	return ((await reply.json()) as { scene: { diagram: string } }).scene.diagram;
}

/** A shape or a link of a diagram, as its XML has it. */
export interface DiagramCell {
	id: string;
	/** drawio's id of the page it is on. */
	page: string;
	vertex: boolean;
	edge: boolean;
	/** Its label: the cell's `value`, or the `label` of the object that holds it. */
	label: string;
	x: number;
	y: number;
	width: number;
	height: number;
}

/** What a diagram's XML holds: its pages' ids in order, and its cells. */
export interface DiagramContent {
	pages: string[];
	cells: DiagramCell[];
}

/**
 * Read a diagram's pages and cells: the page's own diagram, or this XML.
 * Node has no XML reader, so the page's browser reads it.
 */
export async function contentOf(page: Page, xml?: string): Promise<DiagramContent> {
	const text = xml ?? (await diagramXml(page));
	return page.evaluate((source) => {
		const doc = new DOMParser().parseFromString(source, 'text/xml');
		const content: DiagramContent = { pages: [], cells: [] };
		for (const diagram of Array.from(doc.getElementsByTagName('diagram'))) {
			const pageId = diagram.getAttribute('id') ?? '';
			content.pages.push(pageId);
			for (const cell of Array.from(diagram.getElementsByTagName('mxCell'))) {
				// A cell with data of its own is inside an object that holds its id.
				const holder = cell.parentElement;
				const wrapped = holder?.tagName === 'object' || holder?.tagName === 'UserObject';
				const geometry = Array.from(cell.children).find((child) => child.tagName === 'mxGeometry');
				const number = (name: string) => Number(geometry?.getAttribute(name) ?? 0);
				content.cells.push({
					id: (wrapped ? holder!.getAttribute('id') : cell.getAttribute('id')) ?? '',
					page: pageId,
					vertex: cell.getAttribute('vertex') === '1',
					edge: cell.getAttribute('edge') === '1',
					label: (wrapped ? holder!.getAttribute('label') : cell.getAttribute('value')) ?? '',
					x: number('x'),
					y: number('y'),
					width: number('width'),
					height: number('height')
				});
			}
		}
		return content;
	}, text);
}

/** One shape or link of the page's diagram, or of this XML, or undefined when it is not there. */
export async function cellOf(
	page: Page,
	id: string,
	xml?: string
): Promise<DiagramCell | undefined> {
	return (await contentOf(page, xml)).cells.find(
		(cell) => cell.id === id && (cell.vertex || cell.edge)
	);
}

/** Where a shape is, and its size, or undefined when it is not there. */
export function placeOf(
	cell: DiagramCell | undefined
): { x: number; y: number; width: number; height: number } | undefined {
	return cell === undefined
		? undefined
		: { x: cell.x, y: cell.y, width: cell.width, height: cell.height };
}

/**
 * Draw one rectangle, and return its id once the frame holds it. It is left
 * selected, as drawio leaves it. Nobody else may draw meanwhile.
 */
export async function drawCell(page: Page): Promise<string> {
	const before = new Set((await contentOf(page)).cells.map((cell) => cell.id));
	await drawShape(page);
	let added: DiagramCell[] = [];
	await expect
		.poll(
			async () => {
				added = (await contentOf(page)).cells.filter((cell) => cell.vertex && !before.has(cell.id));
				return added.length;
			},
			{ message: 'the one shape this page drew' }
		)
		.toBe(1);
	return added[0]!.id;
}

/** The ids of the diagram's pages, in order. */
export async function pageIds(page: Page): Promise<string[]> {
	return (await contentOf(page)).pages;
}

/** Add pages until the diagram has at least this many. drawio turns to each page it adds. */
export async function atLeastPages(page: Page, count: number): Promise<void> {
	for (let pages = (await pageIds(page)).length; pages < count; pages += 1) {
		await drawio(page).locator('.geControlTab[title="Insert Page"]').click();
		await expect.poll(async () => (await pageIds(page)).length).toBe(pages + 1);
	}
}

/** Turn the frame to the diagram's page at this index, with its tab, and return the page's id. */
export async function turnTo(page: Page, index: number): Promise<string> {
	let ids: string[] = [];
	await expect
		.poll(async () => (ids = await pageIds(page)).length, { message: `page ${index + 1} is here` })
		.toBeGreaterThan(index);
	// The tab's name: its arrow opens the page's menu.
	if ((await area(page)).page !== ids[index]) {
		await drawio(page).locator(`.gePageTab[data-index="${index}"] > :first-child`).click();
	}
	await expect.poll(async () => (await area(page)).page).toBe(ids[index]);
	return ids[index]!;
}

/** The id of the page drawio's tabs mark as shown, read from the frame itself. */
export async function shownPage(page: Page): Promise<string | null> {
	const index = await drawio(page)
		.locator('body')
		.evaluate(() => {
			const name = document.querySelector('.gePageTab > [aria-current="page"]');
			return name?.parentElement?.getAttribute('data-index') ?? null;
		});
	return index === null ? null : ((await pageIds(page))[Number(index)] ?? null);
}

/** What a browser has selected in the frame, as it last reported. */
export interface DiagramSelection {
	page: string | null;
	cells: string[];
}

/** This browser's selection, as the frame last reported it, or null for none. */
export async function selectionOf(page: Page): Promise<DiagramSelection | null> {
	return JSON.parse(
		await page.evaluate(() => window.SEGL_DIAGRAM!.selection())
	) as DiagramSelection | null;
}

/** The outlines a frame draws of one other person's selection, or of one cell of it. */
export function outlines(page: Page, connectionId: string, cell?: string): Locator {
	const ofCell = cell === undefined ? '' : `[data-segl-cell="${cell}"]`;
	return drawio(page).locator(`.segl-selection[data-segl-id="${connectionId}"]${ofCell}`);
}

/**
 * How far an outline's middle is from its cell's, in pixels of the frame's
 * screen, rounded, or Infinity while there is no such outline. The frame must
 * show the cell's page. It never throws, so `expect.poll` can call it.
 */
export async function outlineOff(page: Page, outline: Locator, id: string): Promise<number> {
	try {
		const box = await outline.boundingBox({ timeout: 2_000 });
		if (box === null) return Infinity;
		const middle = await cellMiddle(page, id);
		return Math.round(
			Math.max(
				Math.abs(box.x + box.width / 2 - middle.x),
				Math.abs(box.y + box.height / 2 - middle.y)
			)
		);
	} catch {
		return Infinity;
	}
}

/** The area of the diagram the frame shows, as it last reported, and its page. */
export interface Area {
	x: number;
	y: number;
	width: number;
	height: number;
	page: string | null;
}

export async function area(page: Page): Promise<Area> {
	return JSON.parse(await page.evaluate(() => window.SEGL_DIAGRAM!.view())) as Area;
}

/** What `read` says once it stops changing: the same twice, 300 ms apart. */
export async function settled<T>(page: Page, read: () => Promise<T>): Promise<T> {
	let before = JSON.stringify(await read());
	for (let tries = 0; tries < 20; tries += 1) {
		await page.waitForTimeout(300);
		const now = JSON.stringify(await read());
		if (now === before) return JSON.parse(now) as T;
		before = now;
	}
	throw new Error('the view did not settle');
}

/** Pixels of the frame's screen to one unit of the diagram, once the view has settled. */
export async function scaleOf(page: Page): Promise<number> {
	const width = await drawio(page)
		.locator('.geDiagramContainer')
		.evaluate((el) => el.clientWidth);
	return width / (await settled(page, () => area(page))).width;
}

/** Put the pointer in the middle of the frame's diagram, and return that place. */
export async function overDiagram(page: Page): Promise<{ x: number; y: number }> {
	const box = (await drawio(page).locator('.geDiagramContainer').boundingBox())!;
	const point = { x: box.x + box.width / 2, y: box.y + box.height / 2 };
	await page.mouse.move(point.x, point.y);
	return point;
}

/**
 * Zoom drawio's diagram one step by the wheel, as a person holding Ctrl does.
 * The tests' browser says it is on Windows, where drawio zooms on a plain
 * mouse wheel too, unless the wheel looks like a trackpad's.
 */
export async function zoomDiagram(page: Page, deltaY: number): Promise<void> {
	await overDiagram(page);
	await page.keyboard.down('Control');
	await page.mouse.wheel(0, deltaY);
	await page.keyboard.up('Control');
}

/** Where a frame shows a point of the diagram, on the screen. */
export async function onScreen(page: Page, point: { x: number; y: number }) {
	const container = drawio(page).locator('.geDiagramContainer');
	const box = (await container.boundingBox())!;
	const width = await container.evaluate((el) => el.clientWidth);
	const view = await area(page);
	const scale = width / view.width;
	return { x: box.x + (point.x - view.x) * scale, y: box.y + (point.y - view.y) * scale };
}

/** The point of the diagram at this place on a frame's screen. */
export async function onDiagram(page: Page, place: { x: number; y: number }) {
	const container = drawio(page).locator('.geDiagramContainer');
	const box = (await container.boundingBox())!;
	const width = await container.evaluate((el) => el.clientWidth);
	const view = await area(page);
	const scale = width / view.width;
	return { x: view.x + (place.x - box.x) / scale, y: view.y + (place.y - box.y) / scale };
}

/** Where the middle of a shape is on the screen. The frame must show its page. */
export async function cellMiddle(page: Page, id: string): Promise<{ x: number; y: number }> {
	const cell = await cellOf(page, id);
	expect(cell, `shape ${id} is in the diagram`).toBeDefined();
	return onScreen(page, { x: cell!.x + cell!.width / 2, y: cell!.y + cell!.height / 2 });
}

/** Drag a shape by its middle, this many pixels of the screen, and let go. */
export async function dragCell(page: Page, id: string, dx: number, dy: number): Promise<void> {
	const from = await cellMiddle(page, id);
	await page.mouse.move(from.x, from.y);
	await page.mouse.down();
	await page.mouse.move(from.x + dx, from.y + dy, { steps: 8 });
	await page.mouse.up();
}

/**
 * Click a place of the diagram that holds nothing, so drawio selects
 * nothing: the first of a few places near the frame's edges where the graph
 * has no shape and no handle, and nothing of drawio's or segl's lies on top.
 */
export async function clickNothing(page: Page): Promise<void> {
	const frame = (await page.locator('iframe.segl-diagram').boundingBox())!;
	const place = await drawio(page)
		.locator('.geDiagramContainer')
		.evaluate((container) => {
			const box = container.getBoundingClientRect();
			// mxGraph's panes: the background, the cells, their handles, and the decorations.
			const panes = container.querySelector('svg')?.firstElementChild?.children;
			const spots = [0.06, 0.5, 0.92].flatMap((across) =>
				[0.06, 0.92].map((down) => [across, down] as const)
			);
			for (const [across, down] of spots) {
				// Inside the scroll bars, which belong to the container too.
				const x = box.left + container.clientLeft + container.clientWidth * across;
				const y = box.top + container.clientTop + container.clientHeight * down;
				const hit = document.elementFromPoint(x, y);
				if (hit === null || !container.contains(hit)) continue;
				if (hit.closest('.segl-cursor, .segl-selection') !== null) continue;
				if (panes?.[1]?.contains(hit) || panes?.[2]?.contains(hit)) continue;
				return { x, y };
			}
			return null;
		});
	expect(place, 'a place of the diagram with nothing on it').not.toBeNull();
	await page.mouse.click(frame.x + place!.x, frame.y + place!.y);
}
