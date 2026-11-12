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
 * A slot's history in the bar (S-005, docs/TEST-PLAN.md T-011): the revisions
 * are listed, an older one is restored for every browser on the slot, and
 * the scene it replaced can be restored in its turn.
 *
 * `tests/test_history.py` holds the routes, the edit gate, the 51st revision,
 * and a restore across a kill of the server.
 */
import { expect, type APIRequestContext, type Page } from '@playwright/test';
import {
	connectionStatus,
	drawRectangle,
	elementIds,
	elementOf,
	expectSaved,
	historyControl,
	joinSlot,
	mountOf,
	openHistory,
	restoreRow,
	SLOTS,
	test,
	type SceneElement
} from './pages.ts';

interface Revision {
	revision: number;
	epoch: number;
	authorLabel: string;
	createdAt: string;
}

/** The slot's history as the server lists it, newest first. */
async function revisions(request: APIRequestContext, slot: number): Promise<Revision[]> {
	const response = await request.get(`api/v1/slots/${slot}/revisions`);
	expect(response.status()).toBe(200);
	return ((await response.json()) as { revisions: Revision[] }).revisions;
}

/** The elements of one stored revision that are not deleted. */
async function revisionElements(
	request: APIRequestContext,
	slot: number,
	revision: number
): Promise<SceneElement[]> {
	const response = await request.get(`api/v1/slots/${slot}/revisions/${revision}`);
	expect(response.status()).toBe(200);
	const body = (await response.json()) as { scene: { elements: SceneElement[] } };
	return body.scene.elements.filter((element) => !element.isDeleted);
}

async function slotEpoch(request: APIRequestContext, slot: number): Promise<number> {
	return ((await (await request.get(`api/v1/slots/${slot}`)).json()) as { epoch: number }).epoch;
}

/**
 * Draw a rectangle that gets a history row of its own, and return its id and
 * that row. The server keeps at most one row a second while people draw
 * (docs/DATA-MODEL.md, flush rules), so the drawing waits until the newest
 * row is older than that.
 */
async function drawRevision(
	page: Page,
	request: APIRequestContext,
	slot: number,
	dx: number,
	dy: number
): Promise<{ id: string; revision: number }> {
	await page.waitForTimeout(1100);
	const id = await drawRectangle(page, dx, dy);
	await expectSaved(page);
	const [newest] = await revisions(request, slot);
	expect(await revisionElements(request, slot, newest!.revision)).toContainEqual(
		expect.objectContaining({ id })
	);
	return { id, revision: newest!.revision };
}

