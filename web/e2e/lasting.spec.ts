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
 * History that lasts, and clearing a slot (S-005, S-020; docs/TEST-PLAN.md
 * T-023). A board deleted by mistake comes back from History after newer
 * versions have passed the count, and a slot cleared while segl is stopped
 * is empty in the browser that stayed open on it.
 *
 * This spec is in the `restart` project. Each test has a segl of its own
 * (`server.ts`). The first keeps 5 revisions, where a site keeps 50: the rule
 * is the same, and drawing 50 takes a minute. `tests/test_retention.py` and
 * `tests/test_clear.py` hold the rules.
 */
import { expect, type Page } from '@playwright/test';
import {
	connectionStatus,
	drawRectangle,
	elementIds,
	expectLive,
	expectSaved,
	historyControl,
	joinSlot,
	openHistory,
	restoreRow,
	test as base
} from './pages.ts';
import { RestartableServer } from './server.ts';

const LIMIT = 5;
const SLOT = 2;

const test = base.extend<{ server: RestartableServer }>({
	server: async ({ baseURL }, use) => {
		const server = new RestartableServer(baseURL!, [`history_limit = ${LIMIT}`]);
		try {
			await server.start();
			await use(server);
		} finally {
			await server.remove();
		}
	}
});

/**
 * Draw a rectangle that gets a revision of its own. The server keeps at most
 * one a second while people draw, so the drawing waits a second first.
 */
async function drawRevision(page: Page, dx: number, dy: number): Promise<string> {
	await page.waitForTimeout(1100);
	const id = await drawRectangle(page, dx, dy);
	await expectSaved(page);
	return id;
}

function title(page: Page) {
	return page.getByRole('heading', { level: 1 });
}

test('a board deleted by mistake comes back from History after newer versions pass the count', async ({
	page,
	person,
	server
}) => {
	expect(server.url).toBeTruthy();
	const other = await person('Bea');
	await joinSlot(page, SLOT);
	await joinSlot(other, SLOT);
	const board = [
		await drawRectangle(page, -300, -150),
		await drawRectangle(page, -300, 0),
		await drawRectangle(page, -300, 150)
	];
	await expectSaved(page);
	await expect.poll(() => elementIds(other)).toEqual(expect.arrayContaining(board));

	// Everything selected and deleted, as a slip of the keyboard does it.
	await page.keyboard.press('Control+a');
	await page.keyboard.press('Delete');
	await expect.poll(() => elementIds(page)).toEqual([]);
	await expectSaved(page);
	// More versions than the slot keeps by count, each a second apart.
	const later: string[] = [];
	for (let step = 0; step <= LIMIT; step += 1) {
		later.push(await drawRevision(other, 100 + 60 * step, -200));
	}

	const rows = await openHistory(page);
	const kept = rows.filter({ has: page.locator('[data-kept="delete"]') });
	await expect(kept).toHaveCount(1);
	await expect(kept.locator('[data-kept]')).toHaveText('Before delete');
	// Below the newest five: only its mark keeps it.
	const numbers = await rows.evaluateAll((items) =>
		items.map((item) => Number(item.getAttribute('data-revision')))
	);
	const mine = Number(await kept.getAttribute('data-revision'));
	expect(numbers.indexOf(mine)).toBeGreaterThanOrEqual(LIMIT);

	await restoreRow(kept);

	// The board is back in both browsers, and what came after it is gone.
	for (const browser of [page, other]) {
		await expect.poll(() => elementIds(browser)).toEqual(expect.arrayContaining(board));
		expect((await elementIds(browser)).filter((id) => later.includes(id))).toEqual([]);
		await expect(connectionStatus(browser)).toHaveAttribute('data-state', /^(live|saved)$/);
	}
	// The board it replaced is kept in its turn.
	const after = await openHistory(other);
	await expect(after.first().locator('[data-kept]')).toHaveCount(0);
	await expect(after.nth(1).locator('[data-kept="restore"]')).toHaveText('Before restore');
});

test('a slot cleared while segl is stopped is empty in the browser that stayed open', async ({
	page,
	request,
	server
}) => {
	await joinSlot(page, SLOT);
	const drawn = await drawRectangle(page, 0, 0);
	await expectSaved(page);
	expect((await request.patch(`api/v1/slots/${SLOT}`, { data: { title: 'Workshop' } })).ok()).toBe(
		true
	);
	await expect(title(page)).toHaveText('Workshop');

	await server.stop();
	await expect(connectionStatus(page)).toHaveText('Disconnected');
	const cleared = server.clearSlots([SLOT]);
	expect(cleared.status, cleared.output).toBe(0);
	expect(cleared.output).toContain(`Cleared slot ${SLOT}. It is empty, at epoch 2.`);
	await server.start();

	// The page finds the server again by itself, and takes the empty board.
	await expectLive(page);
	await expect.poll(() => elementIds(page)).toEqual([]);
	await expect(title(page)).toHaveText(`Workspace ${SLOT}`);
	// It did not send its old board back: the server holds none of it.
	await page.waitForTimeout(500);
	const stored = await (await request.get(`api/v1/slots/${SLOT}/scene`)).json();
	expect(stored.epoch).toBe(2);
	expect(stored.scene.elements).toEqual([]);
	await openHistory(page);
	await expect(historyControl(page)).toContainText('No versions yet.');

	await page.reload();
	await joinSlot(page, SLOT);
	expect(await elementIds(page)).not.toContain(drawn);
	expect(await elementIds(page)).toEqual([]);
});
