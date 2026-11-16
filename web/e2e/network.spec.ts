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
 * Network objects on a canvas (N-001 to N-005, docs/TEST-PLAN.md T-022):
 * segl's library, the panel that sets a state and a link's kind, tags that
 * every browser sees, links bound to devices, a new id for each copy, and
 * records that come back after a reload, a restore, and an export and
 * import. `web/e2e/access.spec.ts` has the viewer.
 *
 * The slot is shared, so each test draws in a region of the canvas of its
 * own, far from the middle, and reads only the objects it placed.
 */
import { expect, type APIRequestContext, type Page, type TestInfo } from '@playwright/test';
import {
	attach,
	clickEmpty,
	DEFAULT_INK,
	DEVICE_NAMES,
	DEVICES,
	drag,
	holder,
	labelOf,
	libraryItems,
	LINE_STYLES,
	LINKS,
	lookAt,
	objectIdOf,
	objects,
	onPage,
	openLibrary,
	panel,
	place,
	scene,
	seen,
	seglOf,
	select,
	setState,
	tagsOf,
	UUID,
	type Element
} from './network.ts';
import {
	chooseImport,
	confirmImport,
	expectEditor,
	expectSaved,
	exportScene,
	joinSlot,
	openHistory,
	restoreRow,
	SLOTS,
	tapSockets,
	test,
	withoutFilePickers
} from './pages.ts';

const SLOT = SLOTS.network;
const PROJECTS = ['direct', 'root', 'board'];

/** A region of the canvas for one test in one project, far from where others draw. */
function region(testInfo: TestInfo, n: number): { x: number; y: number } {
	return { x: 4000 + PROJECTS.indexOf(testInfo.project.name) * 6000, y: 4000 + n * 2000 };
}

/** The device and the link an object id names, as the other browser sees it, once it does. */
async function waitFor(page: Page, objectId: string): Promise<Element> {
	await expect.poll(async () => (await holder(page, objectId)) !== undefined).toBe(true);
	return (await holder(page, objectId))!;
}

test('the library holds 12 devices and 5 links, and each one placed is a new object', async ({
	page
}, testInfo) => {
	await joinSlot(page, SLOT);
	const at = region(testInfo, 0);
	await lookAt(page, at.x, at.y);
	await openLibrary(page);
	await expect(libraryItems(page)).toHaveCount(17);

	const placed: Element[] = [];
	for (let index = 0; index < 17; index += 1) placed.push(await place(page, index));
	await expectSaved(page);
	const all = await scene(page);

	expect(placed.map((element) => seglOf(element)!['objectType'])).toEqual([...DEVICES, ...LINKS]);
	const ids = placed.map(objectIdOf);
	expect(new Set(ids).size, 'each placed object has its own id').toBe(17);
	for (const [index, element] of placed.entries()) {
		const record = seglOf(element)!;
		expect(record, `the record of item ${index}`).toEqual({
			schemaVersion: 1,
			objectId: expect.stringMatching(UUID),
			objectType: index < 12 ? DEVICES[index] : LINKS[index - 12],
			state: 'existing'
		});
		expect(record['objectId']).not.toBe('00000000-0000-0000-0000-000000000000');
		// It is not the element's own id.
		expect(record['objectId']).not.toBe(element.id);
	}

	for (const card of placed.slice(0, 12)) {
		const kind = seglOf(card)!['objectType'] as (typeof DEVICES)[number];
		expect(card.type).toBe('rectangle');
		const group = card.groupIds[0];
		expect(group, `${kind} is a group`).toBeDefined();
		const members = all.filter((element) => element.groupIds.includes(group!));
		// The card, its name, and its glyph: lines only, which no link binds to.
		expect(members.filter((element) => element.type === 'rectangle')).toHaveLength(1);
		expect((await labelOf(page, card.id))?.originalText).toBe(DEVICE_NAMES[kind]);
		const glyph = members.filter((element) => element.type === 'line');
		expect(glyph.length, `${kind} has a glyph`).toBeGreaterThan(0);
		expect(members).toHaveLength(2 + glyph.length);
		expect(await tagsOf(page, objectIdOf(card)), 'an existing device has no tag').toEqual([]);
		for (const member of members) expect(member.strokeColor).toBe(DEFAULT_INK);
	}
	for (const line of placed.slice(12)) {
		const kind = seglOf(line)!['objectType'] as (typeof LINKS)[number];
		expect(line.type).toBe('arrow');
		expect({
			strokeStyle: line.strokeStyle,
			strokeWidth: line.strokeWidth,
			startArrowhead: line.startArrowhead,
			endArrowhead: line.endArrowhead
		}).toEqual(LINE_STYLES[kind]);
		expect(line.strokeColor).toBe(DEFAULT_INK);
		expect(await labelOf(page, line.id), 'an existing link has no label').toBeUndefined();
	}
});

