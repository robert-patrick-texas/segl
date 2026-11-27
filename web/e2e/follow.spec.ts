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
 * Follow mode, and the others' cursors in Diagram mode (T18; docs/TEST-PLAN.md
 * T-025 and T-026). A person presses a name in the bar's list of who is here
 * and follows that person's view, on a whiteboard and on slot 9, where each
 * take of the pen starts the others following the holder. Following ends when
 * the follower scrolls, zooms, or clicks themselves.
 *
 * The two browsers of a test have the same size of window, so the follower's
 * view is the leader's, to the pixel.
 */
import { expect, type Page } from '@playwright/test';
import { drawio, openDiagram } from './diagram.ts';
import { joinSlot, openPeople, SLOTS, test } from './pages.ts';

interface BoardView {
	scrollX: number;
	scrollY: number;
	zoom: number;
	width: number;
	height: number;
}

interface Area {
	x: number;
	y: number;
	width: number;
	height: number;
	page: string | null;
}

async function boardView(page: Page): Promise<BoardView> {
	return JSON.parse(await page.evaluate(() => window.SEGL_CANVAS!.view())) as BoardView;
}

function boardArea({ scrollX, scrollY, zoom, width, height }: BoardView): Area {
	return { x: -scrollX, y: -scrollY, width: width / zoom, height: height / zoom, page: null };
}

/**
 * Whether a follower's area fits a leader's: all of it, centred, and the
 * leader's width or height exactly, to a pixel of the follower's screen. A
 * follow fits the leader's area whatever the two canvases' sizes, so their
 * bars may differ. Otherwise what is off, in pixels.
 */
function fits(follower: Area, leader: Area, scale: number): string {
	const centre =
		Math.max(
			Math.abs(follower.x + follower.width / 2 - (leader.x + leader.width / 2)),
			Math.abs(follower.y + follower.height / 2 - (leader.y + leader.height / 2))
		) * scale;
	// The tighter side's room to spare, and a side too short to hold the leader's.
	const spare =
		Math.abs(Math.min(follower.width - leader.width, follower.height - leader.height)) * scale;
	const short = Math.max(leader.width - follower.width, leader.height - follower.height, 0) * scale;
	if (follower.page !== leader.page) return `on page ${follower.page}, not ${leader.page}`;
	const off = { centre, spare, short };
	return Object.values(off).every((value) => value <= 1) ? 'fits' : JSON.stringify(off);
}

async function boardFits(follower: Page, leader: Page): Promise<string> {
	const [mine, theirs] = await Promise.all([boardView(follower), boardView(leader)]);
	return fits(boardArea(mine), boardArea(theirs), mine.zoom);
}

async function area(page: Page): Promise<Area> {
	return JSON.parse(await page.evaluate(() => window.SEGL_DIAGRAM!.view())) as Area;
}

async function frameFits(follower: Page, leader: Page): Promise<string> {
	const [mine, theirs] = await Promise.all([area(follower), area(leader)]);
	const width = await drawio(follower)
		.locator('.geDiagramContainer')
		.evaluate((el) => el.clientWidth);
	return fits(mine, theirs, width / mine.width);
}

/** What `read` says once it stops changing: the same twice, 300 ms apart. */
async function settled<T>(page: Page, read: () => Promise<T>): Promise<T> {
	let before = JSON.stringify(await read());
	for (let tries = 0; tries < 20; tries += 1) {
		await page.waitForTimeout(300);
		const now = JSON.stringify(await read());
		if (now === before) return JSON.parse(now) as T;
		before = now;
	}
	throw new Error('the view did not settle');
}

/** Press a name in the bar's list of who is here. */
async function press(page: Page, name: string): Promise<void> {
	const people = await openPeople(page);
	await people.filter({ hasText: name }).getByRole('button').click();
}

/** The editor's own sign of a follow, on a whiteboard. */
function badge(page: Page) {
	return page.locator('.excalidraw .follow-mode__badge');
}

/** The bar's sign of a follow, on slot 9. */
function following(page: Page) {
	return page.locator('header.segl-bar .segl-bar__following');
}

async function overCanvas(page: Page): Promise<void> {
	const canvas = (await page.locator('.excalidraw canvas.interactive').boundingBox())!;
	await page.mouse.move(canvas.x + 640, canvas.y + 400);
}

