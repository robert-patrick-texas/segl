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
 * JSON export and import (S-011, docs/TEST-PLAN.md T-009): the editor's own
 * export writes a file, an empty document clears the slot, and the file
 * brings the drawing back for every browser on the slot, with its image.
 *
 * `tests/test_import.py` holds the route, what it refuses, the edit gate, the
 * limits, and an import across a kill of the server.
 */
import { createHash } from 'node:crypto';
import { expect, type APIRequestContext } from '@playwright/test';
import {
	canvasImages,
	chooseImport,
	confirmImport,
	connectionStatus,
	drawRectangle,
	dropFile,
	dropImage,
	elementIds,
	elementOf,
	expectLive,
	expectPainted,
	expectSaved,
	exportScene,
	importControl,
	joinSlot,
	mountOf,
	openHistory,
	png,
	sceneDocument,
	SLOTS,
	socketSwitch,
	test,
	withoutFilePickers,
	type Rgb,
	type SceneElement,
	type TestFile
} from './pages.ts';

/** Each project's image is another color, so another file. */
const COLORS: Record<string, Rgb> = {
	direct: [150, 0, 255],
	root: [0, 120, 90],
	board: [220, 60, 0]
};

/** The colors of the images that only a file holds: never placed on any canvas. */
const UNSEEN: Record<string, Rgb> = {
	direct: [90, 200, 30],
	root: [200, 30, 90],
	board: [30, 90, 200]
};

interface Revision {
	revision: number;
	epoch: number;
	authorLabel: string;
}

interface ExportedDocument {
	type: string;
	version: number;
	source: string;
	elements: SceneElement[];
	files: Record<string, { mimeType: string; dataURL: string }>;
}

async function revisions(request: APIRequestContext, slot: number): Promise<Revision[]> {
	const response = await request.get(`api/v1/slots/${slot}/revisions`);
	expect(response.status()).toBe(200);
	return ((await response.json()) as { revisions: Revision[] }).revisions;
}

async function slotEpoch(request: APIRequestContext, slot: number): Promise<number> {
	return ((await (await request.get(`api/v1/slots/${slot}`)).json()) as { epoch: number }).epoch;
}

/** A scene document with no elements, as the editor exports an empty canvas. */
const EMPTY: TestFile = {
	name: 'empty.excalidraw',
	text: JSON.stringify(
		{ type: 'excalidraw', version: 2, source: 'segl', elements: [], appState: {}, files: {} },
		null,
		2
	)
};

/** A scene file with the canvas's elements under new ids, moved down and to the right. */
async function copyOfScene(
	page: Parameters<typeof sceneDocument>[0],
	name: string
): Promise<{ file: TestFile; ids: string[] }> {
	const scene = await sceneDocument(page);
	const elements = scene.elements
		.filter((element) => element.type === 'rectangle')
		.map((element, index) => ({
			...element,
			id: `copy-${index}-${element.id}`,
			x: element.x + 30,
			y: element.y + 30
		}));
	expect(elements.length).toBeGreaterThan(0);
	return {
		file: { name, text: JSON.stringify({ ...scene, elements, files: {} }) },
		ids: elements.map((element) => element.id)
	};
}

