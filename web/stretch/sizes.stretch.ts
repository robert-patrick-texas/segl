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
 * The size runs of docs/TEST-PLAN.md ("Preliminary sizes"): ten editors on
 * one slot, where two is the gate, and a slot of a thousand elements, which
 * should still load and sync. Each test prints what it measured, on lines
 * that start with `stretch:`. The times are of this machine and its browser,
 * which draws without a GPU.
 *
 * A test fails when the browsers do not end with the same scene. It holds no
 * time to a limit.
 */
import { expect, type Page } from '@playwright/test';
import {
	canvasPeers,
	drawRectangle,
	expectEditor,
	expectLive,
	expectSaved,
	joinSlot,
	presenceCount,
	sceneDocument,
	test
} from '../e2e/pages.ts';

const EDITORS = 10;
const ROUNDS = 3;
/** Ten doublings of one rectangle. */
const DOUBLINGS = 10;
const ELEMENTS = 2 ** DOUBLINGS;

/** The slot each project uses: both run against the one server. */
const SLOTS: Record<string, { editors: number; elements: number }> = {
	direct: { editors: 5, elements: 6 },
	board: { editors: 7, elements: 8 }
};

/** Print one measurement, and keep it with the test's result. */
function note(line: string): void {
	console.log(`stretch: [${test.info().project.name}] ${line}`);
	test.info().annotations.push({ type: 'stretch', description: line });
}

/** The elements on a page's canvas, each as its id, version, and place. */
async function sceneOf(page: Page): Promise<string[]> {
	return (await sceneDocument(page)).elements
		.map((element) => `${element.id} v${element.version} ${element.x},${element.y}`)
		.sort();
}

/** Wait until a page's canvas has this many elements, and return how long that took. */
async function waitForCount(page: Page, count: number, since = Date.now()): Promise<number> {
	await page.waitForFunction(
		(wanted) =>
			window.SEGL_CANVAS !== undefined &&
			(JSON.parse(window.SEGL_CANVAS.document()) as { elements: unknown[] }).elements.length ===
				wanted,
		count,
		{ polling: 50, timeout: 120_000 }
	);
	return Date.now() - since;
}

/** Wait until every page shows the same scene, and return it. */
async function sameScene(pages: Page[]): Promise<string[]> {
	let scene: string[] = [];
	await expect
		.poll(
			async () => {
				const scenes = await Promise.all(pages.map(sceneOf));
				scene = scenes[0]!;
				return scenes.filter((each) => each.join('\n') !== scene.join('\n')).length;
			},
			{ message: 'every browser shows the same scene', timeout: 60_000 }
		)
		.toBe(0);
	return scene;
}

interface StoredScene {
	bytes: number;
	/** The elements that are not deleted. */
	elements: number;
}

async function storedScene(page: Page, slot: number): Promise<StoredScene> {
	const response = await page.request.get(`api/v1/slots/${slot}/scene`);
	const text = await response.text();
	const head = JSON.parse(text) as { scene: { elements: { isDeleted: boolean }[] } };
	return {
		bytes: text.length,
		elements: head.scene.elements.filter((element) => !element.isDeleted).length
	};
}

interface Sent {
	/** How many `elements` messages the page sent. */
	messages: number;
	/** The size of the largest, in characters. */
	largest: number;
}

/** Count the `elements` messages a page sends. Call before `goto`. */
function watchSent(page: Page): Sent {
	const sent: Sent = { messages: 0, largest: 0 };
	page.on('websocket', (socket) => {
		socket.on('framesent', (frame) => {
			const text = String(frame.payload);
			if (!text.startsWith('{"type":"elements"')) return;
			sent.messages += 1;
			sent.largest = Math.max(sent.largest, text.length);
		});
	});
	return sent;
}

/** Read a count, and start it again from nothing. */
function taken(sent: Sent): Sent {
	const was = { ...sent };
	sent.messages = 0;
	sent.largest = 0;
	return was;
}

async function selectEverything(page: Page): Promise<void> {
	await page.locator('[data-testid="toolbar-selection"]').click({ force: true });
	const canvas = (await page.locator('.excalidraw canvas.interactive').boundingBox())!;
	await page.mouse.click(canvas.x + canvas.width - 40, canvas.y + canvas.height - 120);
	await page.keyboard.press('Control+a');
}