async function overDiagram(page: Page): Promise<{ x: number; y: number }> {
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
async function zoomDiagram(page: Page, deltaY: number): Promise<void> {
	await overDiagram(page);
	await page.keyboard.down('Control');
	await page.mouse.wheel(0, deltaY);
	await page.keyboard.up('Control');
}

test.describe('on a whiteboard', () => {
	test('a follower’s view matches the leader’s as the leader scrolls and zooms', async ({
		page,
		person
	}) => {
		const leader = await person('Bea');
		await joinSlot(page, SLOTS.follow);
		await joinSlot(leader, SLOTS.follow);

		await press(page, 'Bea');
		await expect(badge(page)).toHaveText(/Following\s*Bea/);
		await expect(await openPeople(page)).toContainText(['Beafollowing']);
		await page.keyboard.press('Escape');

		await overCanvas(leader);
		await leader.mouse.wheel(180, 260);
		await leader.locator('.zoom-in-button').click();
		await leader.locator('.zoom-in-button').click();
		expect((await boardView(leader)).zoom).toBeGreaterThan(1.1);
		await expect.poll(() => boardFits(page, leader)).toBe('fits');
		await expect(badge(page)).toBeVisible();
	});

	test('the follower scrolls, and the follow ends', async ({ page, person }) => {
		const leader = await person('Bea');
		await joinSlot(page, SLOTS.follow);
		await joinSlot(leader, SLOTS.follow);
		await press(page, 'Bea');
		await expect(badge(page)).toBeVisible();

		await overCanvas(page);
		await page.mouse.wheel(0, 300);
		await expect(badge(page)).toBeHidden();
		const mine = await settled(page, () => boardView(page));

		await overCanvas(leader);
		await leader.mouse.wheel(0, -500);
		// Give a view time to arrive, were one still sent.
		await leader.waitForTimeout(600);
		expect(await boardView(page)).toEqual(mine);
		await expect(await openPeople(page)).not.toContainText(['Beafollowing']);
	});

	test('pressing the name again, or the editor’s own stop, ends the follow', async ({
		page,
		person
	}) => {
		const leader = await person('Bea');
		await joinSlot(page, SLOTS.follow);
		await joinSlot(leader, SLOTS.follow);

		await press(page, 'Bea');
		await expect(badge(page)).toBeVisible();
		await press(page, 'Bea');
		await expect(badge(page)).toBeHidden();

		await press(page, 'Bea');
		await expect(badge(page)).toBeVisible();
		await badge(page).getByRole('button').click();
		await expect(badge(page)).toBeHidden();
		await expect(await openPeople(page)).not.toContainText(['Beafollowing']);
	});

	test('the leader leaves, and the follow ends', async ({ page, person }) => {
		const leader = await person('Bea');
		await joinSlot(page, SLOTS.follow);
		await joinSlot(leader, SLOTS.follow);
		await press(page, 'Bea');
		await expect(badge(page)).toBeVisible();

		await leader.close();

		await expect(badge(page)).toBeHidden();
		await expect(await openPeople(page)).toHaveText(['Testeryou']);
	});
});

test.describe('on slot 9', () => {
	test('a take of the pen starts a follow of the holder, who leads until the watcher looks away', async ({
		page,
		person
	}) => {
		const holder = await person('Bea');
		await openDiagram(page);
		await openDiagram(holder);

		await holder.getByRole('button', { name: 'Take pen' }).click();
		await expect(following(page)).toHaveText(/Following Bea/);

		// The holder scrolls and zooms, and the watcher's view matches.
		await overDiagram(holder);
		await holder.mouse.wheel(120, 240);
		await zoomDiagram(holder, -300);
		await expect.poll(() => frameFits(page, holder)).toBe('fits');

		// The holder turns to a new page of the diagram, and the watcher with them.
		const before = (await area(holder)).page;
		await drawio(holder).locator('.geControlTab[title="Insert Page"]').click();
		await expect.poll(async () => (await area(holder)).page).not.toBe(before);
		await expect.poll(() => frameFits(page, holder)).toBe('fits');

		// The watcher scrolls away and stays away.
		await overDiagram(page);
		await page.mouse.wheel(0, 400);
		await expect(following(page)).toBeHidden();
		const mine = await settled(page, () => area(page));
		await overDiagram(holder);
		await holder.mouse.wheel(0, -300);
		await holder.waitForTimeout(600);
		expect(await area(page)).toEqual(mine);

		// A press of the holder's name follows again.
		await press(page, 'Bea');
		await expect(following(page)).toHaveText(/Following Bea/);
		await expect.poll(() => frameFits(page, holder)).toBe('fits');

		// Giving the pen back ends the follow it started.
		await holder.getByRole('button', { name: 'Give pen back' }).click();
		await expect(following(page)).toBeHidden();
	});

	test('the bar’s stop ends a follow', async ({ page, person }) => {
		const leader = await person('Bea');
		await openDiagram(page);
		await openDiagram(leader);

		await press(page, 'Bea');
		await expect(following(page)).toHaveText(/Following Bea/);
		await following(page).click();
		await expect(following(page)).toBeHidden();
	});
});

test.describe('cursors on slot 9', () => {
	/** Where a frame shows a point of the diagram, on the screen. */
	async function onScreen(page: Page, point: { x: number; y: number }) {
		const container = drawio(page).locator('.geDiagramContainer');
		const box = (await container.boundingBox())!;
		const width = await container.evaluate((el) => el.clientWidth);
		const view = await area(page);
		const scale = width / view.width;
		return { x: box.x + (point.x - view.x) * scale, y: box.y + (point.y - view.y) * scale };
	}

	/** The point of the diagram at this place on a frame's screen. */
	async function onDiagram(page: Page, place: { x: number; y: number }) {
		const container = drawio(page).locator('.geDiagramContainer');
		const box = (await container.boundingBox())!;
		const width = await container.evaluate((el) => el.clientWidth);
		const view = await area(page);
		const scale = width / view.width;
		return { x: view.x + (place.x - box.x) / scale, y: view.y + (place.y - box.y) / scale };
	}

	test('each browser shows the other’s cursor with its name, on the point under the other’s pointer', async ({
		page,
		person
	}) => {
		const other = await person('Bea');
		await openDiagram(page);
		await openDiagram(other);

		// The two look at the diagram at different scales and scrolls: two
		// steps in, around a point off the centre. Under the tests' Windows
		// browser drawio also zooms on a plain wheel, so none follows.
		await zoomDiagram(page, -400);
		await zoomDiagram(page, -400);
		const scaleOf = async (browser: Page) => {
			const width = await drawio(browser)
				.locator('.geDiagramContainer')
				.evaluate((el) => el.clientWidth);
			return width / (await settled(browser, () => area(browser))).width;
		};
		const [mine, theirs] = await Promise.all([scaleOf(page), scaleOf(other)]);
		expect(Math.abs(mine / theirs - 1)).toBeGreaterThan(0.2);

		for (const [mover, watcher, name] of [
			[other, page, 'Bea'],
			[page, other, 'Tester']
		] as const) {
			const place = await overDiagram(mover);
			await mover.mouse.move(place.x - 37, place.y + 23);
			const point = await onDiagram(mover, { x: place.x - 37, y: place.y + 23 });
			const cursor = drawio(watcher).locator('.segl-cursor');
			await expect(cursor).toBeVisible();
			await expect(cursor.locator('.segl-cursor__name')).toHaveText(name);
			const expected = await onScreen(watcher, point);
			await expect
				.poll(async () => {
					const box = (await cursor.boundingBox())!;
					return [
						Math.round(Math.abs(box.x - expected.x)),
						Math.round(Math.abs(box.y - expected.y))
					];
				})
				.toEqual([0, 0]);
		}
	});

	test('a cursor on another page of the diagram does not show, and one who leaves takes theirs', async ({
		page,
		person
	}) => {
		const other = await person('Bea');
		await openDiagram(page);
		await openDiagram(other);
		const cursor = drawio(page).locator('.segl-cursor');

		await overDiagram(other);
		await expect(cursor).toBeVisible();

		// The other adds a page, which drawio turns to in their frame alone.
		const first = (await area(other)).page;
		await drawio(other).locator('.geControlTab[title="Insert Page"]').click();
		await expect.poll(async () => (await area(other)).page).not.toBe(first);
		const place = await overDiagram(other);
		await other.mouse.move(place.x + 15, place.y + 15);
		await expect(cursor).toBeHidden();

		await other.close();
		await expect(cursor).toHaveCount(0);
	});
});
