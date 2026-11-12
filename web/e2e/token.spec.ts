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
 * The edit token in a browser (docs/TEST-PLAN.md T-008, and the browser's
 * part of T-012), against a segl that has one: the `token-` projects of
 * `playwright.config.ts`.
 *
 * A test's own `page` is a browser without the token: a viewer. A browser
 * with it is `person(name, { editToken })`, or a page that opens an edit
 * link. The three projects share the one server and its slots, so a test
 * asserts on what it drew itself.
 */
import { expect, type APIRequestContext, type Page } from '@playwright/test';
import {
	canvasImages,
	chooseImport,
	collabUrl,
	confirmImport,
	connectionStatus,
	drawRectangle,
	dropFile,
	dropImage,
	elementIds,
	elementOf,
	expectEditor,
	expectLive,
	expectPainted,
	expectSaved,
	importControl,
	joinSlot,
	nameButton,
	openHistory,
	openPeople,
	png,
	presenceCount,
	restoreRow,
	sceneDocument,
	SLOTS,
	switchSlot,
	test,
	tokenKey,
	type Rgb
} from './pages.ts';
import { EDIT_TOKEN } from './sites.ts';

const HEADER = { 'X-Segl-Edit-Token': EDIT_TOKEN };

/** `token-board` runs at the mount `board` runs at. */
function mount(): 'direct' | 'root' | 'board' {
	return test.info().project.name.replace(/^token-/, '') as 'direct' | 'root' | 'board';
}

/** Each project draws in a row of its own, so its rectangles are not under another's. */
function row(): number {
	return ['direct', 'root', 'board'].indexOf(mount());
}

/** Each project's image is another color, so another file. */
const COLORS: Record<string, Rgb> = {
	direct: [40, 160, 220],
	root: [220, 160, 40],
	board: [160, 40, 220]
};

const NEEDS_TOKEN = 'Editing is locked: it needs the edit token.';
const TOKEN_REFUSED = 'Editing is locked: this segl did not take the edit token this browser has.';
const HAS_TOKEN = 'This browser has the edit token and can edit.';

function notice(page: Page) {
	return page.locator('header.segl-bar .segl-bar__notice');
}

function rectangleTool(page: Page) {
	return page.locator('[data-testid="toolbar-rectangle"]');
}

/** This page may look and not edit, for want of a token, and its bar says so. */
async function expectLocked(page: Page): Promise<void> {
	await expect(notice(page)).toHaveAttribute('data-editing', 'locked');
	await expect(notice(page)).toHaveText(
		`Shared workspace. Anyone who can open this page can see it. ${NEEDS_TOKEN}`
	);
	await expect(rectangleTool(page)).toHaveCount(0);
}

/** This page may edit: the server took its token, the bar says so, and the tools are there. */
async function expectUnlocked(page: Page): Promise<void> {
	await expect(notice(page)).toHaveAttribute('data-editing', 'unlocked');
	await expect(notice(page)).toHaveText(
		`Shared workspace. Anyone who can open this page can see it. ${HAS_TOKEN}`
	);
	await expect(rectangleTool(page)).toBeVisible();
}

async function storedToken(page: Page, baseURL: string | undefined): Promise<string | null> {
	return page.evaluate((key) => localStorage.getItem(key), tokenKey(baseURL));
}

async function expectElement(page: Page, id: string): Promise<void> {
	await expect.poll(() => elementIds(page), { message: `element ${id} arrives` }).toContain(id);
}

async function expectNoElement(page: Page, id: string): Promise<void> {
	await expect.poll(() => elementIds(page), { message: `element ${id} goes` }).not.toContain(id);
}

interface Slot {
	title: string;
	epoch: number;
}

async function slotOf(request: APIRequestContext, slot: number): Promise<Slot> {
	return (await (await request.get(`api/v1/slots/${slot}`)).json()) as Slot;
}

interface Traffic {
	/** Every address the page asked for, and every socket it opened. */
	urls: string[];
	/** Responses that set a cookie. */
	cookies: string[];
}

