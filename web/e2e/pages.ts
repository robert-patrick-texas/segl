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
 * What the specs share: where a project is mounted, a browser that already
 * has a display name, and how to read the canvas.
 */
import { crc32, deflateSync } from 'node:zlib';
import {
	test as base,
	expect,
	type BrowserContext,
	type Locator,
	type Page
} from '@playwright/test';

export interface Mount {
	/** `https://127.0.0.1:18951`. */
	origin: string;
	/** `/board/`, or `/` at a host root. */
	basePath: string;
}

export function mountOf(baseURL: string | undefined): Mount {
	const url = new URL(baseURL ?? '');
	return { origin: url.origin, basePath: url.pathname };
}

/** The `localStorage` key of this mount's display name. */
export function nameKey(baseURL: string | undefined): string {
	return `segl:${mountOf(baseURL).basePath}:displayName`;
}

/** The address of a slot's collaboration socket under this mount. */
export function collabUrl(baseURL: string | undefined, slot: number): string {
	const url = new URL(`collab?slot=${slot}`, baseURL);
	url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
	return url.href;
}

/** The label a test's browser has, unless the test asks for another or for none. */
export const STORED_NAME = 'Tester';

/**
 * Which slot a test may change (docs/DEVELOPMENT.md, "What the browser tests
 * start"). The slots are shared and outlast a test: the three projects run
 * against one server, and a room keeps what was drawn. So a test asserts on
 * what it drew itself, and slot 9 is never drawn on, for the tests about an
 * empty slot.
 */
export const SLOTS = {
	/** The canvas tools, and the mount test's text. */
	tools: 2,
	presence: 3,
	/**
	 * The presence tests draw nothing, so the history tests have this canvas
	 * to themselves. A restore replaces the whole scene of a slot.
	 */
	history: 3,
	/** The title test draws nothing, so the images have the canvas to themselves. */
	title: 4,
	images: 4,
	drawing: 5,
	deleting: 6,
	reconnect: 7,
	names: 8,
	/** Never drawn on. */
	empty: 9
} as const;

async function storeName(context: BrowserContext, key: string, name: string): Promise<void> {
	await context.addInitScript(
		([storageKey, value]) => {
			try {
				// Only when absent, so a rename survives a reload.
				if (localStorage.getItem(storageKey) === null) localStorage.setItem(storageKey, value);
			} catch {
				// A page without storage, such as about:blank.
			}
		},
		[key, name] as const
	);
}

interface Fixtures {
	storedName: string | null;
	/**
	 * Another person: a page in a browser context of its own, with this
	 * display name already stored. "Two browsers" in docs/TEST-PLAN.md is two
	 * of these against the one server.
	 */
	person: (name: string) => Promise<Page>;
}

/**
 * `test`, with a display name already in the browser's `localStorage`.
 *
 * The server gives one address 30 names a minute (docs/SECURITY.md), and
 * every test here comes from 127.0.0.1. So a test's browser starts with a
 * label, as a returning visitor does, and asks the server for nothing. The
 * few tests about a new visitor say `test.use({ storedName: null })`.
 */
export const test = base.extend<Fixtures>({
	storedName: [STORED_NAME, { option: true }],
	context: async ({ context, baseURL, storedName }, use) => {
		if (storedName !== null) await storeName(context, nameKey(baseURL), storedName);
		await use(context);
	},
	person: async ({ browser, baseURL }, use) => {
		const contexts: BrowserContext[] = [];
		await use(async (name) => {
			const context = await browser.newContext();
			contexts.push(context);
			await storeName(context, nameKey(baseURL), name);
			return context.newPage();
		});
		for (const context of contexts) await context.close();
	}
});

/** The button in the segl bar that shows this browser's display name. */
export function nameButton(page: Page): Locator {
	return page.locator('header.segl-bar button.segl-bar__name');
}

/** Open a path under the mount, such as `s/1`, and wait for the editor to paint. */
export async function openSlot(page: Page, path: string): Promise<void> {
	await page.goto(path);
	await expectEditor(page);
}

export async function expectEditor(page: Page): Promise<void> {
	await expect(page.locator('.excalidraw canvas.interactive')).toBeVisible();
	await page.waitForFunction(() => window.SEGL_CANVAS !== undefined);
}

/**
 * What the bar says about the connection: `Connecting…`, `Live`, `Saving…`,
 * `Saved`, or `Disconnected`.
 */
export function connectionStatus(page: Page): Locator {
	return page.locator('header.segl-bar .segl-bar__status');
}

/**
 * Wait until this page is in the slot's room. The bar then says `Live`, or
 * already `Saving…` or `Saved` when the page had something to send.
 */
export async function expectLive(page: Page): Promise<void> {
	await expect(connectionStatus(page)).toHaveAttribute('data-state', /^(live|saving|saved)$/);
}