test('a drawing is exported, the slot is cleared, and the file brings it back for everyone', async ({
	page,
	person,
	request,
	baseURL
}, testInfo) => {
	// T-009.
	const slot = SLOTS.importing;
	const color = COLORS[testInfo.project.name]!;
	const { basePath } = mountOf(baseURL);
	const other = await person('Bea');
	await withoutFilePickers(page);
	await joinSlot(page, slot);
	await joinSlot(other, slot);

	// A drawing by two people, with an image in it.
	const mine = await drawRectangle(page, -250, -150);
	const theirs = await drawRectangle(other, 250, -150);
	const image = await dropImage(page, png(160, 100, color), 420, 420);
	await expectSaved(page);
	await expectSaved(other);
	await expect.poll(() => elementIds(page)).toContain(theirs);
	const before = {
		mine: (await elementOf(page, mine))!,
		theirs: (await elementOf(page, theirs))!
	};
	const epoch = await slotEpoch(request, slot);
	const history = await revisions(request, slot);

	// The editor's own export, named after the slot.
	const exported = await exportScene(page, testInfo.outputPath('exported.excalidraw'));
	expect(exported.name).toBe(`Workspace ${slot}.excalidraw`);
	const written = JSON.parse(exported.text) as ExportedDocument;
	expect([written.type, written.version, written.source]).toEqual(['excalidraw', 2, 'segl']);
	expect(written.elements.map((element) => element.id)).toEqual(
		expect.arrayContaining([mine, theirs, image.id])
	);
	// The file carries the image's bytes inside it.
	expect(written.files[image.fileId!]!.mimeType).toBe('image/png');
	expect(written.files[image.fileId!]!.dataURL).toMatch(/^data:image\/png;base64,/);

	// Clear the slot by importing an empty document. The file goes to the
	// import route under the mount, as it is, with who imported in a header.
	const asked = page.waitForRequest((sent) => sent.url().endsWith('/import'));
	await confirmImport(await chooseImport(page, EMPTY));
	const sent = await asked;
	expect(sent.method()).toBe('POST');
	expect(new URL(sent.url()).pathname).toBe(`${basePath}api/v1/slots/${slot}/import`);
	expect(sent.headers()['x-segl-display-name']).toBe('Tester');
	for (const browser of [page, other]) {
		await expect.poll(() => elementIds(browser)).toEqual([]);
		expect(await canvasImages(browser)).toEqual([]);
	}
	expect(await slotEpoch(request, slot)).toBe(epoch + 1);
	await expect(importControl(page).getByRole('group')).toHaveCount(0);

	// The other person imports the file. The drawing returns in both browsers,
	// each element the copy the file held, and the image is painted.
	await confirmImport(await chooseImport(other, exported));
	for (const browser of [page, other]) {
		await expect.poll(() => elementIds(browser)).toEqual(expect.arrayContaining([mine, theirs]));
		expect(await elementOf(browser, mine)).toMatchObject({
			version: before.mine.version,
			x: before.mine.x
		});
		expect(await elementOf(browser, theirs)).toMatchObject({
			version: before.theirs.version,
			x: before.theirs.x
		});
		await expectPainted(browser, image.id, color);
	}
	expect(await slotEpoch(request, slot)).toBe(epoch + 2);

	// A new revision exists: the import's, by whoever imported, and under it
	// the empty scene it replaced.
	const after = await revisions(request, slot);
	expect(after[0]!.revision).toBeGreaterThan(history[0]!.revision);
	expect([after[0]!.epoch, after[0]!.authorLabel]).toEqual([epoch + 2, 'Bea']);
	expect([after[1]!.epoch, after[1]!.authorLabel]).toEqual([epoch + 1, 'Tester']);
	const stored = (await (
		await request.get(`api/v1/slots/${slot}/revisions/${after[0]!.revision}`)
	).json()) as { scene: { elements: SceneElement[] }; files: { id: string }[] };
	expect(stored.scene.elements.map((element) => element.id)).toEqual(
		expect.arrayContaining([mine, theirs, image.id])
	);
	expect(stored.files.map((file) => file.id)).toEqual([image.fileId]);
	// A stored scene holds no file: the bytes are an upload beside it.
	expect(JSON.stringify(stored.scene)).not.toContain('base64');
	const rows = await openHistory(page);
	await expect(rows.first()).toHaveAttribute('data-epoch', String(epoch + 2));
	await expect(rows.first()).toContainText('Bea');
	await expect(rows.first()).toContainText('replacement');

	// A browser that opens the slot now starts from the imported scene.
	const later = await person('Cy');
	await joinSlot(later, slot);
	expect(await elementIds(later)).toEqual(expect.arrayContaining([mine, theirs, image.id]));
	await expectPainted(later, image.id, color);
});

