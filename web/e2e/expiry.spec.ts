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
 * A pass that ends (S-008, D2-033; docs/TEST-PLAN.md T-019): after
 * `access_pass_hours`, the person enters a code again.
 *
 * This spec is in the `restart` project, beside `durability.spec.ts`. Each
 * test has a segl of its own (`server.ts`), whose passes last seconds, on a
 * port no other project uses.
 */
import { expect, type Page } from '@playwright/test';
import {
	drawRectangle,
	elementIds,
	expectEditor,
	expectLive,
	expectSaved,
	joinSlot,
	passKey,
	test as base
} from './pages.ts';
import { RestartableServer } from './server.ts';
import { ACCESS_CODE, ACCESS_SECRET, PASS_SHAPE } from './sites.ts';

/** How long a pass of this server lasts: 0.004 hours. */
const PASS_SECONDS = 14.4;

const test = base.extend<{ server: RestartableServer }>({
	server: async ({ baseURL }, use) => {
		const server = new RestartableServer(baseURL!, [
			`access_codes = [${JSON.stringify(ACCESS_CODE)}]`,
			`access_secret = ${JSON.stringify(ACCESS_SECRET)}`,
			'access_pass_hours = 0.004'
		]);
		try {
			await server.start();
			await use(server);
		} finally {
			await server.remove();
		}
	}
});

function notice(page: Page) {
	return page.locator('header.segl-bar .segl-bar__notice');
}

function accessLink(page: Page) {
	return notice(page).getByRole('link', { name: 'Enter access code' });
}

function rectangleTool(page: Page) {
	return page.locator('[data-testid="toolbar-rectangle"]');
}

/** Follow the bar's link, enter the code, and return when the server said the pass ends. */
async function enterCode(page: Page): Promise<number> {
	await accessLink(page).click();
	const answered = page.waitForResponse(
		(response) => response.url().endsWith('/api/v1/access') && response.status() === 200
	);
	await page.getByRole('textbox', { name: 'Access code' }).fill(ACCESS_CODE);
	await page.keyboard.press('Enter');
	const body = (await (await answered).json()) as { pass: string; expiresAt: string };
	expect(body.pass).toMatch(PASS_SHAPE);
	return Date.parse(body.expiresAt);
}

async function storedHead(page: Page, slot: number): Promise<string[]> {
	const head = (await (await page.request.get(`api/v1/slots/${slot}/scene`)).json()) as {
		scene: { elements: { id: string }[] };
	};
	return head.scene.elements.map((each) => each.id);
}

test('a pass ends, the browser is told so, and a code entered again lets it edit', async ({
	server,
	page,
	person,
	baseURL
}) => {
	test.setTimeout(90_000);
	void server;
	const slot = 2;
	const watcher = await person('Wim');
	await joinSlot(page, slot);
	await joinSlot(watcher, slot);
	await expect(notice(page)).toHaveAttribute('data-editing', 'locked');

	const issuedAt = Date.now();
	const endsAt = await enterCode(page);
	// The server said when: its setting from the second the pass was stamped
	// with, which is up to a second before the answer.
	expect(endsAt - issuedAt).toBeGreaterThan((PASS_SECONDS - 2) * 1000);
	expect(endsAt - issuedAt).toBeLessThanOrEqual(PASS_SECONDS * 1000 + 500);
	await expect(page).toHaveURL(new URL(`s/${slot}`, baseURL).href);
	await expectEditor(page);
	await expectLive(page);
	await expect(notice(page)).toHaveAttribute('data-editing', 'unlocked');
	const first = await page.evaluate((key) => localStorage.getItem(key), passKey(baseURL));

	// While the pass lasts, the browser edits, and the watcher sees it.
	const drawn = await drawRectangle(page, -200, -100);
	await expectSaved(page);
	await expect.poll(() => elementIds(watcher)).toContain(drawn);
	expect(Date.now()).toBeLessThan(endsAt);

	// The pass ends with the socket still open. Nothing says so until the
	// browser next sends an edit, which the server refuses.
	await page.waitForTimeout(Math.max(0, endsAt - Date.now()) + 500);
	await expect(notice(page)).toHaveAttribute('data-editing', 'unlocked');
	const refused = await drawRectangle(page, 0, -100);

	await expect(notice(page)).toHaveAttribute('data-editing', 'refused');
	await expect(notice(page)).toContainText(
		'Editing is locked: the access this browser had has ended.'
	);
	await expect(accessLink(page)).toBeVisible();
	await expect(rectangleTool(page)).toHaveCount(0);
	// What was drawn after the end reached nobody, and is not stored.
	await watcher.waitForTimeout(700);
	expect(await elementIds(watcher)).not.toContain(refused);
	expect(await storedHead(page, slot)).toEqual([drawn]);
	// A reload shows the same: the stored pass is still the one that ended.
	await page.reload();
	await expectEditor(page);
	await expectLive(page);
	await expect(notice(page)).toHaveAttribute('data-editing', 'refused');
	expect(await elementIds(page)).toEqual([drawn]);

	// The person enters a code again, and edits again.
	await enterCode(page);
	await expect(page).toHaveURL(new URL(`s/${slot}`, baseURL).href);
	await expectEditor(page);
	await expectLive(page);
	await expect(notice(page)).toHaveAttribute('data-editing', 'unlocked');
	const second = await page.evaluate((key) => localStorage.getItem(key), passKey(baseURL));
	expect(second).toMatch(PASS_SHAPE);
	expect(second).not.toBe(first);
	const again = await drawRectangle(page, 200, -100);
	await expectSaved(page);
	await expect.poll(() => elementIds(watcher)).toContain(again);
	expect(await storedHead(page, slot)).toEqual([drawn, again]);
});