/** Wait until the server has called everything this page sent saved. */
export async function expectSaved(page: Page): Promise<void> {
	await expect(connectionStatus(page)).toHaveText('Saved');
	await expect(connectionStatus(page)).toHaveAttribute('data-state', 'saved');
}

/** Open a slot and wait until this page is in the slot's room. */
export async function joinSlot(page: Page, slot: number): Promise<void> {
	await openSlot(page, `s/${slot}`);
	await expectLive(page);
}

/**
 * Go to another slot through the bar, without a page load, and wait until
 * this page is in that slot's room. The heading is waited for first: until
 * the page has moved, the bar still says `Live`, about the slot it is leaving.
 */
export async function switchSlot(page: Page, slot: number, title: string): Promise<void> {
	await page.getByRole('link', { name: `Slot ${slot}:` }).click();
	await expect(page.getByRole('heading', { level: 1 })).toHaveText(title);
	await expectEditor(page);
	await expectLive(page);
}

/** The number in the presence control. */
export function presenceCount(page: Page): Locator {
	return page.getByTestId('presence-count');
}

/** Open the list of who is on the slot, and return its entries. */
export async function openPeople(page: Page): Promise<Locator> {
	const control = page.getByTestId('presence');
	if ((await control.getByRole('list').count()) === 0) await control.getByRole('button').click();
	return control.getByRole('listitem');
}

/** The History control in the segl bar. */
export function historyControl(page: Page): Locator {
	return page.getByTestId('history');
}

/**
 * Open the slot's history, wait for the server's list, and return its rows,
 * newest first. Each has the revision's number in `data-revision`.
 */
export async function openHistory(page: Page): Promise<Locator> {
	const control = historyControl(page);
	const panel = control.getByRole('group', { name: 'History of this slot' });
	if ((await panel.count()) === 0) await control.getByRole('button', { name: 'History' }).click();
	await expect(panel).toHaveAttribute('data-state', 'ready');
	return panel.getByRole('listitem');
}

/** Restore one row of the open history: the press, and the press that confirms it. */
export async function restoreRow(row: Locator): Promise<void> {
	await row.getByRole('button', { name: /^Restore the version of / }).click();
	await expect(row).toContainText('Replace the canvas for everyone?');
	await row.getByRole('button', { name: 'Restore it' }).click();
}

export interface SceneElement {
	id: string;
	type: string;
	isDeleted: boolean;
	version: number;
	x: number;
	y: number;
}

export interface SceneDocument {
	type: string;
	version: number;
	source: string;
	/** Without the deleted ones: the editor leaves them out of this document. */
	elements: SceneElement[];
	appState: Record<string, unknown>;
	/** Left out of a document made for storage: files are stored apart (T07). */
	files?: Record<string, unknown>;
}

/** The scene document the mounted editor would store. */
export async function sceneDocument(page: Page): Promise<SceneDocument> {
	// Between two slots there is no canvas for a moment.
	await page.waitForFunction(() => window.SEGL_CANVAS !== undefined);
	const text = await page.evaluate(() => window.SEGL_CANVAS!.document());
	return JSON.parse(text) as SceneDocument;
}

/** The ids of the elements on the canvas. */
export async function elementIds(page: Page): Promise<string[]> {
	return (await sceneDocument(page)).elements.map((element) => element.id);
}

/** One element on the canvas, or undefined when it is not there, or deleted. */
export async function elementOf(page: Page, id: string): Promise<SceneElement | undefined> {
	return (await sceneDocument(page)).elements.find((element) => element.id === id);
}

/**
 * Draw a rectangle with the mouse, `dx` and `dy` from the middle of the
 * canvas, and return its id. It is left selected, as the editor leaves it.
 */
export async function drawRectangle(page: Page, dx = 0, dy = 0): Promise<string> {
	const before = new Set(await elementIds(page));
	await page.locator('[data-testid="toolbar-rectangle"]').click({ force: true });
	const canvas = (await page.locator('.excalidraw canvas.interactive').boundingBox())!;
	const x = canvas.x + canvas.width / 2 + dx;
	const y = canvas.y + canvas.height / 2 + dy;
	await page.mouse.move(x - 40, y - 25);
	await page.mouse.down();
	await page.mouse.move(x + 40, y + 25, { steps: 5 });
	await page.mouse.up();
	// Whatever else arrived meanwhile is someone else's, and is not a rectangle
	// this page drew at this place.
	const drawn = (await sceneDocument(page)).elements.filter(
		(element) => !before.has(element.id) && element.type === 'rectangle'
	);
	const mine = drawn.filter((element) => Math.abs(element.x + 40 - (x - canvas.x)) < 10);
	expect(mine, 'the rectangle this page just drew').toHaveLength(1);
	return mine[0]!.id;
}

export interface CanvasPeer {
	id: string;
	username: string;
	pointer: { x: number; y: number } | null;
}