/** Watch what a page asks for. Call before `goto`. */
function watch(page: Page): Traffic {
	const traffic: Traffic = { urls: [], cookies: [] };
	page.on('request', (request) => traffic.urls.push(request.url()));
	page.on('websocket', (socket) => traffic.urls.push(socket.url()));
	page.on('response', async (response) => {
		if ((await response.headerValue('set-cookie')) !== null) traffic.cookies.push(response.url());
	});
	return traffic;
}

/** The addresses that carry the token, or a recognizable part of it, raw or encoded. */
function withToken(urls: string[]): string[] {
	const parts = ['S3gl+e2e', 'S3gl%2Be2e', 'e2e/Token', 'e2e%2FToken', 'Token==', 'Token%3D'];
	return urls.filter((url) => parts.some((part) => url.includes(part)));
}

/**
 * Ask the server for something from inside a page, as a script on that page
 * could: with the page's own origin, and without the token unless given.
 * `path` is under segl's root.
 */
async function forced(
	page: Page,
	baseURL: string | undefined,
	path: string,
	options: { method: string; type?: string; body?: string; token?: string }
): Promise<{ status: number; error: string | undefined }> {
	return page.evaluate(
		async ([url, method, type, body, token]) => {
			const headers: Record<string, string> = {};
			if (type !== null) headers['Content-Type'] = type;
			if (token !== null) headers['X-Segl-Edit-Token'] = token;
			const response = await fetch(url, { method, headers, body: body ?? undefined });
			const answer = (await response.json()) as { error?: string };
			return { status: response.status, error: answer.error };
		},
		[
			new URL(path, baseURL).href,
			options.method,
			options.type ?? null,
			options.body ?? null,
			options.token ?? null
		] as const
	);
}

const VIEW_ONLY = { status: 403, error: 'view_only' };

/**
 * Say `hello` on a socket of the page's own, with `token`, and try to add an
 * element. Returns what the server answered: `welcome` with its `viewOnly`,
 * `scene`, and the error, if any.
 */
async function forcedElement(
	page: Page,
	url: string,
	token: string,
	id: string
): Promise<string[]> {
	return page.evaluate(
		([address, editToken, elementId]) =>
			new Promise<string[]>((resolve) => {
				const answers: string[] = [];
				const socket = new WebSocket(address);
				const done = () => {
					socket.close();
					resolve(answers);
				};
				socket.onopen = () =>
					socket.send(
						JSON.stringify({
							type: 'hello',
							clientId: 'forced-1',
							displayName: 'Forced',
							editToken
						})
					);
				socket.onmessage = (event) => {
					const message = JSON.parse(String(event.data)) as Record<string, unknown>;
					if (message['type'] === 'welcome') answers.push(`welcome ${message['viewOnly']}`);
					if (message['type'] === 'error') {
						answers.push(`error ${message['error']}`);
						done();
					}
					if (message['type'] === 'saved') {
						answers.push('saved');
						done();
					}
					if (message['type'] !== 'scene') return;
					answers.push('scene');
					socket.send(
						JSON.stringify({
							type: 'elements',
							epoch: message['epoch'],
							seq: 1,
							elements: [
								{
									id: elementId,
									type: 'rectangle',
									version: 1,
									versionNonce: 1,
									index: 'a0',
									isDeleted: false,
									x: 0,
									y: 0,
									width: 10,
									height: 10
								}
							]
						})
					);
				};
				socket.onclose = () => resolve(answers);
				setTimeout(done, 5000);
			}),
		[url, token, id] as const
	);
}