test('a state set in the panel shows as a tag in every browser', async ({
	page,
	person
}, testInfo) => {
	const other = await person('Other');
	await joinSlot(page, SLOT);
	await joinSlot(other, SLOT);
	const at = region(testInfo, 1);
	await lookAt(page, at.x + 200, at.y + 150);
	const router = await place(page, 0, { x: at.x, y: at.y + 100 });
	const cable = await place(page, 12, { x: at.x + 200, y: at.y + 150 });
	const routerId = objectIdOf(router);
	const cableId = objectIdOf(cable);

	// The panel shows for one selected object: its kind, its name, its state.
	await clickEmpty(page, at.x + 200, at.y + 400);
	await expect(panel(page)).toHaveCount(0);
	await select(page, router);
	await expect(panel(page)).toContainText('Router');
	await expect(panel(page).getByRole('button', { name: 'Existing', exact: true })).toHaveAttribute(
		'aria-pressed',
		'true'
	);
	await expect(panel(page).getByLabel('Kind')).toHaveCount(0);

	// A device's tag is a text in its group, in its ink, at its card's top
	// right, and drawn under the card so a link's end finds the card.
	await setState(page, 'Planned');
	await waitFor(other, routerId);
	await expect
		.poll(async () => (await tagsOf(other, routerId)).map((tag) => tag.originalText))
		.toEqual(['P']);
	const [tag] = await tagsOf(page, routerId);
	expect(tag!.groupIds).toEqual(router.groupIds);
	expect(tag!.strokeColor).toBe(router.strokeColor);
	expect(tag!.x).toBeGreaterThan(router.x + router.width / 2);
	expect(tag!.x + tag!.width).toBeLessThanOrEqual(router.x + router.width);
	expect(tag!.y).toBeGreaterThanOrEqual(router.y);
	expect(tag!.y + tag!.height).toBeLessThan(router.y + router.height / 2);
	const order = (await scene(page)).map((element) => element.id);
	expect(order.indexOf(tag!.id)).toBeLessThan(order.indexOf(router.id));
	expect(seglOf((await holder(other, routerId))!)!['state']).toBe('planned');

	await setState(page, 'To remove');
	await expect
		.poll(async () => (await tagsOf(other, routerId)).map((tag) => tag.originalText))
		.toEqual(['R']);
	// The same tag, its letter changed.
	expect((await tagsOf(page, routerId)).map((each) => each.id)).toEqual([tag!.id]);
	await setState(page, 'Existing');
	await expect.poll(async () => (await tagsOf(other, routerId)).length).toBe(0);
	expect(seglOf((await holder(other, routerId))!)!['state']).toBe('existing');

	// A link's tag starts its label, before the team's own words.
	await select(page, cable);
	await expect(panel(page)).toContainText('Cable');
	// Enter on a selected line edits its label, as a double click does.
	await page.keyboard.press('Enter');
	await page.keyboard.type('10G');
	await page.keyboard.press('Escape');
	await expect.poll(async () => (await labelOf(other, cable.id))?.originalText).toBe('10G');
	// A label the panel makes for a line with none sits at the line's middle.
	const bare = await place(page, 13, { x: at.x + 200, y: at.y + 300 });
	await select(page, bare);
	await setState(page, 'Planned');
	const made = (await labelOf(page, bare.id))!;
	expect(made.originalText).toBe('P');
	const [, end] = bare.points!;
	expect(made.x + made.width / 2).toBeCloseTo(bare.x + end![0] / 2, 0);
	expect(made.y + made.height / 2).toBeCloseTo(bare.y + end![1] / 2, 0);
	// The line knows its label here, as the editor's own labels are known.
	const textsOf = async (id: string) =>
		((await holder(page, objectIdOf(bare)))!.boundElements ?? []).filter(
			(each) => each.type === 'text' && each.id === id
		);
	expect(await textsOf(made.id)).toHaveLength(1);
	await setState(page, 'Existing');
	await expect.poll(async () => (await labelOf(page, bare.id)) === undefined).toBe(true);
	expect(await textsOf(made.id), 'the line lets go of a label that is gone').toHaveLength(0);
	await select(page, cable);

	for (const [state, label] of [
		['Planned', 'P 10G'],
		['To remove', 'R 10G'],
		['Existing', '10G']
	] as const) {
		await setState(page, state);
		await expect.poll(async () => (await labelOf(other, cable.id))?.originalText).toBe(label);
		await expect(panel(page)).toContainText('10G');
		// The rewritten label stays in the middle of its line.
		const line = (await holder(page, cableId))!;
		const words = (await labelOf(page, line.id))!;
		const [, lineEnd] = line.points!;
		expect(words.x + words.width / 2).toBeCloseTo(line.x + lineEnd![0] / 2, 0);
	}
	expect(seglOf((await holder(other, cableId))!)!['state']).toBe('existing');
});

