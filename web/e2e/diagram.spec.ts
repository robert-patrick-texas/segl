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
 * T-024, Diagram mode on slot 9: drawio's editor, co-editing, and the pen.
 * T-027 to T-029 (T19): a whole-diagram load that keeps the page and waits
 * for a press, History and restore, and the others' selections.
 *
 * Every test draws its own rectangles and counts them, or finds them by id,
 * since the three projects share one server and the room keeps what was
 * drawn. A test that needs pages adds them until the diagram has enough, so
 * the diagram gains pages as the tests run. A restart is in
 * `durability.spec.ts`, and a viewer in `access.spec.ts`.
 *
 * `window.SEGL_DIAGRAM.repair()` loads the whole diagram again by the path a
 * drift takes, and its `selection()` is this browser's selection as the frame
 * last reported it.
 */
import { expect, type APIRequestContext, type Page } from '@playwright/test';
import {
	area,
	atLeastPages,
	cellMiddle,
	cellOf,
	clickNothing,
	contentOf,
	diagramCounts,
	diagramXml,
	dragCell,
	drawCell,
	drawio,
	drawShape,
	expectLoads,
	expectVertices,
	headXml,
	openDiagram,
	outlineOff,
	outlines,
	overDiagram,
	penStatus,
	placeOf,
	repair,
	scaleOf,
	selectionOf,
	settled,
	shapes,
	shownPage,
	turnTo,
	vertexCount,
	vertices,
	zoomDiagram,
	type Area
} from './diagram.ts';
import {
	collabUrl,
	expectSaved,
	historyControl,
	mountOf,
	openHistory,
	restoreRow,
	SLOTS,
	tapSockets,
	test,
	watchConnectionId
} from './pages.ts';

async function headVertices(page: Page): Promise<number> {
	const reply = await page.request.get(`api/v1/slots/${SLOTS.diagram}/scene`);
	const body = (await reply.json()) as { scene: { diagram: string } };
	return vertexCount(body.scene.diagram);
}

test('slot 9 is drawio’s editor under the bar, which says Diagram mode', async ({ page }) => {
	await openDiagram(page);

	const bar = page.locator('header.segl-bar');
	await expect(bar.locator('.segl-bar__mode')).toHaveText('Diagram mode');
	await expect(penStatus(page)).toContainText('Pen free');
	// History is here since T19. Import comes to Diagram mode later.
	await expect(historyControl(page).getByRole('button', { name: 'History' })).toBeVisible();
	await expect(bar.getByRole('button', { name: /Import/ })).toHaveCount(0);
	// drawio's own panel has its network and Cisco sets.
	const sets = drawio(page);
	await expect(sets.getByText('Network 2018', { exact: true })).toBeVisible();
	await expect(sets.getByText('Cisco 19 / Routing WAN', { exact: true })).toBeVisible();
	// No Save or Exit: the diagram is saved as it changes.
	await expect(sets.getByRole('button', { name: /^(Save|Exit)$/ })).toHaveCount(0);
});

test('two browsers on slot 9 see each other’s shapes', async ({ page, person }) => {
	await openDiagram(page);
	const other = await person('Bravo2');
	await openDiagram(other);
	const before = await vertices(page);

	await drawShape(page);
	await expectVertices(other, before + 1);
	await drawShape(other);
	await expectVertices(page, before + 2);

	await expectSaved(page);
	await expectSaved(other);
	expect(await diagramXml(page)).toBe(await diagramXml(other));
	expect(await headVertices(page)).toBe(before + 2);
});

test('each draws at the same time, and both shapes remain in both', async ({ page, person }) => {
	await openDiagram(page);
	const other = await person('Bravo2');
	await openDiagram(other);
	const before = await vertices(page);

	await Promise.all([drawShape(page), drawShape(other)]);

	await expectVertices(page, before + 2);
	await expectVertices(other, before + 2);
	await expectSaved(page);
	await expectSaved(other);
	await expect.poll(() => headVertices(page)).toBe(before + 2);
});

test('a reload keeps the diagram', async ({ page }) => {
	await openDiagram(page);
	const before = await vertices(page);
	await drawShape(page);
	await expectSaved(page);

	await page.reload();
	await openDiagram(page, page.url());

	await expectVertices(page, before + 1);
});