test('a browser without the token watches live and cannot change the canvas', async ({
	page,
	person,
	request,
	baseURL,
	context
}) => {
	// T-008, the elements.
	const slot = SLOTS.drawing;
	const traffic = watch(page);
	const editor = await person('Edna', { editToken: EDIT_TOKEN });
	const editorTraffic = watch(editor);
	await joinSlot(page, slot);
	await joinSlot(editor, slot);
	await expectLocked(page);
	await expectUnlocked(editor);

	// It watches live.
	const drawn = await drawRectangle(editor, -250, -200 + row() * 120);
	await expectElement(page, drawn);
	const there = (await elementOf(editor, drawn))!;
	expect(await elementOf(page, drawn)).toMatchObject({ type: 'rectangle', x: there.x, y: there.y });
	await expectSaved(editor);

	// It cannot change the elements. Whatever a person might try on the canvas:
	const before = (await sceneDocument(page)).elements.map((each) => [each.id, each.version]);
	const images = (await canvasImages(page)).length;
	const canvas = (await page.locator('.excalidraw canvas.interactive').boundingBox())!;
	// The key of the rectangle tool, and a drag.
	await page.mouse.click(canvas.x + canvas.width / 2, canvas.y + canvas.height - 150);
	await page.keyboard.press('r');
	await page.mouse.move(canvas.x + 500, canvas.y + 500);
	await page.mouse.down();
	await page.mouse.move(canvas.x + 600, canvas.y + 560, { steps: 5 });
	await page.mouse.up();
	// A press on the rectangle that is there, and the keys that delete.
	await page.mouse.click(canvas.x + there.x + 2, canvas.y + there.y + 2);
	await page.keyboard.press('Delete');
	await page.keyboard.press('Backspace');
	await page.keyboard.press('Control+a');
	await page.keyboard.press('Delete');
	// A double press, which starts a text for an editor.
	await page.mouse.dblclick(canvas.x + 700, canvas.y + 300);
	await page.keyboard.type('mine');
	await page.keyboard.press('Escape');
	// Something pasted.
	await page.evaluate(() => {
		const clipboardData = new DataTransfer();
		clipboardData.setData('text/plain', 'pasted');
		document.dispatchEvent(new ClipboardEvent('paste', { clipboardData, bubbles: true }));
	});
	// An image dragged in from a folder, which the editor's own view mode would place.
	const picture = { name: 'picture.png', type: 'image/png', bytes: png(120, 80, COLORS[mount()]!) };
	await dropFile(page, picture, 500, 300);
	// And a link dragged in from another window, which the editor would embed.
	const link = await page.evaluateHandle(() => {
		const transfer = new DataTransfer();
		transfer.setData('text/plain', 'https://www.youtube.com/watch?v=dQw4w9WgXcQ');
		return transfer;
	});
	await page
		.locator('.excalidraw canvas.interactive')
		.dispatchEvent('drop', { dataTransfer: link, clientX: 600, clientY: 400 });
	await page.waitForTimeout(700);

	const after = (await sceneDocument(page)).elements.map((each) => [each.id, each.version]);
	expect(after).toEqual(before);
	expect(await canvasImages(page)).toHaveLength(images);
	// The editor has had nothing from it, and neither has the stored scene.
	expect(await elementOf(editor, drawn)).toMatchObject({ version: there.version });
	// A viewer is never saving: it has nothing to save.
	await expect(connectionStatus(page)).toHaveAttribute('data-state', 'live');
	await expect(connectionStatus(page)).toHaveText('Live');

	// A script on the viewer's page, with a socket of its own, is refused by
	// the server: without a token, and with one that is a character short.
	for (const [index, token] of ['', EDIT_TOKEN.slice(0, -1)].entries()) {
		const id = `forced-${mount()}-${index}-${Date.now()}`;
		const answers = await forcedElement(page, collabUrl(baseURL, slot), token, id);
		expect(answers).toEqual(['welcome true', 'scene', 'error view_only']);
		expect(await elementIds(editor)).not.toContain(id);
	}
	const head = (await (await request.get(`api/v1/slots/${slot}/scene`)).json()) as {
		scene: { elements: { id: string }[] };
	};
	expect(
		head.scene.elements.map((each) => each.id).filter((id) => id.startsWith('forced-'))
	).toEqual([]);

	// The editor draws on, and the viewer still sees it.
	const next = await drawRectangle(editor, -100, -200 + row() * 120);
	await expectElement(page, next);

	// T-012 in a browser: nothing set a cookie, and the token is in no address
	// either browser asked for.
	await page.waitForLoadState('networkidle');
	expect(traffic.cookies).toEqual([]);
	expect(editorTraffic.cookies).toEqual([]);
	expect(await context.cookies()).toEqual([]);
	expect(await editor.context().cookies()).toEqual([]);
	expect(await page.evaluate(() => document.cookie)).toBe('');
	expect(await editor.evaluate(() => document.cookie)).toBe('');
	expect(editorTraffic.urls.length).toBeGreaterThan(5);
	expect(withToken(editorTraffic.urls)).toEqual([]);
	expect(withToken(traffic.urls)).toEqual([]);
});