/** The other connections the editor is drawing cursors for. */
export async function canvasPeers(page: Page): Promise<CanvasPeer[]> {
	await page.waitForFunction(() => window.SEGL_CANVAS !== undefined);
	return JSON.parse(await page.evaluate(() => window.SEGL_CANVAS!.peers())) as CanvasPeer[];
}

/** A color as red, green, blue. */
export type Rgb = readonly [number, number, number];

/** A PNG file of one color: an image whose every pixel a test can know. */
export function png(width: number, height: number, [red, green, blue]: Rgb): Buffer {
	const chunk = (type: string, data: Buffer): Buffer => {
		const body = Buffer.concat([Buffer.from(type, 'latin1'), data]);
		const whole = Buffer.alloc(body.length + 8);
		whole.writeUInt32BE(data.length, 0);
		body.copy(whole, 4);
		whole.writeUInt32BE(crc32(body), body.length + 4);
		return whole;
	};
	const header = Buffer.alloc(13);
	header.writeUInt32BE(width, 0);
	header.writeUInt32BE(height, 4);
	// Eight bits a channel, RGB, no interlace.
	header.set([8, 2, 0, 0, 0], 8);
	// Each row starts with its filter, 0 for none.
	const row = Buffer.alloc(1 + width * 3);
	for (let x = 0; x < width; x += 1) row.set([red, green, blue], 1 + x * 3);
	const rows = Buffer.concat(Array.from({ length: height }, () => row));
	return Buffer.concat([
		Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
		chunk('IHDR', header),
		chunk('IDAT', deflateSync(rows)),
		chunk('IEND', Buffer.alloc(0))
	]);
}

export interface CanvasImage {
	id: string;
	fileId: string | null;
	x: number;
	y: number;
	width: number;
	height: number;
	/** The type of the image's file, or null while the canvas does not hold the file. */
	mimeType: string | null;
}

/** The images on a page's canvas that are not deleted. */
export async function canvasImages(page: Page): Promise<CanvasImage[]> {
	await page.waitForFunction(() => window.SEGL_CANVAS !== undefined);
	return JSON.parse(await page.evaluate(() => window.SEGL_CANVAS!.images())) as CanvasImage[];
}

/**
 * Place an image by dropping a file on the canvas, `x` and `y` from its top
 * left corner, as a person drags one in from a folder. Returns the image once
 * the editor holds it with its file.
 */
export async function dropImage(
	page: Page,
	file: Buffer,
	x: number,
	y: number
): Promise<CanvasImage> {
	const before = new Set((await canvasImages(page)).map((image) => image.id));
	const canvas = page.locator('.excalidraw canvas.interactive');
	const box = (await canvas.boundingBox())!;
	const dataTransfer = await page.evaluateHandle((base64) => {
		const binary = atob(base64);
		const bytes = new Uint8Array(binary.length);
		for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
		const transfer = new DataTransfer();
		transfer.items.add(new File([bytes], 'picture.png', { type: 'image/png' }));
		return transfer;
	}, file.toString('base64'));
	await canvas.dispatchEvent('drop', { dataTransfer, clientX: box.x + x, clientY: box.y + y });
	let placed: CanvasImage | undefined;
	await expect
		.poll(
			async () => {
				placed = (await canvasImages(page)).find((image) => !before.has(image.id));
				return placed?.mimeType ?? null;
			},
			{ message: 'the dropped image is on the canvas with its file' }
		)
		.toBe('image/png');
	return placed!;
}

/** One image on a page's canvas, or undefined when it is not there. */
export async function imageOf(page: Page, id: string): Promise<CanvasImage | undefined> {
	return (await canvasImages(page)).find((image) => image.id === id);
}

/**
 * The color the canvas shows in the middle of an image, as the page painted
 * it. The canvas is not scrolled or zoomed in these tests, so the image is
 * where its element says. An image without its file is painted as a gray
 * placeholder, which is no test's color.
 */
export async function colorOf(page: Page, image: CanvasImage): Promise<number[]> {
	return page.evaluate(
		([x, y]) => {
			const canvas = document.querySelector<HTMLCanvasElement>('.excalidraw canvas.static')!;
			const scale = canvas.width / canvas.getBoundingClientRect().width;
			const pixel = canvas
				.getContext('2d')!
				.getImageData(Math.round(x * scale), Math.round(y * scale), 1, 1);
			return Array.from(pixel.data.slice(0, 3));
		},
		[image.x + image.width / 2, image.y + image.height / 2] as const
	);
}

/** Wait until a page paints an image in its own color. */
export async function expectPainted(page: Page, id: string, color: Rgb): Promise<void> {
	await expect
		.poll(
			async () => {
				const image = await imageOf(page, id);
				return image === undefined ? null : await colorOf(page, image);
			},
			{ message: `image ${id} is painted` }
		)
		.toEqual([...color]);
}