test('a link between two devices keeps both ends when one moves', async ({
	page,
	person
}, testInfo) => {
	const other = await person('Other');
	await joinSlot(page, SLOT);
	await joinSlot(other, SLOT);
	const at = region(testInfo, 2);
	await lookAt(page, at.x + 260, at.y + 200);
	const router = await place(page, 0, { x: at.x, y: at.y + 150 });
	const server = await place(page, 4, { x: at.x + 420, y: at.y + 150 });
	const cable = await place(page, 12, { x: at.x + 150, y: at.y + 40 });

	await attach(page, cable, 'start', router, 'right');
	await attach(page, (await holder(page, objectIdOf(cable)))!, 'end', server, 'left');
	const bound = (await holder(page, objectIdOf(cable)))!;
	expect(bound.startBinding?.elementId, 'the start is on the router').toBe(router.id);
	expect(bound.endBinding?.elementId, 'the end is on the server').toBe(server.id);

	// Move the server's group down. The link's end goes with it.
	await page.keyboard.press('Escape');
	await drag(page, server, 0, 160);
	const moved = (await holder(page, objectIdOf(server)))!;
	expect(Math.round(moved.y - server.y)).toBe(160);
	const after = (await holder(page, objectIdOf(cable)))!;
	expect(after.startBinding?.elementId).toBe(router.id);
	expect(after.endBinding?.elementId).toBe(server.id);
	const end = after.points!.at(-1)!;
	const endY = after.y + end[1];
	expect(endY, 'the end went down with the server').toBeGreaterThan(moved.y - 20);
	expect(endY).toBeLessThan(moved.y + moved.height + 20);

	await expect
		.poll(async () => {
			const seen = await holder(other, objectIdOf(cable));
			return [seen?.startBinding?.elementId, seen?.endBinding?.elementId, Math.round(seen?.y ?? 0)];
		})
		.toEqual([router.id, server.id, Math.round(after.y)]);
});

/** The object the page placed or copied since `before`, once it is on the canvas. */
async function newObject(page: Page, before: ReadonlySet<string>): Promise<Element> {
	let found: Element | undefined;
	await expect
		.poll(async () => {
			found = (await objects(page)).find((element) => !before.has(element.id));
			return found !== undefined;
		})
		.toBe(true);
	return found!;
}

async function objectElementIds(page: Page): Promise<Set<string>> {
	return new Set((await objects(page)).map((element) => element.id));
}