test('a browser without the token cannot change the title, and sees the change of one that has it', async ({
	page,
	person,
	request,
	baseURL
}) => {
	// T-008, the title.
	const slot = SLOTS.title;
	const title = `Gated ${mount()}`;
	const editor = await person('Edna', { editToken: EDIT_TOKEN });
	await joinSlot(page, slot);
	await joinSlot(editor, slot);
	const before = await slotOf(request, slot);

	try {
		// For the viewer the title is text, with nothing to press.
		await expect(page.getByRole('heading', { level: 1 })).toHaveText(before.title);
		await expect(page.getByRole('heading', { level: 1 }).getByRole('button')).toHaveCount(0);
		// A script on its page is refused: without the token, and with a wrong one.
		const body = JSON.stringify({ title: 'Taken over' });
		const patch = { method: 'PATCH', type: 'application/json', body };
		expect(await forced(page, baseURL, `api/v1/slots/${slot}`, patch)).toEqual(VIEW_ONLY);
		expect(
			await forced(page, baseURL, `api/v1/slots/${slot}`, { ...patch, token: 'not-the-token' })
		).toEqual(VIEW_ONLY);
		expect(await slotOf(request, slot)).toEqual(before);

		// The editor changes it in its bar, and the viewer's bar follows.
		await editor.getByRole('heading', { level: 1 }).getByRole('button').click();
		await editor.getByRole('textbox', { name: 'Slot title' }).fill(title);
		await editor.keyboard.press('Enter');
		for (const browser of [editor, page]) {
			await expect(browser.getByRole('heading', { level: 1 })).toHaveText(title);
			await expect(browser).toHaveTitle(`${title} · segl`);
		}
		expect((await slotOf(request, slot)).title).toBe(title);
		// And it is still text for the viewer.
		await expect(page.getByRole('heading', { level: 1 }).getByRole('button')).toHaveCount(0);
	} finally {
		// The next project finds the slot as this one did.
		const restored = await request.patch(`api/v1/slots/${slot}`, {
			data: { title: before.title },
			headers: HEADER
		});
		expect(restored.status()).toBe(200);
	}
});

test('a browser without the token reads the history and cannot restore, and follows a restore', async ({
	page,
	person,
	request,
	baseURL
}) => {
	// T-008, the history.
	const slot = SLOTS.history;
	const editor = await person('Edna', { editToken: EDIT_TOKEN });
	await joinSlot(page, slot);
	await joinSlot(editor, slot);

	// Two revisions: the server keeps at most one a second while people draw.
	const newest = async () => {
		const listed = (await (await request.get(`api/v1/slots/${slot}/revisions`)).json()) as {
			revisions: { revision: number }[];
		};
		return listed.revisions[0]!.revision;
	};
	await editor.waitForTimeout(1100);
	const first = await drawRectangle(editor, 150, -200 + row() * 120);
	await expectSaved(editor);
	const kept = await newest();
	await editor.waitForTimeout(1100);
	const second = await drawRectangle(editor, 300, -200 + row() * 120);
	await expectSaved(editor);
	expect(await newest()).toBeGreaterThan(kept);
	await expectElement(page, second);
	const epoch = (await slotOf(request, slot)).epoch;

	// The viewer's list has the rows, nothing to press, and the reason.
	const rows = await openHistory(page);
	expect(await rows.count()).toBeGreaterThanOrEqual(2);
	await expect(rows.and(page.locator(`[data-revision="${kept}"]`))).toHaveCount(1);
	const panel = page.getByRole('group', { name: 'History of this slot' });
	await expect(panel.getByRole('button')).toHaveCount(0);
	await expect(panel).toContainText('Restoring needs the edit token.');
	// A script on its page is refused.
	const body = JSON.stringify({ revision: kept, displayName: 'Viewer' });
	expect(
		await forced(page, baseURL, `api/v1/slots/${slot}/restore`, {
			method: 'POST',
			type: 'application/json',
			body
		})
	).toEqual(VIEW_ONLY);
	expect((await slotOf(request, slot)).epoch).toBe(epoch);
	expect(await elementIds(page)).toContain(second);

	// The editor restores the older revision, and the viewer's canvas follows.
	const editorRows = await openHistory(editor);
	await restoreRow(editorRows.and(editor.locator(`[data-revision="${kept}"]`)));
	await expectNoElement(page, second);
	await expectNoElement(editor, second);
	expect(await elementIds(page)).toContain(first);
	expect((await slotOf(request, slot)).epoch).toBe(epoch + 1);
	// So does its open list: the restore's row is on top, marked, and still
	// nothing can be pressed.
	await expect(rows.first()).toContainText('replacement');
	await expect(panel.getByRole('button')).toHaveCount(0);
});