test('one browser takes the pen: the other sees its changes and cannot edit, then takes it in turn', async ({
	page,
	person
}) => {
	await openDiagram(page);
	const other = await person('Bravo2');
	await openDiagram(other);
	const before = await vertices(page);

	await page.getByRole('button', { name: 'Take pen' }).click();
	await expect(penStatus(page)).toContainText('You have the pen');
	await expect(penStatus(other)).toContainText('Pen: Tester');

	// The watcher's drawio is read-only: a click on a shape adds nothing.
	await shapes(other).first().click();
	await drawShape(page);
	await expectVertices(other, before + 1);
	await expectVertices(page, before + 1);

	await other.getByRole('button', { name: 'Take pen' }).click();
	await expect(penStatus(page)).toContainText('Pen: Bravo2');
	await shapes(page).first().click();
	await drawShape(other);
	await expectVertices(page, before + 2);
	await expectVertices(other, before + 2);

	await other.getByRole('button', { name: 'Give pen back' }).click();
	await expect(penStatus(page)).toContainText('Pen free');
	await drawShape(page);
	await expectVertices(other, before + 3);
});

test('the holder leaves, and the pen is free', async ({ page, person }) => {
	await openDiagram(page);
	const other = await person('Bravo2');
	await openDiagram(other);
	await other.getByRole('button', { name: 'Take pen' }).click();
	await expect(penStatus(page)).toContainText('Pen: Bravo2');

	await other.close();

	await expect(penStatus(page)).toContainText('Pen free');
	const before = await vertices(page);
	await drawShape(page);
	await expectVertices(page, before + 1);
	await expectSaved(page);
	expect(await diagramCounts(page)).toEqual({ mismatches: 0, reloads: 0 });
});

test('Diagram mode asks for nothing off its origin, sets no cookie, and stays in its mount', async ({
	page,
	baseURL
}) => {
	const { origin, basePath } = mountOf(baseURL);
	const outside: string[] = [];
	const local: string[] = [];
	const cookies: string[] = [];
	const sockets: string[] = [];
	page.on('websocket', (socket) => sockets.push(socket.url()));
	await page.context().route('**/*', async (route) => {
		const url = new URL(route.request().url());
		if (url.protocol === 'data:' || url.protocol === 'blob:') return route.continue();
		if (url.origin !== origin) {
			outside.push(url.href);
			return route.abort('internetdisconnected');
		}
		local.push(url.pathname);
		return route.continue();
	});
	page.on('response', async (response) => {
		if ((await response.headerValue('set-cookie')) !== null) cookies.push(response.url());
	});

	await openDiagram(page);
	const before = await vertices(page);
	await drawShape(page);
	await expectSaved(page);
	await page.waitForLoadState('networkidle');

	expect(outside).toEqual([]);
	expect(cookies).toEqual([]);
	expect(sockets).toEqual([collabUrl(baseURL, SLOTS.diagram)]);
	expect(local.every((path) => path.startsWith(basePath))).toBe(true);
	expect(local).toContain(`${basePath}drawio/js/app.min.js`);
	// drawio keeps its settings beside segl's, under keys of its own.
	const keys = await drawio(page)
		.locator('body')
		.evaluate(() => Object.keys(localStorage));
	expect(keys.filter((key) => !key.startsWith('segl:'))).toEqual(['.drawio-config']);
	// No service worker: drawio's offline mode is off.
	expect(
		await page.evaluate(async () => (await navigator.serviceWorker.getRegistrations()).length)
	).toBe(0);
	await expectVertices(page, before + 1);
});

/**
 * How far apart two views of one frame are, in pixels of its screen: the
 * most that a corner of the area moved.
 */
function viewMoved(before: Area, after: Area, scale: number): number {
	return (
		Math.max(
			Math.abs(after.x - before.x),
			Math.abs(after.y - before.y),
			Math.abs(after.x + after.width - (before.x + before.width)),
			Math.abs(after.y + after.height - (before.y + before.height))
		) * scale
	);
}