test(`${EDITORS} editors draw on one slot at the same time, and every browser ends with the same scene`, async ({
	page,
	person
}) => {
	const slot = SLOTS[test.info().project.name]!.editors;
	const pages = [page];
	for (let index = 1; index < EDITORS; index += 1) pages.push(await person(`Editor${index}`));

	const opened = Date.now();
	await Promise.all(pages.map((each) => joinSlot(each, slot)));
	for (const each of pages) await expect(presenceCount(each)).toHaveText(String(EDITORS));
	note(`${EDITORS} browsers were in the room ${Date.now() - opened} ms after they opened the slot`);

	// Every browser draws a rectangle at the same moment, three times over.
	let drawn = 0;
	for (let round = 0; round < ROUNDS; round += 1) {
		const started = Date.now();
		await Promise.all(
			pages.map((each, index) => drawRectangle(each, -360 + 90 * index, -150 + 100 * round))
		);
		drawn += EDITORS;
		const done = Date.now();
		await Promise.all(pages.map((each) => waitForCount(each, drawn, done)));
		note(
			`round ${round + 1}: ${EDITORS} rectangles took ${done - started} ms to draw, ` +
				`and every browser had all ${drawn} at most ${Date.now() - done} ms later`
		);
	}

	// Every browser draws every other one's pointer.
	for (const each of pages) expect(await canvasPeers(each)).toHaveLength(EDITORS - 1);

	// Every browser moves the rectangle it drew last, twenty steps, all at once.
	const moving = Date.now();
	await Promise.all(
		pages.map(async (each) => {
			for (let step = 0; step < 20; step += 1) await each.keyboard.press('ArrowRight');
		})
	);
	const moved = Date.now();
	const scene = await sameScene(pages);
	expect(scene).toHaveLength(drawn);
	note(
		`${EDITORS * 20} moves took ${moved - moving} ms to make, ` +
			`and every browser showed the same scene at most ${Date.now() - moved} ms later`
	);

	for (const each of pages) await expectSaved(each);
	const stored = await storedScene(page, slot);
	expect(stored.elements).toBe(drawn);
	note(`the stored scene has ${stored.elements} elements in ${stored.bytes} characters`);
});

test(`a slot of ${ELEMENTS} elements loads in a new browser, and an edit still reaches the others`, async ({
	page,
	person
}) => {
	const slot = SLOTS[test.info().project.name]!.elements;
	const watcher = await person('Watcher');
	const late = await person('Late');
	const sent = { page: watchSent(page), watcher: watchSent(watcher), late: watchSent(late) };
	await joinSlot(page, slot);
	await joinSlot(watcher, slot);

	// One rectangle, doubled ten times: select everything, and duplicate it.
	await drawRectangle(page, -100, -100);
	const began = Date.now();
	let slowest = 0;
	for (let count = 2; count <= ELEMENTS; count *= 2) {
		await selectEverything(page);
		const pressed = Date.now();
		await page.keyboard.press('Control+d');
		await waitForCount(page, count, pressed);
		slowest = Math.max(slowest, await waitForCount(watcher, count, pressed));
	}
	note(
		`${ELEMENTS} elements were made in ${DOUBLINGS} doublings in ${Date.now() - began} ms. ` +
			`The slowest doubling was in the other browser ${slowest} ms after the key`
	);
	const growing = taken(sent.page);
	note(
		`the largest elements message of the doublings was ${growing.largest} characters, ` +
			`of ${growing.messages} messages`
	);
	await expectSaved(page);
	const stored = await storedScene(page, slot);
	expect(stored.elements).toBe(ELEMENTS);
	note(`the stored scene has ${stored.elements} elements in ${stored.bytes} characters`);

	// A browser that was not there loads the slot.
	const opened = Date.now();
	await late.goto(`s/${slot}`);
	const loaded = await waitForCount(late, ELEMENTS, opened);
	await expectEditor(late);
	await expectLive(late);
	// A second for anything the page sends back about the scene it was given.
	await late.waitForTimeout(1000);
	const back = taken(sent.late);
	note(
		`a new browser had all ${ELEMENTS} elements ${loaded} ms after it opened the slot, ` +
			`and sent ${back.messages} elements messages of at most ${back.largest} characters about them`
	);

	// One more rectangle, drawn in the late browser, reaches the other two.
	await drawRectangle(late, 250, 150);
	const one = Date.now();
	await Promise.all([page, watcher].map((each) => waitForCount(each, ELEMENTS + 1, one)));
	const edit = taken(sent.late);
	note(
		`one rectangle drawn on the loaded slot was in the other two browsers at most ` +
			`${Date.now() - one} ms later, in ${edit.messages} messages of at most ${edit.largest} characters`
	);

	// Every element moved at once, in the watcher's browser.
	taken(sent.watcher);
	await selectEverything(watcher);
	const nudged = Date.now();
	await watcher.keyboard.press('ArrowRight');
	const scene = await sameScene([watcher, page, late]);
	expect(scene).toHaveLength(ELEMENTS + 1);
	const all = taken(sent.watcher);
	note(
		`a move of all ${ELEMENTS + 1} elements showed the same in three browsers at most ` +
			`${Date.now() - nudged} ms later, in ${all.messages} messages of at most ${all.largest} characters`
	);

	for (const each of [page, watcher, late]) await expectSaved(each);
	expect((await storedScene(page, slot)).elements).toBe(ELEMENTS + 1);
});