test('a browser without the token cannot import, and follows an import', async ({
	page,
	person,
	request,
	baseURL
}) => {
	// T-008, the import.
	const slot = SLOTS.importing;
	const editor = await person('Edna', { editToken: EDIT_TOKEN });
	await joinSlot(page, slot);
	await joinSlot(editor, slot);
	const epoch = (await slotOf(request, slot)).epoch;
	const id = `imported-${mount()}-${Date.now()}`;
	const text = JSON.stringify({
		type: 'excalidraw',
		version: 2,
		source: 'segl',
		elements: [
			{
				id,
				type: 'rectangle',
				version: 1,
				versionNonce: 1,
				index: 'a0',
				isDeleted: false,
				x: 100,
				y: 100,
				width: 80,
				height: 50
			}
		],
		appState: {},
		files: {}
	});

	// The viewer's Import button says what importing needs, and opens no file dialog.
	const choosers: string[] = [];
	page.on('filechooser', () => choosers.push('opened'));
	const control = importControl(page);
	await control.getByRole('button', { name: 'Import', exact: true }).click();
	await expect(control.getByRole('group')).toHaveText('Importing needs the edit token.');
	await page.waitForTimeout(300);
	expect(choosers).toEqual([]);
	// A scene file dropped on its canvas is named, with the same words and nothing to press.
	await dropFile(
		page,
		{ name: 'network.excalidraw', type: '', bytes: Buffer.from(text) },
		500,
		300
	);
	await expect(control.getByRole('group')).toContainText('network.excalidraw');
	await expect(control.getByRole('group')).toContainText('Importing needs the edit token.');
	await expect(control.getByRole('button', { name: 'Import it' })).toHaveCount(0);
	// A script on its page is refused.
	expect(
		await forced(page, baseURL, `api/v1/slots/${slot}/import`, { method: 'POST', body: text })
	).toEqual(VIEW_ONLY);
	expect((await slotOf(request, slot)).epoch).toBe(epoch);
	expect(await elementIds(page)).not.toContain(id);

	// The editor imports the file, and the viewer's canvas is the file's.
	const question = await chooseImport(editor, { name: 'network.excalidraw', text });
	await confirmImport(question);
	await expect.poll(() => elementIds(page)).toEqual([id]);
	await expect.poll(() => elementIds(editor)).toEqual([id]);
	expect((await slotOf(request, slot)).epoch).toBe(epoch + 1);
});

test('a browser without the token cannot upload, and paints the image of one that has it', async ({
	page,
	person,
	baseURL
}) => {
	// T-008, the uploaded files (S-008: "asset writes require the token").
	const slot = SLOTS.images;
	const color = COLORS[mount()]!;
	const uploads: string[] = [];
	page.on('request', (request) => {
		if (request.method() === 'POST' && request.url().includes('/assets'))
			uploads.push(request.url());
	});
	const editor = await person('Edna', { editToken: EDIT_TOKEN });
	await joinSlot(page, slot);
	await joinSlot(editor, slot);

	// A script on the viewer's page is refused.
	expect(
		await forced(page, baseURL, `api/v1/slots/${slot}/assets`, {
			method: 'POST',
			type: 'image/png',
			body: 'not really a picture'
		})
	).toEqual(VIEW_ONLY);
	uploads.length = 0;

	// The editor places an image. The viewer paints it, and uploads nothing.
	const image = await dropImage(editor, png(160, 100, color), 420 + row() * 190, 420);
	await expectSaved(editor);
	await expectPainted(page, image.id, color);
	await expectPainted(editor, image.id, color);
	expect(uploads).toEqual([]);
	await expect(connectionStatus(page)).toHaveAttribute('data-state', 'live');
});