test('an image that only the file holds is stored by the server and painted everywhere', async ({
	page,
	person,
	request
}, testInfo) => {
	const slot = SLOTS.importing;
	const other = await person('Bea');
	await withoutFilePickers(page);
	await joinSlot(page, slot);
	await joinSlot(other, slot);
	// A file with an image in it, as the editor writes one.
	const placed = await dropImage(page, png(160, 100, COLORS[testInfo.project.name]!), 420, 420);
	await expectSaved(page);
	const exported = await exportScene(page, testInfo.outputPath('with-image.excalidraw'));
	const written = JSON.parse(exported.text) as ExportedDocument;
	// The same file with another image in that one's place: bytes no browser
	// holds and the server has never been sent, under a file id of their own.
	const color = UNSEEN[testInfo.project.name]!;
	const bytes = png(160, 100, color);
	const fileId = createHash('sha1').update(bytes).digest('hex');
	const edited = {
		...written,
		elements: written.elements
			.filter((element) => element.id === placed.id)
			.map((element) => ({ ...element, id: `unseen-${fileId}`, fileId })),
		files: {
			[fileId]: {
				mimeType: 'image/png',
				id: fileId,
				dataURL: `data:image/png;base64,${bytes.toString('base64')}`
			}
		}
	};
	expect(edited.elements).toHaveLength(1);
	const hash = createHash('sha256').update(bytes).digest('hex');
	expect((await request.get(`api/v1/assets/${hash}`)).status()).toBe(404);

	await confirmImport(
		await chooseImport(other, { name: 'edited.excalidraw', text: JSON.stringify(edited) })
	);

	// Each browser has to fetch the file: it is painted in the file's color.
	for (const browser of [page, other]) {
		await expect.poll(() => elementIds(browser)).toEqual([`unseen-${fileId}`]);
		await expectPainted(browser, `unseen-${fileId}`, color);
	}
	// The bytes came out of the document, and are an upload like any other.
	const asset = await request.get(`api/v1/assets/${hash}`);
	expect(asset.status()).toBe(200);
	expect(asset.headers()['content-type']).toBe('application/octet-stream');
	expect((await asset.body()).equals(bytes)).toBe(true);
	const head = (await (await request.get(`api/v1/slots/${slot}/scene`)).json()) as {
		files: { id: string; hash: string; mimeType: string }[];
	};
	expect(head.files).toEqual([{ id: fileId, hash, mimeType: 'image/png' }]);
});

test('a scene file dropped on the canvas is offered for import, and the editor does not open it', async ({
	page,
	person,
	request
}) => {
	const slot = SLOTS.importing;
	const other = await person('Bea');
	await joinSlot(page, slot);
	await joinSlot(other, slot);
	const drawn = await drawRectangle(page, -250, 60);
	await expectSaved(page);
	await expect.poll(() => elementIds(other)).toContain(drawn);
	const { file, ids } = await copyOfScene(page, 'network.excalidraw');
	const epoch = await slotEpoch(request, slot);
	const imports: string[] = [];
	page.on('request', (sent) => {
		if (sent.url().endsWith('/import')) imports.push(sent.url());
	});
	const dropped = { name: file.name, type: '', bytes: Buffer.from(file.text) };
	const panel = importControl(page).getByRole('group');

	await dropFile(page, dropped, 500, 300);

	// The bar asks. Nothing was opened in this browser, and nothing was sent.
	await expect(panel).toContainText('network.excalidraw');
	await expect(panel).toContainText('Replace the canvas for everyone?');
	await page.waitForTimeout(500);
	for (const browser of [page, other]) {
		const held = await elementIds(browser);
		expect(held).toContain(drawn);
		expect(held.filter((id) => ids.includes(id))).toEqual([]);
	}
	expect(imports).toEqual([]);

	// Cancel lets go of the file.
	await panel.getByRole('button', { name: 'Cancel' }).click();
	await expect(panel).toHaveCount(0);
	expect(await slotEpoch(request, slot)).toBe(epoch);

	// Dropped again and confirmed, it is an import like any other.
	await dropFile(page, dropped, 500, 300);
	await confirmImport(panel);
	for (const browser of [page, other]) {
		await expect.poll(async () => (await elementIds(browser)).sort()).toEqual([...ids].sort());
	}
	expect(await slotEpoch(request, slot)).toBe(epoch + 1);
	expect(imports).toHaveLength(1);
});

