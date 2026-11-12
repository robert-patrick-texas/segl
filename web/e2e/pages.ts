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
	title: 4,
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

/** What the bar says about the connection: `Connecting…`, `Live`, or `Disconnected`. */
export function connectionStatus(page: Page): Locator {
	return page.locator('header.segl-bar .segl-bar__status');
}

/** Open a slot and wait until this page is in the slot's room. */
export async function joinSlot(page: Page, slot: number): Promise<void> {
	await openSlot(page, `s/${slot}`);
	await expect(connectionStatus(page)).toHaveText('Live');
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
	await expect(connectionStatus(page)).toHaveText('Live');
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