test('a browser without the token is still someone on the slot, with a name of its own', async ({
	page,
	person
}) => {
	// Presence and rename need no token (docs/ARCHITECTURE.md, edit gate).
	const slot = SLOTS.presence;
	const editor = await person('Edna', { editToken: EDIT_TOKEN });
	await joinSlot(page, slot);
	await joinSlot(editor, slot);

	await expect(presenceCount(editor)).toHaveText('2');
	await expect(presenceCount(page)).toHaveText('2');
	await expect(await openPeople(editor)).toContainText(['Tester', 'Edna']);

	await nameButton(page).click();
	await page.getByRole('textbox', { name: 'Your name' }).fill('vera viewer');
	await page.keyboard.press('Enter');

	await expect(nameButton(page)).toHaveText('Vera Viewer');
	await expect(await openPeople(editor)).toContainText(['Vera Viewer', 'Edna']);
	await expectLocked(page);
});

test('an edit link makes a browser an editor, is taken out of the address, and is in no request', async ({
	page,
	request,
	baseURL,
	context
}) => {
	// T-008, the fragment link: as someone copies the token out of segl.toml.
	const slot = SLOTS.tools;
	const traffic = watch(page);

	await page.goto(`s/${slot}#e=${EDIT_TOKEN}`);
	await expectEditor(page);
	await expectLive(page);

	// The fragment went, and nothing was added to the tab's history for it.
	await expect(page).toHaveURL(new URL(`s/${slot}`, baseURL).href);
	expect(await page.evaluate(() => location.hash)).toBe('');
	expect(await page.evaluate(() => history.length)).toBeLessThanOrEqual(2);
	// The server took the token, so the browser keeps it, under the mount's key.
	await expectUnlocked(page);
	expect(await storedToken(page, baseURL)).toBe(EDIT_TOKEN);

	// It edits: the canvas, and the title, which goes with the token in a header.
	const drawn = await drawRectangle(page, 250, -200 + row() * 120);
	await expectSaved(page);
	const head = (await (await request.get(`api/v1/slots/${slot}/scene`)).json()) as {
		scene: { elements: { id: string }[] };
	};
	expect(head.scene.elements.map((each) => each.id)).toContain(drawn);
	const before = await slotOf(request, slot);
	try {
		await page.getByRole('heading', { level: 1 }).getByRole('button').click();
		await page.getByRole('textbox', { name: 'Slot title' }).fill(`Linked ${mount()}`);
		await page.keyboard.press('Enter');
		await expect(page.getByRole('heading', { level: 1 })).toHaveText(`Linked ${mount()}`);
		expect((await slotOf(request, slot)).title).toBe(`Linked ${mount()}`);
	} finally {
		await request.patch(`api/v1/slots/${slot}`, { data: { title: before.title }, headers: HEADER });
	}

	// It is still an editor after a reload, which has no fragment to read,
	await page.reload();
	await expectEditor(page);
	await expectLive(page);
	await expectUnlocked(page);
	await expectElement(page, drawn);
	// and on another slot.
	await switchSlot(page, SLOTS.empty, `Workspace ${SLOTS.empty}`);
	await expectUnlocked(page);

	// The token went to the server in a header and in `hello`, and in no address.
	await page.waitForLoadState('networkidle');
	expect(traffic.urls.length).toBeGreaterThan(10);
	expect(withToken(traffic.urls)).toEqual([]);
	expect(traffic.urls.filter((url) => url.includes('#'))).toEqual([]);
	expect(traffic.cookies).toEqual([]);
	expect(await context.cookies()).toEqual([]);
});

test("a link at segl's root, percent-encoded, works the same", async ({ page, baseURL }) => {
	await page.goto(`./#e=${encodeURIComponent(EDIT_TOKEN)}`);

	// The root sends a new browser on to slot 1, and the fragment does not come along.
	await expect(page).toHaveURL(new URL('s/1', baseURL).href);
	await expectEditor(page);
	await expectLive(page);
	await expectUnlocked(page);
	expect(await storedToken(page, baseURL)).toBe(EDIT_TOKEN);
});