test('a file that is not a scene is refused in words, and nothing changes', async ({
	page,
	request
}) => {
	const slot = SLOTS.importing;
	await joinSlot(page, slot);
	const drawn = await drawRectangle(page, 250, 60);
	await expectSaved(page);
	const epoch = await slotEpoch(request, slot);
	const control = importControl(page);

	const panel = await chooseImport(page, {
		name: 'notes.txt',
		text: 'not a drawing',
		type: 'text/plain'
	});
	await confirmImport(panel);

	await expect(control.getByRole('alert')).toHaveText('That is not an Excalidraw file.');
	// The file is still there to cancel, and the canvas is as it was.
	await expect(panel).toContainText('notes.txt');
	expect(await slotEpoch(request, slot)).toBe(epoch);
	expect(await elementIds(page)).toContain(drawn);

	// Another file is another question, without the words about the last one:
	// one dropped on the canvas while they are still showing.
	const dropped = { name: 'other.excalidraw', type: '', bytes: Buffer.from(EMPTY.text) };
	await dropFile(page, dropped, 500, 300);
	await expect(panel).toContainText('other.excalidraw');
	await expect(panel).toContainText('Replace the canvas for everyone?');
	await expect(control.getByRole('alert')).toHaveCount(0);
	await page.keyboard.press('Escape');
	await expect(panel).toHaveCount(0);
	// What the server answers for a file over `max_scene_bytes`, which is 50 MiB
	// here: the answer is put in the server's place.
	await page.route('**/api/v1/slots/*/import', (route) =>
		route.fulfill({
			status: 413,
			contentType: 'application/json',
			body: JSON.stringify({ error: 'payload_too_large', message: 'The body is larger.' })
		})
	);
	const again = await chooseImport(page, EMPTY);
	await expect(control.getByRole('alert')).toHaveCount(0);
	await confirmImport(again);
	await expect(control.getByRole('alert')).toHaveText('That file is larger than this segl takes.');
	expect(await slotEpoch(request, slot)).toBe(epoch);
	expect(await elementIds(page)).toContain(drawn);
});

test("the editor's own way to open a file is gone, and its export is there", async ({ page }) => {
	// The editor would open a file in this browser's canvas alone.
	await withoutFilePickers(page);
	await joinSlot(page, SLOTS.importing);
	const choosers: string[] = [];
	page.on('filechooser', () => choosers.push('opened'));

	await page.locator('[data-testid="main-menu-trigger"]').click();

	await expect(page.locator('[data-testid="json-export-button"]')).toBeVisible();
	await expect(page.locator('[data-testid="load-button"]')).toHaveCount(0);
	await expect(page.locator('.excalidraw .dropdown-menu')).not.toContainText('Open');
	await page.keyboard.press('Escape');

	// Its shortcut opens nothing either.
	await page.locator('.excalidraw canvas.interactive').click({ position: { x: 600, y: 500 } });
	await page.keyboard.press('Control+o');
	await page.waitForTimeout(500);
	expect(choosers).toEqual([]);

	// The bar's own button does open the file dialog.
	await importControl(page).getByRole('button', { name: 'Import', exact: true }).click();
	await expect.poll(() => choosers).toEqual(['opened']);
});

test('importing waits while the page is not in the room of its slot', async ({ page, request }) => {
	// A page that is not connected would not be sent the imported scene.
	const slot = SLOTS.importing;
	const network = await socketSwitch(page);
	await joinSlot(page, slot);
	const epoch = await slotEpoch(request, slot);
	const choosers: string[] = [];
	page.on('filechooser', () => choosers.push('opened'));
	const control = importControl(page);
	const button = control.getByRole('button', { name: 'Import', exact: true });

	await network.kill();
	await expect(connectionStatus(page)).toHaveAttribute('data-state', 'disconnected');

	// The button says why, and opens no file dialog.
	await button.click();
	await expect(control.getByRole('group')).toHaveText('Importing waits for the connection.');
	await page.waitForTimeout(300);
	expect(choosers).toEqual([]);
	// A file dropped meanwhile is named, with the same words and nothing to press.
	const dropped = { name: 'later.excalidraw', type: '', bytes: Buffer.from(EMPTY.text) };
	await dropFile(page, dropped, 500, 300);
	await expect(control.getByRole('group')).toContainText('later.excalidraw');
	await expect(control.getByRole('group')).toContainText('Importing waits for the connection.');
	await expect(control.getByRole('button', { name: 'Import it' })).toHaveCount(0);

	// Back in the room, the same file can be imported.
	network.restore();
	await expectLive(page);
	await confirmImport(control.getByRole('group'));
	await expect.poll(() => elementIds(page)).toEqual([]);
	expect(await slotEpoch(request, slot)).toBe(epoch + 1);
	expect(choosers).toEqual([]);
});

test('the import question stays inside a narrow page', async ({ page }) => {
	await page.setViewportSize({ width: 390, height: 800 });
	await joinSlot(page, SLOTS.importing);

	const panel = await chooseImport(page, EMPTY);

	const box = (await panel.boundingBox())!;
	const button = (await importControl(page)
		.getByRole('button', { name: 'Import', exact: true })
		.boundingBox())!;
	expect(box.x).toBeGreaterThanOrEqual(0);
	expect(box.x + box.width).toBeLessThanOrEqual(390);
	expect(box.y).toBeGreaterThanOrEqual(button.y + button.height);
	// The page did not gain a sideways scroll.
	expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
});