test('an older version is restored in every browser, and the one it replaced comes back', async ({
	page,
	person,
	request,
	baseURL
}) => {
	// T-011.
	const slot = SLOTS.history;
	const { basePath } = mountOf(baseURL);
	const other = await person('Bea');
	await joinSlot(page, slot);
	await joinSlot(other, slot);
	const epoch = await slotEpoch(request, slot);

	// More than one revision: the first rectangle, and then both.
	const first = await drawRevision(page, request, slot, -250, -150);
	const second = await drawRevision(other, request, slot, 250, -150);
	expect(second.revision).toBeGreaterThan(first.revision);
	await expect.poll(() => elementIds(page)).toContain(second.id);
	const older = await revisionElements(request, slot, first.revision);
	expect(older.map((element) => element.id)).not.toContain(second.id);
	const before = (await elementOf(other, second.id))!;

	// The list, and the restore, are asked for under the mount.
	const listed = page.waitForRequest((asked) => asked.url().endsWith('/revisions'));
	const rows = await openHistory(page);
	expect(new URL((await listed).url()).pathname).toBe(`${basePath}api/v1/slots/${slot}/revisions`);
	const restored = page.waitForRequest((asked) => asked.url().endsWith('/restore'));
	await restoreRow(rows.and(page.locator(`[data-revision="${first.revision}"]`)));
	const sent = await restored;
	expect(new URL(sent.url()).pathname).toBe(`${basePath}api/v1/slots/${slot}/restore`);
	expect(sent.postDataJSON()).toEqual({ revision: first.revision, displayName: 'Tester' });

	// Every connected browser switches to that scene: the later rectangle is
	// gone from both, and the first is the copy the revision held.
	const kept = older.find((element) => element.id === first.id)!;
	for (const browser of [page, other]) {
		await expect.poll(() => elementIds(browser)).not.toContain(second.id);
		expect(await elementOf(browser, first.id)).toMatchObject({ version: kept.version, x: kept.x });
		await expect(connectionStatus(browser)).toHaveAttribute('data-state', /^(live|saved)$/);
	}
	expect(await slotEpoch(request, slot)).toBe(epoch + 1);
	// The open list read itself again. The restore is its newest row, by
	// whoever restored, and the row under it is the scene that was replaced.
	await expect(rows.first()).toHaveAttribute('data-epoch', String(epoch + 1));
	await expect(rows.first()).toContainText('Tester');
	await expect(rows.first()).toContainText('replacement');
	const replaced = Number(await rows.nth(1).getAttribute('data-revision'));
	expect(replaced).toBeGreaterThanOrEqual(second.revision);
	expect(await revisionElements(request, slot, replaced)).toContainEqual(
		expect.objectContaining({ id: second.id, version: before.version })
	);

	// A browser that opens the slot now starts from the restored scene.
	const late = await person('Cy');
	await joinSlot(late, slot);
	await expect.poll(() => elementIds(late)).toContain(first.id);
	expect(await elementIds(late)).not.toContain(second.id);

	// The second browser restores the revision from before the restore, and
	// the later drawing returns, as it was.
	const theirs = await openHistory(other);
	await expect(theirs.first()).toHaveAttribute('data-epoch', String(epoch + 1));
	await restoreRow(theirs.and(other.locator(`[data-revision="${replaced}"]`)));
	for (const browser of [page, other, late]) {
		await expect
			.poll(() => elementOf(browser, second.id))
			.toMatchObject({
				version: before.version,
				x: before.x
			});
		expect(await elementIds(browser)).toContain(first.id);
	}
	expect(await slotEpoch(request, slot)).toBe(epoch + 2);
	await expect(theirs.first()).toContainText('Bea');
	await expect(rows.first()).toHaveAttribute('data-epoch', String(epoch + 2));

	// Drawing goes on, and is saved, on the scene that came back.
	await page.keyboard.press('Escape');
	await expect(historyControl(page).getByRole('group')).toHaveCount(0);
	const third = await drawRectangle(page, 0, 200);
	await expectSaved(page);
	await expect.poll(() => elementIds(other)).toContain(third);
	const head = (await (await request.get(`api/v1/slots/${slot}/scene`)).json()) as {
		epoch: number;
		scene: { elements: SceneElement[] };
	};
	expect(head.epoch).toBe(epoch + 2);
	expect(head.scene.elements.map((element) => element.id)).toEqual(
		expect.arrayContaining([first.id, second.id, third])
	);
});