test('a browser on page 3 that loads the whole diagram stays on page 3, at the same view, with its selection kept', async ({
	page
}) => {
	// T-027.
	await openDiagram(page);
	await atLeastPages(page, 3);
	const third = await turnTo(page, 2);
	// A view of its own on that page, two steps in, which a plain load would lose.
	const plain = await scaleOf(page);
	await zoomDiagram(page, -400);
	await zoomDiagram(page, -400);
	const cell = await drawCell(page);
	await expectSaved(page);
	const scale = await scaleOf(page);
	expect(Math.abs(scale / plain - 1)).toBeGreaterThan(0.2);
	const before = await settled(page, () => area(page));
	expect(before.page).toBe(third);
	await expect.poll(() => selectionOf(page)).toEqual({ page: third, cells: [cell] });
	const { reloads } = await diagramCounts(page);

	await repair(page);

	await expectLoads(page, reloads + 1);
	await expect.poll(() => shownPage(page)).toBe(third);
	const after = await settled(page, () => area(page));
	expect(after.page).toBe(third);
	expect(viewMoved(before, after, scale)).toBeLessThanOrEqual(2);
	await expect.poll(() => selectionOf(page)).toEqual({ page: third, cells: [cell] });
	expect(await shownPage(page)).toBe(third);
	// The turn back was quiet: a load leaves nothing to undo, so Undo turns no page.
	await drawio(page).locator('.geDiagramContainer').press('Control+z');
	await page.waitForTimeout(500);
	expect(await shownPage(page)).toBe(third);
	expect(await cellOf(page, cell)).toBeDefined();
});

test('an empty page keeps its view across a whole-diagram load', async ({ page }) => {
	// T-027. drawio sets no scale of its own on an empty page.
	await openDiagram(page);
	await drawio(page).locator('.geControlTab[title="Insert Page"]').click();
	await expectSaved(page);
	const empty = (await area(page)).page;
	expect(
		(await contentOf(page)).cells.filter((cell) => cell.page === empty && cell.vertex)
	).toEqual([]);
	const plain = await scaleOf(page);
	await zoomDiagram(page, -400);
	await zoomDiagram(page, -400);
	const scale = await scaleOf(page);
	expect(Math.abs(scale / plain - 1)).toBeGreaterThan(0.2);
	const before = await settled(page, () => area(page));
	const { reloads } = await diagramCounts(page);

	await repair(page);

	await expectLoads(page, reloads + 1);
	const after = await settled(page, () => area(page));
	expect(after.page).toBe(empty);
	expect(viewMoved(before, after, scale)).toBeLessThanOrEqual(2);
});

test('a shape drawn just as a load comes still takes its label', async ({ page }) => {
	// T-027. drawio selects a shape from its panel again some 200 ms after
	// the click, by the cell it had: a load in between left a cell the
	// diagram no longer holds selected, and F2 opened no label editor.
	await openDiagram(page);
	const before = new Set((await contentOf(page)).cells.map((cell) => cell.id));
	const { reloads } = await diagramCounts(page);
	await drawShape(page);
	await repair(page);
	await expectLoads(page, reloads + 1);
	let added: string[] = [];
	await expect
		.poll(async () => {
			added = (await contentOf(page)).cells
				.filter((cell) => cell.vertex && !before.has(cell.id))
				.map((cell) => cell.id);
			return added.length;
		})
		.toBe(1);
	const cell = added[0]!;
	await expect.poll(async () => (await selectionOf(page))?.cells).toEqual([cell]);

	await drawio(page).locator('.geDiagramContainer').press('F2');
	await page.keyboard.type('Core');
	await clickNothing(page);

	await expect.poll(async () => (await cellOf(page, cell))?.label).toBe('Core');
	await expectSaved(page);
	// No label editor is still taken for open: the next load comes.
	await repair(page);
	await expectLoads(page, reloads + 2);
	expect((await cellOf(page, cell))?.label).toBe('Core');
});