test('a copy gets a new id, and a cut and a paste keeps it', async ({ page, person }, testInfo) => {
	await page.context().grantPermissions(['clipboard-read', 'clipboard-write']);
	const other = await person('Other');
	await joinSlot(page, SLOT);
	await joinSlot(other, SLOT);
	const at = region(testInfo, 3);
	await lookAt(page, at.x + 260, at.y + 220);
	const router = await place(page, 0, { x: at.x, y: at.y });
	const source = objectIdOf(router);
	await select(page, router);
	await setState(page, 'Planned');
	const tagText = async (objectId: string) =>
		(await tagsOf(page, objectId)).map((tag) => tag.originalText);

	// The editor's duplicate. The copy's tag takes the copy's new id.
	let before = await objectElementIds(page);
	await select(page, router);
	await page.keyboard.press('Control+d');
	const duplicate = await newObject(page, before);
	expect(objectIdOf(duplicate)).toMatch(UUID);
	expect(objectIdOf(duplicate)).not.toBe(source);
	expect(await tagText(objectIdOf(duplicate))).toEqual(['P']);
	expect(await tagText(source)).toEqual(['P']);
	await drag(page, duplicate, 0, 200);

	// Alt-drag: the editor leaves the copy where the source was.
	before = await objectElementIds(page);
	await page.keyboard.press('Escape');
	await page.keyboard.down('Alt');
	await drag(page, router, 260, 0);
	await page.keyboard.up('Alt');
	const leftBehind = await newObject(page, before);
	expect(objectIdOf(leftBehind)).not.toBe(source);
	expect(objectIdOf(leftBehind)).not.toBe(objectIdOf(duplicate));
	expect(Math.round(leftBehind.x)).toBe(Math.round(router.x));
	expect(Math.round((await holder(page, source))!.x)).toBe(Math.round(router.x + 260));
	expect(await tagText(objectIdOf(leftBehind))).toEqual(['P']);

	// A paste while the source is on the canvas.
	before = await objectElementIds(page);
	await select(page, (await holder(page, source))!);
	await page.keyboard.press('Control+c');
	const pasteAt = await onPage(page, at.x + 470, at.y + 260);
	await page.mouse.move(pasteAt.x, pasteAt.y);
	await page.keyboard.press('Control+v');
	const pasted = await newObject(page, before);
	const pastedId = objectIdOf(pasted);
	expect([source, objectIdOf(duplicate), objectIdOf(leftBehind)]).not.toContain(pastedId);

	// A cut and a paste: the first copy is gone, so the id stays.
	await select(page, pasted);
	await page.keyboard.press('Control+x');
	await expect.poll(async () => (await holder(page, pastedId)) === undefined).toBe(true);
	before = await objectElementIds(page);
	const againAt = await onPage(page, at.x + 470, at.y + 420);
	await page.mouse.move(againAt.x, againAt.y);
	await page.keyboard.press('Control+v');
	const moved = await newObject(page, before);
	expect(moved.id).not.toBe(pasted.id);
	expect(objectIdOf(moved)).toBe(pastedId);
	expect(await tagText(pastedId)).toEqual(['P']);

	// The other browser holds each object under the id this browser gave it.
	const mine = [source, objectIdOf(duplicate), objectIdOf(leftBehind), pastedId].sort();
	await expectSaved(page);
	await expect
		.poll(async () =>
			(await objects(other))
				.map(objectIdOf)
				.filter((id) => mine.includes(id))
				.sort()
		)
		.toEqual(mine);
	for (const objectId of mine) {
		await expect.poll(async () => (await tagsOf(other, objectId)).length).toBe(1);
	}
});

test("a person's color and width stay through a state change and a kind change", async ({
	page
}, testInfo) => {
	await joinSlot(page, SLOT);
	const at = region(testInfo, 4);
	await lookAt(page, at.x + 200, at.y + 150);
	const router = await place(page, 0, { x: at.x, y: at.y + 100 });
	const cable = await place(page, 12, { x: at.x + 220, y: at.y + 150 });
	const blue = page.getByTestId('color-top-pick-#1971c2');

	// The team colors a device by owner or vendor, in the editor's own menu.
	await select(page, router);
	await blue.click();
	await expect
		.poll(async () => (await holder(page, objectIdOf(router)))!.strokeColor)
		.toBe('#1971c2');
	await setState(page, 'Planned');
	const card = (await holder(page, objectIdOf(router)))!;
	expect(card.strokeColor).toBe('#1971c2');
	expect(seglOf(card)!['state']).toBe('planned');
	// The tag is in the object's ink.
	expect((await tagsOf(page, objectIdOf(router)))[0]!.strokeColor).toBe('#1971c2');

	// A link colored for its speed keeps its color through a kind change.
	await select(page, cable);
	await blue.click();
	await panel(page).getByLabel('Kind').selectOption({ label: 'Circuit' });
	await expect
		.poll(async () => seglOf((await holder(page, objectIdOf(cable)))!)!['objectType'])
		.toBe('circuit');
	let line = (await holder(page, objectIdOf(cable)))!;
	expect(line.strokeColor).toBe('#1971c2');
	expect([line.strokeStyle, line.strokeWidth]).toEqual(['solid', 4]);

	// A width set by hand stays, and the kind and the state are data: unchanged.
	await select(page, line);
	await page.getByTestId('strokeWidth-thin').click({ force: true });
	await expect.poll(async () => (await holder(page, objectIdOf(cable)))!.strokeWidth).toBe(1);
	line = (await holder(page, objectIdOf(cable)))!;
	expect(seglOf(line)).toMatchObject({ objectType: 'circuit', state: 'existing' });
	await setState(page, 'To remove');
	line = (await holder(page, objectIdOf(cable)))!;
	expect([line.strokeColor, line.strokeWidth]).toEqual(['#1971c2', 1]);
	await expect(panel(page).getByLabel('Kind')).toHaveValue('circuit');
});

