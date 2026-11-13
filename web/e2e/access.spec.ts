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
 * Access codes in a browser (docs/TEST-PLAN.md T-008 and T-019, and the
 * browser's part of T-012), against a segl that asks for one: the `access-`
 * projects of `playwright.config.ts`.
 *
 * A test's own `page` is a browser without a pass: a viewer. A browser with
 * one is `person(name, { editor: true })`, which buys a pass as the access
 * page does, or a page on which a code is entered. The three projects share
 * the one server and its slots, so a test asserts on what it drew itself.
 *
 * Every test here comes from 127.0.0.1, and five wrong codes in a row make an
 * address wait fifteen minutes. So a test that enters a wrong code enters a
 * right one afterwards, which starts the count again, and the wait itself is
 * shown with an answer the test puts in the server's place.
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
	buyPass,
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
	passKey,
	switchSlot,
	test,
	type Rgb
} from './pages.ts';
import { ACCESS_CODE, ACCESS_SECRET, PASS_SHAPE } from './sites.ts';

/** The header a pass travels in. Its name is from when it carried a token. */
const PASS_HEADER = 'X-Segl-Edit-Token';

/** `access-board` runs at the mount `board` runs at. */
function mount(): 'direct' | 'root' | 'board' {
	return test.info().project.name.replace(/^access-/, '') as 'direct' | 'root' | 'board';
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

const SHARED = 'Shared workspace. Anyone who can open this page can see it.';
const NEEDS_CODE = 'Editing is locked: it needs an access code.';
const ACCESS_ENDED = 'Editing is locked: the access this browser had has ended.';
const HAS_ACCESS = 'This browser entered an access code and can edit.';
const WRONG_CODE = "That is not one of this segl's access codes.";

function notice(page: Page) {
	return page.locator('header.segl-bar .segl-bar__notice');
}

function rectangleTool(page: Page) {
	return page.locator('[data-testid="toolbar-rectangle"]');
}

/** The way to the access page, by the notice, for a browser that may not edit. */
function accessLink(page: Page) {
	return notice(page).getByRole('link', { name: 'Enter access code' });
}

/** This page may look and not edit, for want of a pass, and its bar says so and offers the way. */
async function expectLocked(page: Page): Promise<void> {
	await expect(notice(page)).toHaveAttribute('data-editing', 'locked');
	await expect(notice(page)).toHaveText(`${SHARED} ${NEEDS_CODE} Enter access code`);
	await expect(accessLink(page)).toBeVisible();
	await expect(rectangleTool(page)).toHaveCount(0);
}

/** This page may edit: the server took its pass, the bar says so, and the tools are there. */
async function expectUnlocked(page: Page): Promise<void> {
	await expect(notice(page)).toHaveAttribute('data-editing', 'unlocked');
	await expect(notice(page)).toHaveText(`${SHARED} ${HAS_ACCESS}`);
	await expect(accessLink(page)).toHaveCount(0);
	await expect(rectangleTool(page)).toBeVisible();
}

/** This page has a pass the server does not take, and its bar says so and offers the way. */
async function expectEnded(page: Page): Promise<void> {
	await expect(notice(page)).toHaveAttribute('data-editing', 'refused');
	await expect(notice(page)).toHaveText(`${SHARED} ${ACCESS_ENDED} Enter access code`);
	await expect(accessLink(page)).toBeVisible();
	await expect(rectangleTool(page)).toHaveCount(0);
}

async function storedPass(page: Page, baseURL: string | undefined): Promise<string | null> {
	return page.evaluate((key) => localStorage.getItem(key), passKey(baseURL));
}

function codeField(page: Page) {
	return page.getByRole('textbox', { name: 'Access code' });
}

/** What the access page answered, in words. */
function answer(page: Page) {
	return page.locator('.segl-access__answer');
}

/** The access page is showing, under the mount. */
async function expectAccessPage(page: Page, baseURL: string | undefined): Promise<void> {
	await expect(page).toHaveURL(new URL('access', baseURL).href);
	await expect(page.getByRole('heading', { level: 1 })).toHaveText('Access code');
	await expect(page).toHaveTitle('Access code · segl');
	await expect(codeField(page)).toBeFocused();
}

/** Type a code into the access page's field and press Enter. */
async function enterCode(page: Page, code: string): Promise<void> {
	await codeField(page).fill(code);
	await page.keyboard.press('Enter');
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

/**
 * The addresses that carry a code, the secret, or a pass: the code as
 * written, encoded, and as the server compares it, and the signature of
 * each given pass.
 */
function withSecrets(urls: string[], passes: (string | null)[] = []): string[] {
	const parts = [
		'Maple',
		'maple',
		'River',
		'river.42',
		ACCESS_SECRET,
		...passes.filter((pass) => pass !== null).map((pass) => pass.split('.')[1]!)
	];
	return urls.filter((url) => parts.some((part) => url.includes(part)));
}

/**
 * Ask the server for something from inside a page, as a script on that page
 * could: with the page's own origin, and without a pass unless given.
 * `path` is under segl's root.
 */
async function forced(
	page: Page,
	baseURL: string | undefined,
	path: string,
	options: { method: string; type?: string; body?: string; pass?: string }
): Promise<{ status: number; error: string | undefined }> {
	return page.evaluate(
		async ([url, method, type, body, pass]) => {
			const headers: Record<string, string> = {};
			if (type !== null) headers['Content-Type'] = type;
			if (pass !== null) headers['X-Segl-Edit-Token'] = pass;
			const response = await fetch(url, { method, headers, body: body ?? undefined });
			const answer = (await response.json()) as { error?: string };
			return { status: response.status, error: answer.error };
		},
		[
			new URL(path, baseURL).href,
			options.method,
			options.type ?? null,
			options.body ?? null,
			options.pass ?? null
		] as const
	);
}

const VIEW_ONLY = { status: 403, error: 'view_only' };

/**
 * Say `hello` on a socket of the page's own, with `pass`, and try to add an
 * element. Returns what the server answered: `welcome` with its `viewOnly`,
 * `scene`, and the error, if any.
 */
async function forcedElement(page: Page, url: string, pass: string, id: string): Promise<string[]> {
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
		[url, pass, id] as const
	);
}

test('a browser without a pass watches live and cannot change the canvas', async ({
	page,
	person,
	request,
	baseURL,
	context
}) => {
	// T-008, the elements.
	const slot = SLOTS.drawing;
	const traffic = watch(page);
	const editor = await person('Edna', { editor: true });
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
	// the server: without a pass, with the editor's pass a character short,
	// and with the code itself where a pass goes.
	const editorPass = await storedPass(editor, baseURL);
	expect(editorPass).toMatch(PASS_SHAPE);
	for (const [index, sent] of ['', editorPass!.slice(0, -1), ACCESS_CODE].entries()) {
		const id = `forced-${mount()}-${index}-${Date.now()}`;
		const answers = await forcedElement(page, collabUrl(baseURL, slot), sent, id);
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

	// T-012 in a browser: nothing set a cookie, and no code and no pass is in
	// an address either browser asked for.
	await page.waitForLoadState('networkidle');
	expect(traffic.cookies).toEqual([]);
	expect(editorTraffic.cookies).toEqual([]);
	expect(await context.cookies()).toEqual([]);
	expect(await editor.context().cookies()).toEqual([]);
	expect(await page.evaluate(() => document.cookie)).toBe('');
	expect(await editor.evaluate(() => document.cookie)).toBe('');
	expect(editorTraffic.urls.length).toBeGreaterThan(5);
	expect(withSecrets(editorTraffic.urls, [editorPass])).toEqual([]);
	expect(withSecrets(traffic.urls, [editorPass])).toEqual([]);
});

test('a browser without a pass cannot change the title, and sees the change of one that has one', async ({
	page,
	person,
	request,
	baseURL
}) => {
	// T-008, the title.
	const slot = SLOTS.title;
	const title = `Gated ${mount()}`;
	const editor = await person('Edna', { editor: true });
	await joinSlot(page, slot);
	await joinSlot(editor, slot);
	const before = await slotOf(request, slot);

	try {
		// For the viewer the title is text, with nothing to press.
		await expect(page.getByRole('heading', { level: 1 })).toHaveText(before.title);
		await expect(page.getByRole('heading', { level: 1 }).getByRole('button')).toHaveCount(0);
		// A script on its page is refused: without a pass, and with what is not one.
		const body = JSON.stringify({ title: 'Taken over' });
		const patch = { method: 'PATCH', type: 'application/json', body };
		expect(await forced(page, baseURL, `api/v1/slots/${slot}`, patch)).toEqual(VIEW_ONLY);
		expect(
			await forced(page, baseURL, `api/v1/slots/${slot}`, { ...patch, pass: 'not-a-pass' })
		).toEqual(VIEW_ONLY);
		expect(
			await forced(page, baseURL, `api/v1/slots/${slot}`, { ...patch, pass: ACCESS_CODE })
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
			headers: { [PASS_HEADER]: await buyPass(request) }
		});
		expect(restored.status()).toBe(200);
	}
});

test('a browser without a pass reads the history and cannot restore, and follows a restore', async ({
	page,
	person,
	request,
	baseURL
}) => {
	// T-008, the history.
	const slot = SLOTS.history;
	const editor = await person('Edna', { editor: true });
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
	await expect(panel).toContainText('Restoring needs an access code.');
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

test('a browser without a pass cannot import, and follows an import', async ({
	page,
	person,
	request,
	baseURL
}) => {
	// T-008, the import.
	const slot = SLOTS.importing;
	const editor = await person('Edna', { editor: true });
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
	await expect(control.getByRole('group')).toHaveText('Importing needs an access code.');
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
	await expect(control.getByRole('group')).toContainText('Importing needs an access code.');
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

test('a browser without a pass cannot upload, and paints the image of one that has one', async ({
	page,
	person,
	baseURL
}) => {
	// T-008, the uploaded files (S-008: "asset writes need a pass").
	const slot = SLOTS.images;
	const color = COLORS[mount()]!;
	const uploads: string[] = [];
	page.on('request', (request) => {
		if (request.method() === 'POST' && request.url().includes('/assets'))
			uploads.push(request.url());
	});
	const editor = await person('Edna', { editor: true });
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

test('a browser without a pass is still someone on the slot, with a name of its own', async ({
	page,
	person
}) => {
	// Presence and rename need no pass (docs/ARCHITECTURE.md, edit gate).
	const slot = SLOTS.presence;
	const editor = await person('Edna', { editor: true });
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

test('a viewer follows the link in the bar, enters the code, and edits', async ({
	page,
	request,
	baseURL,
	context
}) => {
	// T-008 and T-019: the access page, from the bar and back to the slot.
	const slot = SLOTS.tools;
	const traffic = watch(page);
	const posted: { url: string; body: string | null; headers: Record<string, string> }[] = [];
	page.on('request', (sent) => {
		if (sent.method() === 'POST' && sent.url().endsWith('/api/v1/access')) {
			posted.push({ url: sent.url(), body: sent.postData(), headers: sent.headers() });
		}
	});
	await joinSlot(page, slot);
	await expectLocked(page);
	await page.evaluate(() => {
		(window as unknown as { samePage: boolean }).samePage = true;
	});

	// The link is by the notice, and goes to the access page under the mount.
	await accessLink(page).click();
	await expectAccessPage(page, baseURL);
	// One field, named for what it takes. It is not a login.
	await expect(page.getByRole('textbox')).toHaveCount(1);
	await expect(page.locator('input[type="password"]')).toHaveCount(0);
	await expect(page.locator('main')).toContainText(
		'Enter an access code to edit on this segl. Looking needs none.'
	);
	await expect(page.locator('main')).not.toContainText(/log ?in|sign ?in|password|user/i);
	await expect(page.getByRole('button', { name: 'Enter' })).toBeDisabled();

	// As a person types it: another case, other separators.
	await enterCode(page, 'maple river-42');

	// Back on the slot the person came from, as an editor, with no page load.
	await expect(page).toHaveURL(new URL(`s/${slot}`, baseURL).href);
	await expectEditor(page);
	await expectLive(page);
	await expectUnlocked(page);
	expect(await page.evaluate(() => (window as unknown as { samePage?: boolean }).samePage)).toBe(
		true
	);
	// The pass is this browser's, under the mount's key.
	const pass = await storedPass(page, baseURL);
	expect(pass).toMatch(PASS_SHAPE);
	// The access page is not left in the tab's history for Back to return to.
	expect(await page.evaluate(() => history.length)).toBeLessThanOrEqual(3);

	// It edits: the canvas, and the title, which goes with the pass in a header.
	const drawn = await drawRectangle(page, 250, -200 + row() * 120);
	await expectSaved(page);
	const head = (await (await request.get(`api/v1/slots/${slot}/scene`)).json()) as {
		scene: { elements: { id: string }[] };
	};
	expect(head.scene.elements.map((each) => each.id)).toContain(drawn);
	const before = await slotOf(request, slot);
	try {
		await page.getByRole('heading', { level: 1 }).getByRole('button').click();
		await page.getByRole('textbox', { name: 'Slot title' }).fill(`Entered ${mount()}`);
		await page.keyboard.press('Enter');
		await expect(page.getByRole('heading', { level: 1 })).toHaveText(`Entered ${mount()}`);
		expect((await slotOf(request, slot)).title).toBe(`Entered ${mount()}`);
	} finally {
		await request.patch(`api/v1/slots/${slot}`, {
			data: { title: before.title },
			headers: { [PASS_HEADER]: pass! }
		});
	}

	// It is still an editor after a reload,
	await page.reload();
	await expectEditor(page);
	await expectLive(page);
	await expectUnlocked(page);
	await expectElement(page, drawn);
	// and on another slot.
	await switchSlot(page, SLOTS.empty, `Workspace ${SLOTS.empty}`);
	await expectUnlocked(page);

	// The code went to the server once, in the body of a POST from this page.
	expect(posted).toHaveLength(1);
	expect(JSON.parse(posted[0]!.body ?? '')).toEqual({ code: 'maple river-42' });
	expect(posted[0]!.headers['x-segl-edit-token']).toBeUndefined();
	// No code and no pass is in an address, and nothing set a cookie.
	await page.waitForLoadState('networkidle');
	expect(traffic.urls.length).toBeGreaterThan(10);
	expect(withSecrets(traffic.urls, [pass])).toEqual([]);
	expect(traffic.cookies).toEqual([]);
	expect(await context.cookies()).toEqual([]);
	expect(await page.evaluate(() => document.cookie)).toBe('');
});

test('a wrong code is answered in words, and the right one then lets the browser edit', async ({
	page,
	baseURL
}) => {
	const slot = SLOTS.empty;
	await joinSlot(page, slot);
	await accessLink(page).click();
	await expectAccessPage(page, baseURL);

	await enterCode(page, 'Maple River 43');

	// Still on the access page, told so in words, with the field empty again.
	await expect(answer(page)).toHaveText(WRONG_CODE);
	await expect(answer(page)).toHaveAttribute('role', 'alert');
	await expect(page).toHaveURL(new URL('access', baseURL).href);
	await expect(codeField(page)).toHaveValue('');
	await expect(codeField(page)).toBeFocused();
	await expect(codeField(page)).toHaveAttribute('aria-invalid', 'true');
	expect(await storedPass(page, baseURL)).toBeNull();
	await expect(page.locator('body')).not.toContainText('Maple River 43');

	// The right one, which also starts the server's count of wrong codes again.
	await enterCode(page, ACCESS_CODE);

	await expect(page).toHaveURL(new URL(`s/${slot}`, baseURL).href);
	await expectEditor(page);
	await expectLive(page);
	await expectUnlocked(page);
	expect(await storedPass(page, baseURL)).toMatch(PASS_SHAPE);
});

test('a browser that has to wait is told for how long, and one the server cannot answer to try again', async ({
	page,
	baseURL
}) => {
	// The server's own wait is fifteen minutes for every test from this
	// address, so here an answer is put in its place (tests/test_access.py
	// has the real one).
	await page.goto('access');
	await expectAccessPage(page, baseURL);
	await page.route('**/api/v1/access', (route) =>
		route.fulfill({
			status: 429,
			contentType: 'application/json',
			headers: { 'Retry-After': '840' },
			body: JSON.stringify({ error: 'rate_limited', message: 'Too many.' })
		})
	);

	await enterCode(page, ACCESS_CODE);

	await expect(answer(page)).toHaveText(
		'Too many wrong codes came from this address. Try again in 14 minutes.'
	);
	// What was typed stays: it may be right, and is to be sent again later.
	await expect(codeField(page)).toHaveValue(ACCESS_CODE);
	expect(await storedPass(page, baseURL)).toBeNull();

	await page.unroute('**/api/v1/access');
	await page.route('**/api/v1/access', (route) => route.abort());
	await page.keyboard.press('Enter');

	await expect(answer(page)).toHaveText('segl could not be asked. Try again.');
	await expect(page).toHaveURL(new URL('access', baseURL).href);
	expect(await storedPass(page, baseURL)).toBeNull();

	// And once the server answers, the same code works.
	await page.unroute('**/api/v1/access');
	await page.keyboard.press('Enter');
	await expect(page).toHaveURL(new URL('s/1', baseURL).href);
	await expectEditor(page);
	await expectUnlocked(page);
});

test('the access page, opened by its address, goes back to the last slot this browser used', async ({
	page,
	baseURL
}) => {
	// A browser that has used no slot goes to slot 1.
	await page.goto('access');
	await expectAccessPage(page, baseURL);
	await expect(page.getByRole('link', { name: 'Back to slot 1' })).toBeVisible();

	// One that was on a slot goes back there: by the link, without a code,
	await joinSlot(page, SLOTS.empty);
	await page.goto('access');
	await expectAccessPage(page, baseURL);
	await page.getByRole('link', { name: `Back to slot ${SLOTS.empty}` }).click();
	await expect(page).toHaveURL(new URL(`s/${SLOTS.empty}`, baseURL).href);
	await expectEditor(page);
	await expectLive(page);
	await expectLocked(page);

	// and with one.
	await page.goto('access');
	await enterCode(page, ACCESS_CODE);
	await expect(page).toHaveURL(new URL(`s/${SLOTS.empty}`, baseURL).href);
	await expectEditor(page);
	await expectUnlocked(page);
});

test('the access page goes back to the slot its link was on, whatever another tab has opened since', async ({
	page,
	context,
	baseURL
}) => {
	// The slot comes with the link, not from the last slot this browser
	// stored, which another tab may have changed.
	const slot = SLOTS.empty;
	await joinSlot(page, slot);
	await expectLocked(page);
	const tab = await context.newPage();
	await joinSlot(tab, SLOTS.tools);
	await expectLocked(tab);

	await accessLink(page).click();
	await expectAccessPage(page, baseURL);
	await expect(page.getByRole('link', { name: `Back to slot ${slot}` })).toBeVisible();
	await enterCode(page, ACCESS_CODE);

	await expect(page).toHaveURL(new URL(`s/${slot}`, baseURL).href);
	await expectEditor(page);
	await expectUnlocked(page);
	// The other tab stayed where it was, and edits too.
	await expect(tab).toHaveURL(new URL(`s/${SLOTS.tools}`, baseURL).href);
	await expectUnlocked(tab);
});

test('an address that ends in #e= and something is an address like any other', async ({
	page,
	baseURL
}) => {
	// The edit link of an earlier build is gone (D2-033): nothing reads the
	// fragment, so what it carries opens nothing and is stored nowhere.
	const slot = SLOTS.empty;
	const hellos: string[] = [];
	page.on('websocket', (socket) =>
		socket.on('framesent', (frame) => {
			const message = JSON.parse(String(frame.payload)) as { type: string; editToken?: string };
			if (message.type === 'hello') hellos.push(message.editToken ?? '');
		})
	);

	// Even a real pass in the fragment makes no editor.
	const pass = await buyPass(page.request);
	for (const carried of ['an-old-token', ACCESS_CODE, pass]) {
		await page.goto(`s/${slot}#e=${encodeURIComponent(carried)}`);
		await expectEditor(page);
		await expectLive(page);

		await expectLocked(page);
		expect(await storedPass(page, baseURL)).toBeNull();
		// The page left the address as it was.
		expect(await page.evaluate(() => location.hash)).toBe(`#e=${encodeURIComponent(carried)}`);
		// So that the next address is a page load, and not a change of fragment.
		await page.goto('about:blank');
	}
	expect(hellos).toEqual(['', '', '']);

	// Nor at segl's root, which sends the browser on to the slot it used last.
	await page.goto(`./#e=${encodeURIComponent(pass)}`);
	await expect(page).toHaveURL(new URL(`s/${slot}`, baseURL).href);
	await expectEditor(page);
	await expectLive(page);
	await expectLocked(page);
	expect(await storedPass(page, baseURL)).toBeNull();
});

test('a code entered in one tab lets the other tabs of that browser edit', async ({
	page,
	context,
	baseURL
}) => {
	const slot = SLOTS.empty;
	await joinSlot(page, slot);
	await expectLocked(page);
	await page.evaluate(() => {
		(window as unknown as { samePage: boolean }).samePage = true;
	});

	const tab = await context.newPage();
	await joinSlot(tab, SLOTS.tools);
	await accessLink(tab).click();
	await enterCode(tab, ACCESS_CODE);
	await expectEditor(tab);
	await expectUnlocked(tab);

	// The first tab says hello again with the stored pass, and may edit,
	// without a page load.
	await expectUnlocked(page);
	expect(await storedPass(page, baseURL)).toMatch(PASS_SHAPE);
	expect(await page.evaluate(() => (window as unknown as { samePage?: boolean }).samePage)).toBe(
		true
	);
});

test('a browser whose pass the server does not take is told that its access has ended', async ({
	person,
	baseURL
}) => {
	// A pass of the right shape that no code of this segl signed: one from
	// before the site changed its codes or its secret, or one that has ended.
	const stale = '1700000000.AAAAAAAAAAAAAAAAAAAAAAAA';
	const visitor = await person('Vera', { pass: stale });
	const slot = SLOTS.empty;
	await joinSlot(visitor, slot);

	await expectEnded(visitor);
	// It still watches, as any viewer.
	await expect(connectionStatus(visitor)).toHaveText('Live');

	// The same way in: the link, and a code.
	await accessLink(visitor).click();
	await expectAccessPage(visitor, baseURL);
	await enterCode(visitor, ACCESS_CODE);
	await expect(visitor).toHaveURL(new URL(`s/${slot}`, baseURL).href);
	await expectEditor(visitor);
	await expectUnlocked(visitor);
	// The new pass took the place of the old one.
	const pass = await storedPass(visitor, baseURL);
	expect(pass).toMatch(PASS_SHAPE);
	expect(pass).not.toBe(stale);
});

test('a pass stamped now that no code of this segl signed is not taken', async ({ person }) => {
	// Its age is right, so the signature is the one reason to refuse it.
	const forged = `${Math.floor(Date.now() / 1000)}.AAAAAAAAAAAAAAAAAAAAAAAA`;
	expect(forged).toMatch(PASS_SHAPE);
	const visitor = await person('Vera', { pass: forged });
	await joinSlot(visitor, SLOTS.empty);

	await expectEnded(visitor);
});

test('what an earlier build stored as a token is not a pass', async ({ person }) => {
	// The key is the one a token was stored under before access codes (T10).
	const visitor = await person('Vera', { pass: 'S3gl+e2e/Token==' });
	await joinSlot(visitor, SLOTS.empty);

	await expectEnded(visitor);
});

for (const width of [390, 800]) {
	test(`the notice of a locked browser, with its link, stays inside a page ${width} wide`, async ({
		page
	}) => {
		await page.setViewportSize({ width, height: 800 });
		await joinSlot(page, SLOTS.empty);
		await expectLocked(page);

		const widths = await page.evaluate(() => [
			document.documentElement.scrollWidth,
			document.documentElement.clientWidth
		]);
		expect(widths).toEqual([width, width]);
		await expect(notice(page)).toBeVisible();
		const link = (await accessLink(page).boundingBox())!;
		expect(link.x).toBeGreaterThanOrEqual(0);
		expect(link.x + link.width).toBeLessThanOrEqual(width);
	});
}

test('the access page stays inside a narrow page, and asks for nothing outside the mount', async ({
	page,
	baseURL
}) => {
	const traffic = watch(page);
	await page.setViewportSize({ width: 390, height: 800 });

	await page.goto('access');
	await expectAccessPage(page, baseURL);

	const widths = await page.evaluate(() => [
		document.documentElement.scrollWidth,
		document.documentElement.clientWidth
	]);
	expect(widths).toEqual([390, 390]);
	await enterCode(page, 'not one of them');
	await expect(answer(page)).toHaveText(WRONG_CODE);
	expect(
		await page.evaluate(() => [
			document.documentElement.scrollWidth,
			document.documentElement.clientWidth
		])
	).toEqual([390, 390]);
	// Every address it asked for is under segl's root, and none set a cookie.
	await page.waitForLoadState('networkidle');
	expect(traffic.urls.length).toBeGreaterThan(2);
	expect(traffic.urls.filter((url) => !url.startsWith(baseURL!))).toEqual([]);
	expect(traffic.cookies).toEqual([]);

	// The right code, so that the server's count of wrong ones starts again.
	await enterCode(page, ACCESS_CODE);
	await expectEditor(page);
	await expectUnlocked(page);
});