test('a press that ends in a cancel, a lost focus, or a move with no button lets a load come', async ({
	page
}) => {
	// T-027. drawio's frame sees no release for these, so it ends the press
	// itself. A real cancel and a real loss of focus cannot be made with a
	// mouse here, so the frame is sent the events a browser sends.
	await openDiagram(page);
	const frame = drawio(page).locator('body');
	const endings = ['pointercancel', 'blur', 'pointermove'] as const;
	for (const [index, ending] of endings.entries()) {
		const pointerId = 70 + index;
		const { reloads } = await diagramCounts(page);
		await frame.evaluate((_body, id) => {
			window.dispatchEvent(new PointerEvent('pointerdown', { pointerId: id, buttons: 1 }));
		}, pointerId);
		await repair(page);
		// The press holds the load.
		await page.waitForTimeout(600);
		expect((await diagramCounts(page)).reloads, `held before the ${ending}`).toBe(reloads);

		await frame.evaluate(
			(_body, [id, kind]) => {
				const event =
					kind === 'blur'
						? new FocusEvent('blur')
						: new PointerEvent(kind, { pointerId: id, buttons: 0 });
				window.dispatchEvent(event);
			},
			[pointerId, ending] as const
		);

		await expectLoads(page, reloads + 1);
	}
});

test('a load that comes during a drag waits for the release, and every browser keeps the move', async ({
	page,
	person
}) => {
	// T-027.
	const tap = await tapSockets(page);
	const other = await person('Bea');
	await openDiagram(page);
	await openDiagram(other);
	const cell = await drawCell(page);
	await expectSaved(page);
	await expect.poll(async () => (await cellOf(other, cell)) !== undefined).toBe(true);
	const start = (await cellOf(page, cell))!;
	const scale = await scaleOf(page);
	const from = await cellMiddle(page, cell);
	const { reloads } = await diagramCounts(page);
	const asks = () => tap.sent.filter((message) => message.type === 'reload').length;
	const asked = asks();

	// Press on the shape and move part of the way, then a load is wanted.
	await page.mouse.move(from.x, from.y);
	await page.mouse.down();
	await page.mouse.move(from.x + 40, from.y + 20, { steps: 5 });
	await repair(page);
	// While the button is down, the page asks for nothing and loads nothing.
	await page.waitForTimeout(1_000);
	expect(asks()).toBe(asked);
	expect((await diagramCounts(page)).reloads).toBe(reloads);

	// The rest of the way, and the release: the load comes now.
	await page.mouse.move(from.x + 100, from.y + 60, { steps: 5 });
	await page.mouse.up();
	await expectLoads(page, reloads + 1);
	expect(asks()).toBe(asked + 1);
	await expectSaved(page);

	// The whole move, less drawio's snap to its grid of 10.
	const moved = placeOf(await cellOf(page, cell))!;
	expect(Math.abs(moved.x - start.x - 100 / scale)).toBeLessThanOrEqual(10);
	expect(Math.abs(moved.y - start.y - 60 / scale)).toBeLessThanOrEqual(10);
	await expect.poll(async () => placeOf(await cellOf(other, cell))).toEqual(moved);
	await expect
		.poll(async () => placeOf(await cellOf(page, cell, await headXml(page))))
		.toEqual(moved);
});

interface DiagramRevision {
	revision: number;
	epoch: number;
}

async function diagramRevisions(request: APIRequestContext): Promise<DiagramRevision[]> {
	const reply = await request.get(`api/v1/slots/${SLOTS.diagram}/revisions`);
	expect(reply.status()).toBe(200);
	return ((await reply.json()) as { revisions: DiagramRevision[] }).revisions;
}

async function revisionXml(request: APIRequestContext, revision: number): Promise<string> {
	const reply = await request.get(`api/v1/slots/${SLOTS.diagram}/revisions/${revision}`);
	expect(reply.status()).toBe(200);
	return ((await reply.json()) as { scene: { diagram: string } }).scene.diagram;
}

async function diagramEpoch(request: APIRequestContext): Promise<number> {
	const reply = await request.get(`api/v1/slots/${SLOTS.diagram}`);
	return ((await reply.json()) as { epoch: number }).epoch;
}

/**
 * Draw a rectangle that gets a history row of its own, and return its id and
 * that row. The server keeps at most one row a second while people draw, so
 * the drawing waits until the newest row is older than that.
 */
async function drawRevision(
	page: Page,
	request: APIRequestContext
): Promise<{ id: string; revision: number }> {
	await page.waitForTimeout(1_100);
	const id = await drawCell(page);
	await expectSaved(page);
	let revision = 0;
	await expect
		.poll(
			async () => {
				revision = (await diagramRevisions(request))[0]?.revision ?? 0;
				return revision > 0 && (await cellOf(page, id, await revisionXml(request, revision)));
			},
			{ message: `the newest revision holds shape ${id}` }
		)
		.toBeTruthy();
	return { id, revision };
}