/** A slot's revisions as the server lists them, newest first. */
async function revisions(
	request: APIRequestContext,
	slot: number
): Promise<{ revision: number }[]> {
	const response = await request.get(`api/v1/slots/${slot}/revisions`);
	expect(response.status()).toBe(200);
	return ((await response.json()) as { revisions: { revision: number }[] }).revisions;
}

/**
 * A router that is planned, a server to remove, and a cable with words and
 * a tag in its label: the records and tags the next tests carry through.
 * The last change waits a second, so the server keeps a revision of it.
 */
async function drawStates(page: Page, at: { x: number; y: number }): Promise<string[]> {
	await lookAt(page, at.x + 260, at.y + 200);
	const router = await place(page, 0, { x: at.x, y: at.y + 150 });
	const server = await place(page, 4, { x: at.x + 420, y: at.y + 150 });
	const cable = await place(page, 12, { x: at.x + 150, y: at.y + 40 });
	await attach(page, cable, 'start', router, 'right');
	await select(page, router);
	await setState(page, 'Planned');
	await select(page, server);
	await setState(page, 'To remove');
	await select(page, (await holder(page, objectIdOf(cable)))!);
	await page.keyboard.press('Enter');
	await page.keyboard.type('10G');
	await page.keyboard.press('Escape');
	await expectSaved(page);
	await page.waitForTimeout(1100);
	await select(page, (await holder(page, objectIdOf(cable)))!);
	await setState(page, 'Planned');
	await expectSaved(page);
	return [router, server, cable].map(objectIdOf);
}

test('records and tags are the same after a reload and a restore', async ({
	page,
	person,
	request
}, testInfo) => {
	const other = await person('Other');
	await joinSlot(page, SLOT);
	await joinSlot(other, SLOT);
	const ids = await drawStates(page, region(testInfo, 5));
	const before = await seen(page, ids);
	expect(before.map(({ record, tags, label }) => [record['state'], tags, label])).toEqual([
		['planned', ['P'], 'Router'],
		['remove', ['R'], 'Server'],
		['planned', [], 'P 10G']
	]);
	const cableStart = (await holder(page, ids[2]!))!.startBinding?.elementId;
	expect(cableStart).toBe((await holder(page, ids[0]!))!.id);

	// A reload: the head the server stored.
	await page.reload();
	await expectEditor(page);
	expect(await seen(page, ids)).toEqual(before);
	expect((await holder(page, ids[2]!))!.startBinding?.elementId).toBe(cableStart);
	await expect.poll(() => seen(other, ids)).toEqual(before);

	// The newest revision holds them as they are. Change one, then restore it.
	const [kept] = await revisions(request, SLOT);
	await lookAt(page, (await holder(page, ids[0]!))!.x + 260, (await holder(page, ids[0]!))!.y + 50);
	await page.waitForTimeout(1100);
	await select(page, (await holder(page, ids[0]!))!);
	await setState(page, 'Existing');
	await expectSaved(page);
	await expect.poll(async () => (await tagsOf(other, ids[0]!)).length).toBe(0);
	const [newest] = await revisions(request, SLOT);
	expect(newest!.revision).toBeGreaterThan(kept!.revision);

	const rows = await openHistory(page);
	await restoreRow(rows.and(page.locator(`[data-revision="${kept!.revision}"]`)));
	for (const browser of [page, other]) {
		await expect.poll(() => seen(browser, ids)).toEqual(before);
	}
});