test('the history lists who drew and when, newest first, and a restore takes two presses', async ({
	page,
	request
}) => {
	const slot = SLOTS.history;
	await joinSlot(page, slot);
	// Two revisions of this test's own: one row has no order.
	const earlier = await drawRevision(page, request, slot, -250, 40);
	const drawn = await drawRevision(page, request, slot, -250, 120);
	const stored = await revisions(request, slot);
	const epoch = await slotEpoch(request, slot);

	const button = historyControl(page).getByRole('button', { name: 'History' });
	await expect(button).toHaveAttribute('aria-expanded', 'false');
	const rows = await openHistory(page);
	await expect(button).toHaveAttribute('aria-expanded', 'true');

	// The server's rows, in its order: newest first.
	await expect(rows).toHaveCount(stored.length);
	const shown = await rows.evaluateAll((items) =>
		items.map((item) => Number(item.getAttribute('data-revision')))
	);
	expect(shown).toEqual(stored.map((row) => row.revision));
	expect(shown.indexOf(drawn.revision)).toBeLessThan(shown.indexOf(earlier.revision));
	const newest = rows.first();
	await expect(newest).toHaveAttribute('data-revision', String(drawn.revision));
	await expect(newest).toContainText('Tester');
	await expect(newest.locator('time')).toHaveAttribute('datetime', stored[0]!.createdAt);
	await expect(newest.locator('time')).toHaveText(/\d{1,2}:\d{2}:\d{2}/);

	// The first press asks. Cancel leaves everything as it was.
	await newest.getByRole('button', { name: /^Restore the version of / }).click();
	await expect(newest).toContainText('Replace the canvas for everyone?');
	await newest.getByRole('button', { name: 'Cancel' }).click();
	await expect(newest).not.toContainText('Replace the canvas');
	expect(await slotEpoch(request, slot)).toBe(epoch);
	expect(await revisions(request, slot)).toEqual(stored);
	expect(await elementIds(page)).toContain(drawn.id);

	// Escape closes the list, and so does a press on the canvas.
	await page.keyboard.press('Escape');
	await expect(historyControl(page).getByRole('group')).toHaveCount(0);
	await openHistory(page);
	const canvas = (await page.locator('.excalidraw canvas.interactive').boundingBox())!;
	await page.mouse.click(canvas.x + canvas.width - 120, canvas.y + canvas.height - 160);
	await expect(historyControl(page).getByRole('group')).toHaveCount(0);
	await expect(button).toHaveAttribute('aria-expanded', 'false');
});

test('a slot nobody has drawn on has no versions to restore', async ({ page }) => {
	await joinSlot(page, SLOTS.empty);

	const rows = await openHistory(page);

	await expect(rows).toHaveCount(0);
	await expect(historyControl(page)).toContainText('No versions yet.');
	await expect(historyControl(page).getByRole('button', { name: /Restore/ })).toHaveCount(0);
});

test('a version that is no longer kept says so, and the list is read again', async ({
	page,
	request
}) => {
	const slot = SLOTS.history;
	await joinSlot(page, slot);
	await drawRevision(page, request, slot, 250, 120);
	const epoch = await slotEpoch(request, slot);
	// What the server answers for a revision that newer ones have pushed out
	// since the list was read. Filling a history takes 50 revisions, so the
	// answer is put in the server's place.
	await page.route('**/api/v1/slots/*/restore', (route) =>
		route.fulfill({
			status: 404,
			contentType: 'application/json',
			body: JSON.stringify({ error: 'revision_not_found', message: 'No such revision.' })
		})
	);
	const rows = await openHistory(page);
	const readAgain = page.waitForRequest((asked) => asked.url().endsWith('/revisions'));

	await restoreRow(rows.first());

	await expect(historyControl(page).getByRole('alert')).toHaveText(
		'That version is no longer kept.'
	);
	await readAgain;
	await expect(historyControl(page).getByRole('group')).toHaveAttribute('data-state', 'ready');
	// Nothing was restored, and the canvas is as it was.
	expect(await slotEpoch(request, slot)).toBe(epoch);
	await expect(connectionStatus(page)).toHaveAttribute('data-state', /^(live|saved)$/);
});

test('the open history stays inside a narrow page', async ({ page }) => {
	// The list hangs from its button, which a narrow bar puts far to the right.
	await page.setViewportSize({ width: 390, height: 800 });
	await joinSlot(page, SLOTS.history);

	await openHistory(page);

	const panel = (await historyControl(page).getByRole('group').boundingBox())!;
	const button = (await historyControl(page)
		.getByRole('button', { name: 'History' })
		.boundingBox())!;
	expect(panel.x).toBeGreaterThanOrEqual(0);
	expect(panel.x + panel.width).toBeLessThanOrEqual(390);
	// Under its button, and moved left of it to fit.
	expect(panel.y).toBeGreaterThanOrEqual(button.y + button.height);
	expect(panel.x).toBeLessThan(button.x);
	// The page did not gain a sideways scroll.
	expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
});