test('a restore from History on slot 9 reaches both browsers, each on its own page', async ({
	page,
	person,
	request
}) => {
	// T-028.
	const mine = watchConnectionId(page);
	const other = await person('Bea');
	await openDiagram(page);
	await openDiagram(other);
	await atLeastPages(page, 3);
	const second = await turnTo(page, 1);
	const third = await turnTo(other, 2);
	// The head has the pages, whether this test added them or found them.
	await expect
		.poll(async () => (await contentOf(page, await headXml(page))).pages)
		.toEqual(expect.arrayContaining([second, third]));
	const epoch = await diagramEpoch(request);

	// Two revisions: the first shape, then both.
	const first = await drawRevision(page, request);
	const later = await drawRevision(page, request);
	const older = await contentOf(page, await revisionXml(request, first.revision));
	expect(older.pages).toEqual(expect.arrayContaining([second, third]));
	expect(older.cells.map((cell) => cell.id)).not.toContain(later.id);
	await expect.poll(async () => (await cellOf(other, later.id)) !== undefined).toBe(true);

	const rows = await openHistory(page);
	const restored = page.waitForRequest((asked) => asked.url().endsWith('/restore'));
	await restoreRow(rows.and(page.locator(`[data-revision="${first.revision}"]`)));
	// The restore names its connection, so the server can tell the pen holder's.
	expect((await restored).postDataJSON()).toEqual({
		revision: first.revision,
		displayName: 'Tester',
		connectionId: await mine()
	});

	// Both browsers load the restored diagram, and each stays on its page.
	for (const [browser, shown] of [
		[page, second],
		[other, third]
	] as const) {
		await expect.poll(async () => (await cellOf(browser, later.id)) === undefined).toBe(true);
		expect(await cellOf(browser, first.id)).toBeDefined();
		expect((await settled(browser, () => area(browser))).page).toBe(shown);
		expect(await shownPage(browser)).toBe(shown);
	}
	expect(await diagramEpoch(request)).toBe(epoch + 1);
	// The open list read itself again: the restore is its newest row, and the
	// row under it is the diagram it replaced.
	await expect(rows.first()).toHaveAttribute('data-epoch', String(epoch + 1));
	await expect(rows.first()).toContainText('Tester');
	await expect(rows.first()).toContainText('replacement');
	await expect(rows.nth(1).locator('[data-kept="restore"]')).toBeVisible();

	// Drawing goes on, and is saved, in the diagram that came back.
	await page.keyboard.press('Escape');
	const next = await drawCell(page);
	await expectSaved(page);
	await expect.poll(async () => (await cellOf(other, next)) !== undefined).toBe(true);
	const head = (await contentOf(page, await headXml(page))).cells.map((cell) => cell.id);
	expect(head).toEqual(expect.arrayContaining([first.id, next]));
	expect(head).not.toContain(later.id);
});

test('while another holds the pen, History on slot 9 shows no Restore', async ({
	page,
	person,
	request
}) => {
	// T-028.
	const mine = watchConnectionId(page);
	const holder = await person('Bea');
	await openDiagram(page);
	await openDiagram(holder);
	// A row of this test's own to list.
	const drawn = await drawRevision(page, request);
	await holder.getByRole('button', { name: 'Take pen' }).click();
	await expect(penStatus(page)).toContainText('Pen: Bea');
	const epoch = await diagramEpoch(request);
	const restore = /^Restore the version of /;

	const rows = await openHistory(page);
	await expect(rows.and(page.locator(`[data-revision="${drawn.revision}"]`))).toBeVisible();
	await expect(historyControl(page).getByRole('button', { name: restore })).toHaveCount(0);
	await expect(historyControl(page)).toContainText('Restoring needs the pen.');
	// The server refuses one from this browser too, and nothing is restored.
	const refused = await request.post(`api/v1/slots/${SLOTS.diagram}/restore`, {
		data: { revision: drawn.revision, displayName: 'Tester', connectionId: await mine() }
	});
	expect(refused.status()).toBe(409);
	expect(await refused.json()).toMatchObject({ error: 'pen_held' });
	expect(await diagramEpoch(request)).toBe(epoch);
	// The holder may restore.
	const theirs = await openHistory(holder);
	await expect(theirs.first().getByRole('button', { name: restore })).toBeVisible();

	// The pen comes back, and with it Restore.
	await holder.getByRole('button', { name: 'Give pen back' }).click();
	await expect(penStatus(page)).toContainText('Pen free');
	await expect(rows.first().getByRole('button', { name: restore })).toBeVisible();
});