test('records and tags are the same after an export and an import', async ({ page }, testInfo) => {
	await withoutFilePickers(page);
	await joinSlot(page, SLOT);
	const ids = await drawStates(page, region(testInfo, 6));
	const before = await seen(page, ids);

	// The editor's own export carries each record in its element.
	const exported = await exportScene(page, testInfo.outputPath('network.excalidraw'));
	const written = JSON.parse(exported.text) as { elements: Element[] };
	for (const objectId of ids) {
		expect(
			written.elements.filter((element) => seglOf(element)?.['objectId'] === objectId).length,
			`${objectId} is in the file`
		).toBeGreaterThan(0);
	}

	// Imported into another slot, where none of them was drawn.
	await joinSlot(page, SLOTS.importing);
	await confirmImport(await chooseImport(page, exported));
	await expect.poll(() => seen(page, ids)).toEqual(before);
	expect((await holder(page, ids[2]!))!.startBinding?.elementId).toBe(
		(await holder(page, ids[0]!))!.id
	);

	// A device that came with two tags, as when two browsers set a state at
	// once, keeps one when its state is set again.
	const doubled = JSON.parse(exported.text) as { elements: Element[] };
	const first = doubled.elements.find(
		(element) => seglOf(element)?.['part'] === 'tag' && seglOf(element)?.['objectId'] === ids[0]
	)!;
	doubled.elements.push({ ...first, id: `${first.id}-twice`, y: first.y + 30 });
	await confirmImport(
		await chooseImport(page, { name: 'doubled.excalidraw', text: JSON.stringify(doubled) })
	);
	await expect.poll(async () => (await tagsOf(page, ids[0]!)).length).toBe(2);
	const router = (await holder(page, ids[0]!))!;
	await lookAt(page, router.x + 60, router.y + 50);
	await select(page, router);
	await setState(page, 'To remove');
	await expect
		.poll(async () => (await tagsOf(page, ids[0]!)).map((tag) => tag.originalText))
		.toEqual(['R']);
});

test('a browser the server makes a viewer shows no panel', async ({ page }, testInfo) => {
	const tap = await tapSockets(page);
	await joinSlot(page, SLOT);
	const at = region(testInfo, 8);
	await lookAt(page, at.x + 60, at.y + 50);
	const router = await place(page, 0, { x: at.x, y: at.y });
	await select(page, router);
	await expect(panel(page)).toBeVisible();
	// The server drops an edit: this browser is a viewer after all.
	tap.tell({ type: 'error', error: 'view_only', message: 'Editing is locked.' });
	await expect(panel(page)).toHaveCount(0);
});

/** The parts of the editor a person works with, where they are on the page. */
async function editorTools(page: Page): Promise<{ name: string; box: number[] }[]> {
	return page.evaluate(() => {
		const parts = [
			'.App-toolbar',
			'.App-menu__left',
			'.layer-ui__wrapper__top-right',
			'.default-sidebar-trigger',
			'.mobile-misc-tools-container',
			'.dropdown-menu-button',
			'.zoom-actions',
			'.undo-redo-buttons',
			'.help-icon',
			'.App-bottom-bar .Island'
		];
		const found: { name: string; box: number[] }[] = [];
		for (const part of parts) {
			for (const node of document.querySelectorAll(`.excalidraw ${part}`)) {
				const r = node.getBoundingClientRect();
				if (r.width > 0 && r.height > 0)
					found.push({ name: part, box: [r.left, r.top, r.right, r.bottom] });
			}
		}
		return found;
	});
}

test('the panel covers none of the editor tools, at any width', async ({ page }, testInfo) => {
	await joinSlot(page, SLOT);
	const at = region(testInfo, 7);
	await lookAt(page, at.x + 60, at.y + 50);
	const router = await place(page, 0, { x: at.x, y: at.y });
	for (const width of [1280, 800, 390]) {
		await page.setViewportSize({ width, height: 844 });
		await lookAt(page, router.x + 60, router.y + 50);
		await select(page, router);
		await expect(panel(page)).toBeVisible();
		const own = (await panel(page).boundingBox())!;
		const covered = (await editorTools(page)).filter(
			({ box: [left, top, right, bottom] }) =>
				own.x < right! && own.x + own.width > left! && own.y < bottom! && own.y + own.height > top!
		);
		expect(covered, `the editor's tools the panel covers at ${width} px`).toEqual([]);
		expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
			width
		);
		// The panel is inside the canvas, under the segl bar.
		const canvas = (await page.locator('.segl__canvas').boundingBox())!;
		expect(own.y).toBeGreaterThanOrEqual(canvas.y);
		expect(own.x + own.width).toBeLessThanOrEqual(width);
	}

	// On a wide page the panel moves left of the library while it is open.
	await page.setViewportSize({ width: 1280, height: 844 });
	await lookAt(page, router.x + 60, router.y + 50);
	await select(page, router);
	await openLibrary(page);
	const library = (await page.locator('.excalidraw .sidebar').boundingBox())!;
	await expect
		.poll(async () => {
			const own = (await panel(page).boundingBox())!;
			return own.x + own.width <= library.x;
		})
		.toBe(true);
});