test('a link with a wrong token is taken out of the address and is not stored', async ({
	page,
	baseURL
}) => {
	const slot = SLOTS.empty;

	await page.goto(`s/${slot}#e=not-the-token`);
	await expectEditor(page);
	await expectLive(page);

	await expect(page).toHaveURL(new URL(`s/${slot}`, baseURL).href);
	// The bar says that the token is wrong, not that there is none.
	await expect(notice(page)).toHaveAttribute('data-editing', 'refused');
	await expect(notice(page)).toContainText(TOKEN_REFUSED);
	await expect(rectangleTool(page)).toHaveCount(0);
	expect(await storedToken(page, baseURL)).toBeNull();

	// After a reload the browser has no token at all.
	await page.reload();
	await expectEditor(page);
	await expectLive(page);
	await expectLocked(page);
	expect(await storedToken(page, baseURL)).toBeNull();
});

test('a link with a wrong token does not take the place of a token that works', async ({
	person,
	baseURL
}) => {
	// Any page on the web can make a browser open such a link (D2-032).
	const slot = SLOTS.empty;
	const editor = await person('Edna', { editToken: EDIT_TOKEN });
	const hellos: string[] = [];
	editor.on('websocket', (socket) =>
		socket.on('framesent', (frame) => {
			const message = JSON.parse(String(frame.payload)) as { type: string; editToken?: string };
			if (message.type === 'hello') hellos.push(message.editToken ?? '');
		})
	);

	await editor.goto(`s/${slot}#e=not-the-token`);
	await expectEditor(editor);

	await expect(editor).toHaveURL(new URL(`s/${slot}`, baseURL).href);
	await expectUnlocked(editor);
	expect(await storedToken(editor, baseURL)).toBe(EDIT_TOKEN);
	// The link's token was tried, refused, and given up for the stored one.
	expect(hellos).toEqual(['not-the-token', EDIT_TOKEN]);

	await editor.reload();
	await expectEditor(editor);
	await expectLive(editor);
	await expectUnlocked(editor);
});

test('a link opened in a tab that is already on the slot unlocks it without a page load', async ({
	page,
	baseURL
}) => {
	const slot = SLOTS.empty;
	await joinSlot(page, slot);
	await expectLocked(page);
	await page.evaluate(() => {
		(window as unknown as { sameDocument: boolean }).sameDocument = true;
	});

	// The same address with a fragment: the browser loads nothing.
	await page.goto(`s/${slot}#e=${encodeURIComponent(EDIT_TOKEN)}`);

	await expectUnlocked(page);
	await expect(page).toHaveURL(new URL(`s/${slot}`, baseURL).href);
	expect(await storedToken(page, baseURL)).toBe(EDIT_TOKEN);
	expect(
		await page.evaluate(() => (window as unknown as { sameDocument?: boolean }).sameDocument)
	).toBe(true);
	// Back does not bring the link back.
	await page.goBack();
	expect(await page.evaluate(() => location.hash)).toBe('');
	expect(withToken([page.url()])).toEqual([]);
});

test('a link opened in one tab unlocks the other tabs of that browser', async ({
	page,
	context,
	baseURL
}) => {
	const slot = SLOTS.empty;
	await joinSlot(page, slot);
	await expectLocked(page);

	const tab = await context.newPage();
	await tab.goto(`s/${SLOTS.tools}#e=${EDIT_TOKEN}`);
	await expectEditor(tab);
	await expectUnlocked(tab);

	// The first tab says hello again with the stored token, and may edit.
	await expectUnlocked(page);
	expect(await storedToken(page, baseURL)).toBe(EDIT_TOKEN);
});

test('the notice of a locked browser stays inside a narrow page', async ({ page }) => {
	await page.setViewportSize({ width: 390, height: 800 });
	await joinSlot(page, SLOTS.empty);
	await expectLocked(page);

	const widths = await page.evaluate(() => [
		document.documentElement.scrollWidth,
		document.documentElement.clientWidth
	]);
	expect(widths).toEqual([390, 390]);
	await expect(notice(page)).toBeVisible();
});