test('each browser sees the other’s selection outlined, on its page and not on another', async ({
	page,
	person
}) => {
	// T-029.
	const mine = watchConnectionId(page);
	await openDiagram(page);
	await atLeastPages(page, 2);
	const first = await turnTo(page, 0);
	const cell = await drawCell(page);
	await expectSaved(page);
	await expect.poll(() => selectionOf(page)).toEqual({ page: first, cells: [cell] });
	const me = await mine();

	// A browser that comes later sees the selection already made.
	const other = await person('Bea');
	const theirs = watchConnectionId(other);
	await openDiagram(other);
	expect((await area(other)).page).toBe(first);
	const outline = outlines(other, me, cell);
	await expect(outline).toBeVisible();
	await expect.poll(() => outlineOff(other, outline, cell)).toBeLessThanOrEqual(2);

	// And the first sees the second's. Neither outlines its own.
	const their = await drawCell(other);
	const them = await theirs();
	const theirOutline = outlines(page, them, their);
	await expect(theirOutline).toBeVisible();
	await expect.poll(() => outlineOff(page, theirOutline, their)).toBeLessThanOrEqual(2);
	await expect(outlines(page, me)).toHaveCount(0);
	await expect(outlines(other, them)).toHaveCount(0);
	// In the other person's cursor color.
	await overDiagram(other);
	const cursor = drawio(page).locator('.segl-cursor');
	await expect(cursor).toBeVisible();
	const color = await cursor
		.locator('svg path')
		.last()
		.evaluate((arrow) => getComputedStyle(arrow).fill);
	const strokes = await theirOutline.evaluate((node) =>
		[node, ...Array.from(node.querySelectorAll('*'))].map((el) => getComputedStyle(el).stroke)
	);
	expect(strokes).toContain(color);

	// On another page the first's selection is not outlined. Back on its page, it is.
	await turnTo(other, 1);
	await expect(outlines(other, me)).toHaveCount(0);
	await turnTo(other, 0);
	await expect(outline).toBeVisible();
	await expect.poll(() => outlineOff(other, outline, cell)).toBeLessThanOrEqual(2);

	// A load in the other browser replaces the cells, and the outline is drawn again.
	await outline.evaluate((node) => node.setAttribute('data-test', 'before the load'));
	const { reloads } = await diagramCounts(other);
	await repair(other);
	await expectLoads(other, reloads + 1);
	const redrawn = drawio(other).locator(
		`.segl-selection[data-segl-id="${me}"][data-segl-cell="${cell}"]:not([data-test])`
	);
	await expect(redrawn).toBeVisible();
	await expect.poll(() => outlineOff(other, redrawn, cell)).toBeLessThanOrEqual(2);
});

test('the outline follows a moved shape, and goes when the other selects nothing', async ({
	page,
	person
}) => {
	// T-029.
	const mine = watchConnectionId(page);
	const other = await person('Bea');
	await openDiagram(page);
	await openDiagram(other);
	const cell = await drawCell(page);
	await expectSaved(page);
	const outline = outlines(other, await mine(), cell);
	await expect(outline).toBeVisible();
	const start = (await cellOf(other, cell))!;
	const before = (await outline.boundingBox())!;

	await dragCell(page, cell, 100, 60);

	// The shape moves in the other browser, and its outline with it.
	await expect.poll(async () => (await cellOf(other, cell))?.x).not.toBe(start.x);
	await expect.poll(() => outlineOff(other, outline, cell)).toBeLessThanOrEqual(2);
	const after = (await outline.boundingBox())!;
	expect(after.x - before.x).toBeGreaterThan(50);
	expect(after.y - before.y).toBeGreaterThan(30);

	await clickNothing(page);

	await expect.poll(() => selectionOf(page)).toBeNull();
	await expect(outlines(other, await mine())).toHaveCount(0);
});
