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
 * Live collaboration (S-002, S-010, S-013): two browsers on one slot, as two
 * browser contexts against the one server (docs/TEST-PLAN.md T-001 to T-004,
 * T-014's broadcast, T-015, T-016, and the WebSocket half of T-013).
 *
 * Every test runs in each project, so "two contexts sync over
 * `/board/collab` through nginx" is these tests in the `board` project.
 */
import { expect, type Page } from '@playwright/test';
import {
	canvasPeers,
	collabUrl,
	connectionStatus,
	drawRectangle,
	elementIds,
	elementOf,
	expectLive,
	expectSaved,
	joinSlot,
	nameButton,
	openPeople,
	openSlot,
	presenceCount,
	sceneDocument,
	SLOTS,
	socketSwitch,
	switchSlot,
	tapSockets,
	test,
	type SocketMessage
} from './pages.ts';

/** Wait until an element this test knows by id is on a page's canvas. */
async function expectElement(page: Page, id: string): Promise<void> {
	await expect.poll(() => elementIds(page), { message: `element ${id} arrives` }).toContain(id);
}

async function expectNoElement(page: Page, id: string): Promise<void> {
	await expect.poll(() => elementIds(page), { message: `element ${id} goes` }).not.toContain(id);
}

/** Each element on a page's canvas, as its id and version, in id order. */
async function stamps(page: Page): Promise<string[]> {
	return (await sceneDocument(page)).elements
		.map((element) => `${element.id} v${element.version}`)
		.sort();
}

/** The ids of the elements a socket message carries. */
function idsOf(message: SocketMessage | undefined): string[] {
	const elements = (message?.['elements'] ?? []) as { id: string }[];
	return elements.map((element) => element.id);
}

/** Put the keyboard on the canvas without drawing: a click with the selection tool. */
async function selectEverything(page: Page): Promise<void> {
	await page.locator('[data-testid="toolbar-selection"]').click({ force: true });
	const canvas = (await page.locator('.excalidraw canvas.interactive').boundingBox())!;
	await page.mouse.click(canvas.x + canvas.width - 40, canvas.y + canvas.height - 120);
	await page.keyboard.press('Control+a');
}

test('a rectangle drawn in one browser appears in the other', async ({ page, person, baseURL }) => {
	// T-001, and through nginx the WebSocket half of T-013.
	const sockets: string[] = [];
	page.on('websocket', (socket) => sockets.push(socket.url()));
	const other = await person('Bea');
	await joinSlot(page, SLOTS.drawing);
	await joinSlot(other, SLOTS.drawing);
	expect(sockets).toEqual([collabUrl(baseURL, SLOTS.drawing)]);

	const first = await drawRectangle(page, -200, -100);
	await expectElement(other, first);
	expect(await elementOf(other, first)).toMatchObject({
		type: 'rectangle',
		x: (await elementOf(page, first))!.x,
		y: (await elementOf(page, first))!.y
	});

	// And the other way.
	const second = await drawRectangle(other, 200, -100);
	await expectElement(page, second);
});

test("each browser shows the other's cursor, with its name", async ({ page, person }) => {
	// S-002: element edits and cursors.
	const other = await person('Bea');
	await joinSlot(page, SLOTS.drawing);
	await joinSlot(other, SLOTS.drawing);
	await expect
		.poll(async () => (await canvasPeers(page)).map((peer) => peer.username))
		.toEqual(['Bea']);
	await expect
		.poll(async () => (await canvasPeers(other)).map((peer) => peer.username))
		.toEqual(['Tester']);

	const canvas = (await other.locator('.excalidraw canvas.interactive').boundingBox())!;
	await other.mouse.move(canvas.x + 300, canvas.y + 300);
	await expect.poll(async () => (await canvasPeers(page))[0]!.pointer).not.toBeNull();
	const from = (await canvasPeers(page))[0]!.pointer!;
	await other.mouse.move(canvas.x + 420, canvas.y + 350, { steps: 4 });

	// The same move on the other browser's canvas: 120 across, 50 down.
	await expect
		.poll(async () => {
			const to = (await canvasPeers(page))[0]!.pointer!;
			return [Math.round(to.x - from.x), Math.round(to.y - from.y)];
		})
		.toEqual([120, 50]);
	// The editor's own row of avatars is hidden: the bar has the list.
	await expect(page.locator('.excalidraw .UserList')).toBeHidden();
});

test('both browsers draw at the same time, and both elements remain', async ({ page, person }) => {
	// T-002.
	const other = await person('Bea');
	await joinSlot(page, SLOTS.drawing);
	await joinSlot(other, SLOTS.drawing);

	const [mine, theirs] = await Promise.all([
		drawRectangle(page, -250, 100),
		drawRectangle(other, 250, 100)
	]);

	expect(mine).not.toBe(theirs);
	for (const browser of [page, other]) {
		await expectElement(browser, mine);
		await expectElement(browser, theirs);
	}
	// Each is whole in the other browser, not a half-drawn copy.
	await expect
		.poll(async () => (await elementOf(other, mine))?.version)
		.toBe((await elementOf(page, mine))!.version);
	await expect
		.poll(async () => (await elementOf(page, theirs))?.version)
		.toBe((await elementOf(other, theirs))!.version);
});

test('an element one browser moved and the other deleted stays gone', async ({ page, person }) => {
	// T-003.
	const other = await person('Bea');
	await joinSlot(page, SLOTS.deleting);
	await joinSlot(other, SLOTS.deleting);
	const moved = await drawRectangle(page);
	await expectElement(other, moved);
	const drawnAt = (await elementOf(page, moved))!.x;

	// One browser moves it: it is still selected, and the arrow keys move it.
	for (let step = 0; step < 5; step += 1) await page.keyboard.press('Shift+ArrowRight');
	const movedTo = (await elementOf(page, moved))!.x;
	expect(movedTo).toBeGreaterThan(drawnAt);
	await expect.poll(async () => (await elementOf(other, moved))?.x).toBe(movedTo);

	// The other deletes what was just moved.
	await selectEverything(other);
	await other.keyboard.press('Delete');
	await expectNoElement(other, moved);
	await expectNoElement(page, moved);

	// Something drawn afterwards reaches a reloaded page only from the room,
	// so once it is there, the room's whole scene is.
	const kept = await drawRectangle(page, 0, 150);
	for (const browser of [page, other]) {
		await browser.reload();
		await expectLive(browser);
		await expectElement(browser, kept);
		expect(await elementIds(browser)).not.toContain(moved);
	}
});

test('a killed socket shows disconnected, and edits made meanwhile reconcile', async ({
	page,
	person
}) => {
	// T-004.
	const network = await socketSwitch(page);
	const other = await person('Bea');
	await joinSlot(page, SLOTS.reconnect);
	await joinSlot(other, SLOTS.reconnect);
	const shared = await drawRectangle(page, 0, -150);
	await expectElement(other, shared);
	await expect(presenceCount(other)).toHaveText('2');

	await network.kill();
	await expect(connectionStatus(page)).toHaveText('Disconnected');
	await expect(connectionStatus(page)).toHaveAttribute('data-state', 'disconnected');
	await expect(page.getByTestId('presence').getByRole('button')).toHaveCount(0);
	await expect(presenceCount(other)).toHaveText('1');

	// While it is down: this browser draws, and the other draws and moves the
	// rectangle they share.
	const offline = await drawRectangle(page, -250, 100);
	const meanwhile = await drawRectangle(other, 250, 100);
	await selectEverything(other);
	for (let step = 0; step < 3; step += 1) await other.keyboard.press('Shift+ArrowDown');
	const theirs = (await elementOf(other, shared))!;
	expect(theirs.y).toBeGreaterThan((await elementOf(page, shared))!.y);
	// The canvas stayed usable, and nothing crossed.
	expect(await elementIds(other)).not.toContain(offline);
	expect(await elementIds(page)).not.toContain(meanwhile);

	network.restore();
	// `Live`, and then `Saving…` and `Saved`: it has the offline edits to send.
	await expectLive(page);
	await expect(presenceCount(other)).toHaveText('2');

	// What was drawn while down arrives on each side.
	await expectElement(other, offline);
	await expectElement(page, meanwhile);
	// The server's newer edit is not discarded: this browser's older copy of
	// the shared rectangle did not overwrite the move.
	await expect.poll(async () => (await elementOf(page, shared))?.y).toBe(theirs.y);
	expect((await elementOf(other, shared))!.y).toBe(theirs.y);
	expect((await elementOf(other, shared))!.version).toBe(theirs.version);
});

test('the count is the connections on this slot, and the list names them', async ({
	page,
	person
}) => {
	// T-015.
	const elsewhere = await person('Cy');
	await joinSlot(elsewhere, 1);
	await joinSlot(page, SLOTS.presence);
	await expect(presenceCount(page)).toHaveText('1');

	const other = await person('Bea');
	await joinSlot(other, SLOTS.presence);

	await expect(presenceCount(page)).toHaveText('2');
	await expect(presenceCount(other)).toHaveText('2');
	await expect(page.getByTestId('presence').getByRole('button')).toHaveAccessibleName(
		'2 connections on this slot. Show who'
	);
	await expect(await openPeople(page)).toHaveText(['Testeryou', 'Bea']);
	await expect(await openPeople(other)).toHaveText(['Tester', 'Beayou']);
	// Slot 1's count does not include them.
	await expect(presenceCount(elsewhere)).toHaveText('1');
	await expect(await openPeople(elsewhere)).toHaveText(['Cyyou']);

	// Closing one drops the count to 1, and the open list follows.
	await other.context().close();
	await expect(presenceCount(page)).toHaveText('1');
	await expect(await openPeople(page)).toHaveText(['Testeryou']);
	await page.keyboard.press('Escape');
	await expect(page.getByTestId('presence').getByRole('list')).toHaveCount(0);
});

test('two tabs of one browser are two connections with one label', async ({ page, context }) => {
	const tab = await context.newPage();
	await joinSlot(page, SLOTS.presence);
	await joinSlot(tab, SLOTS.presence);

	await expect(presenceCount(page)).toHaveText('2');
	await expect(await openPeople(page)).toHaveText(['Testeryou', 'Tester']);
});

test('a rename is shown to everyone on the slot, title-cased', async ({
	page,
	person,
	context
}) => {
	// T-014: a rename of `john smith` is broadcast as `John Smith`.
	const other = await person('Bea');
	const tab = await context.newPage();
	await joinSlot(page, SLOTS.names);
	await joinSlot(other, SLOTS.names);
	await joinSlot(tab, SLOTS.names);
	await expect(await openPeople(other)).toHaveText(['Tester', 'Beayou', 'Tester']);

	await nameButton(page).click();
	await page.getByRole('textbox', { name: 'Your name' }).fill('john smith');
	await page.keyboard.press('Enter');

	await expect(nameButton(page)).toHaveText('John Smith');
	// The other tab of this browser took the name from storage, and sent it too.
	await expect(await openPeople(other)).toHaveText(['John Smith', 'Beayou', 'John Smith']);
	await expect(await openPeople(page)).toHaveText(['John Smithyou', 'Bea', 'John Smith']);
	// The name beside the cursor on the other canvas follows.
	await expect
		.poll(async () => (await canvasPeers(other)).map((peer) => peer.username))
		.toEqual(['John Smith', 'John Smith']);
});

test('a new title is seen by a second browser, and is still there after a reload', async ({
	page,
	person,
	request
}) => {
	// T-016.
	const slot = SLOTS.title;
	const title = `Core ${test.info().project.name}`;
	const other = await person('Bea');
	await joinSlot(page, slot);
	await joinSlot(other, slot);
	await expect(other.getByRole('heading', { level: 1 })).toHaveText(`Workspace ${slot}`);

	try {
		await page.getByRole('heading', { level: 1 }).getByRole('button').click();
		const field = page.getByRole('textbox', { name: 'Slot title' });
		await expect(field).toHaveValue(`Workspace ${slot}`);
		await field.fill(`  ${title}  `);
		await page.keyboard.press('Enter');

		for (const browser of [page, other]) {
			await expect(browser.getByRole('heading', { level: 1 })).toHaveText(title);
			await expect(browser).toHaveTitle(`${title} · segl`);
			await expect(browser.getByRole('link', { name: `Slot ${slot}: ${title}` })).toBeVisible();
		}
		await other.reload();
		await expect(other.getByRole('heading', { level: 1 })).toHaveText(title);

		// A title of only spaces is refused in the field, and Escape keeps the old one.
		await page.getByRole('heading', { level: 1 }).getByRole('button').click();
		await field.fill('   ');
		await page.keyboard.press('Enter');
		await expect(page.getByRole('alert')).toHaveText('1 to 80 characters');
		await page.keyboard.press('Escape');
		await expect(page.getByRole('heading', { level: 1 })).toHaveText(title);

		// Slots have no create or delete route.
		expect((await request.post('api/v1/slots', { data: { title: 'New' } })).status()).toBe(405);
		expect((await request.delete(`api/v1/slots/${slot}`)).status()).toBe(405);
		expect(
			((await (await request.get('api/v1/slots')).json()) as { slots: unknown[] }).slots
		).toHaveLength(9);
	} finally {
		// The other tests name this slot by its first title.
		const restored = await request.patch(`api/v1/slots/${slot}`, {
			data: { title: `Workspace ${slot}` }
		});
		expect(restored.status()).toBe(200);
	}
	await expect(page.getByRole('heading', { level: 1 })).toHaveText(`Workspace ${slot}`);
});

test('a drawing stays on its slot when the person goes to another', async ({ page, person }) => {
	await joinSlot(page, SLOTS.drawing);
	const here = await drawRectangle(page, -100, 200);

	// Through the bar, without a page load: the canvas of one slot is taken
	// down and the next one put up.
	await switchSlot(page, SLOTS.names, `Workspace ${SLOTS.names}`);
	const there = await drawRectangle(page, 100, 200);

	const other = await person('Bea');
	await joinSlot(other, SLOTS.names);
	await expectElement(other, there);
	expect(await elementIds(other)).not.toContain(here);
	expect(await elementIds(page)).not.toContain(here);

	await switchSlot(page, SLOTS.drawing, `Workspace ${SLOTS.drawing}`);
	await expectElement(page, here);
	expect(await elementIds(page)).not.toContain(there);
});

test('a browser that opens a slot sends none of the drawing it loaded back', async ({
	page,
	person
}) => {
	const slot = SLOTS.drawing;
	const other = await person('Cy');
	await joinSlot(other, slot);
	const theirs = await drawRectangle(other, -300, 150);
	await expectSaved(other);

	// The page loads the scene over HTTP, and the server's own copy comes over
	// the socket after `welcome`. Here it comes a second later, so whatever the
	// page would send in between, it sends.
	const sent: { type: string; elements?: { id: string }[] }[] = [];
	await page.routeWebSocket(/\/collab\?slot=\d$/, (route) => {
		const server = route.connectToServer();
		route.onMessage((message) => {
			sent.push(JSON.parse(String(message)) as (typeof sent)[number]);
			server.send(message);
		});
		server.onMessage((message) => {
			const { type } = JSON.parse(String(message)) as { type: string };
			if (type === 'scene') setTimeout(() => route.send(message), 1000);
			else route.send(message);
		});
	});
	await openSlot(page, `s/${slot}`);
	await expectLive(page);
	await expectElement(page, theirs);
	// The canvas has something to report meanwhile: the other person is drawn
	// on it at `welcome`, and their pointer moves.
	const canvas = (await other.locator('.excalidraw canvas.interactive').boundingBox())!;
	await other.mouse.move(canvas.x + 300, canvas.y + 300);
	await other.mouse.move(canvas.x + 400, canvas.y + 350, { steps: 5 });
	await expect.poll(async () => (await canvasPeers(page)).length).toBe(1);
	await page.waitForTimeout(1500);

	const edits = () => sent.filter((message) => message.type === 'elements');
	expect(edits()).toEqual([]);
	// It drew nothing, so the bar has nothing to call saved.
	await expect(connectionStatus(page)).toHaveAttribute('data-state', 'live');

	// What it then draws goes out, and nothing else with it.
	const mine = await drawRectangle(page, 300, 150);
	await expectSaved(page);
	await expectElement(other, mine);
	const ids = edits().flatMap((message) => (message.elements ?? []).map((each) => each.id));
	expect([...new Set(ids)]).toEqual([mine]);
});

test('a page that reloads a quiet slot is sent a socket scene with no element', async ({
	page
}) => {
	// D2-037: the scene comes once, over HTTP.
	const tap = await tapSockets(page);
	await joinSlot(page, SLOTS.reconnect);
	const drawn = await drawRectangle(page, 150, -200);
	await expectSaved(page);

	tap.received.length = 0;
	tap.sent.length = 0;
	await page.reload();
	await expectLive(page);
	await expectElement(page, drawn);

	const scenes = tap.received.filter((message) => message.type === 'scene');
	expect(scenes).toHaveLength(1);
	expect(scenes[0]).toMatchObject({ whole: false, elements: [], files: [] });
	// The page handed back the mark that came with the scene route's answer.
	const hello = tap.sent.find((message) => message.type === 'hello');
	expect(hello?.['mark']).toBe(scenes[0]!['mark']);
});

test('a socket that drops while another browser edits comes back, and both end with the same scene', async ({
	page,
	person
}) => {
	const tap = await tapSockets(page);
	const other = await person('Bea');
	await joinSlot(other, SLOTS.reconnect);
	const before = await drawRectangle(other, -300, 250);
	await joinSlot(page, SLOTS.reconnect);
	await expectElement(page, before);
	const shared = await drawRectangle(page, -150, 250);
	await expectElement(other, shared);

	await tap.kill();
	await expect(connectionStatus(page)).toHaveAttribute('data-state', 'disconnected');
	const theirs = await drawRectangle(other, 150, 250);
	const mine = await drawRectangle(page, 300, 250);
	const heard = tap.received.length;

	tap.restore();
	await expectLive(page);
	await expectElement(page, theirs);
	await expectElement(other, mine);
	await expect
		.poll(async () => (await stamps(page)).join('\n'))
		.toBe((await stamps(other)).join('\n'));

	// The scene after the reconnect held what changed while this page was
	// away, and not what it already had.
	const scene = tap.received.slice(heard).find((message) => message.type === 'scene');
	expect(scene?.['whole']).toBe(false);
	expect(idsOf(scene)).toContain(theirs);
	expect(idsOf(scene)).not.toContain(before);
});

test('a batch lost with its socket reaches the other browser after the reconnect', async ({
	page,
	person
}) => {
	// T-004: the network loses what the page sent, and the page believes it went.
	const tap = await tapSockets(page);
	const other = await person('Bea');
	await joinSlot(page, SLOTS.reconnect);
	await joinSlot(other, SLOTS.reconnect);

	tap.hold();
	const lost = await drawRectangle(page, 250, -250);
	await expect.poll(() => tap.dropped.some((message) => idsOf(message).includes(lost))).toBe(true);
	expect(await elementIds(other)).not.toContain(lost);
	await tap.kill();
	const heard = tap.received.length;
	const said = tap.sent.length;

	tap.restore();
	await expectLive(page);
	await expectElement(other, lost);
	await expectSaved(page);

	// The server's scene had nothing new, since it never got the batch. The
	// page sent it again from what it knew the server held.
	const scene = tap.received.slice(heard).find((message) => message.type === 'scene');
	expect(scene).toMatchObject({ whole: false });
	expect(idsOf(scene)).not.toContain(lost);
	const again = tap.sent.slice(said).filter((message) => message.type === 'elements');
	expect(again.flatMap(idsOf)).toContain(lost);
});
