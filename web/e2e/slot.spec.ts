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
 * The slot page: the editor inside the segl bar (S-001), the shared notice
 * (S-016), and the navigation rules (D2-006). Each test runs at a host root
 * and at `/board/`.
 */
import { expect } from '@playwright/test';
import { readProjectVersion } from '../scripts/app-version.ts';
import {
	drawRectangle,
	elementIds,
	elementOf,
	expectEditor,
	expectLive,
	joinSlot,
	mountOf,
	openSlot,
	sceneDocument,
	SLOTS,
	test,
	tokenKey
} from './pages.ts';

const VERSION = readProjectVersion(new URL('../../versions.toml', import.meta.url));

test('a slot shows the editor under the segl bar', async ({ page }) => {
	await openSlot(page, 's/1');

	const bar = page.locator('header.segl-bar');
	await expect(bar.getByRole('heading', { level: 1 })).toHaveText('Workspace 1');
	await expect(bar.getByRole('navigation', { name: 'Slots' }).getByRole('link')).toHaveText([
		'1',
		'2',
		'3',
		'4',
		'5',
		'6',
		'7',
		'8',
		'9'
	]);
	await expect(bar.getByRole('link', { name: 'Slot 1: Workspace 1' })).toHaveAttribute(
		'aria-current',
		'page'
	);
	await expect(bar.getByTestId('presence')).toBeAttached();
	await expect(bar.getByText(`segl ${VERSION}`)).toBeVisible();
	await expect(page).toHaveTitle('Workspace 1 · segl');

	// The bar is outside the canvas: the editor starts where the bar ends.
	const barBox = (await bar.boundingBox())!;
	const editorBox = (await page.locator('.excalidraw').first().boundingBox())!;
	expect(editorBox.y).toBeGreaterThanOrEqual(barBox.y + barBox.height - 1);
	expect(editorBox.height).toBeGreaterThan(400);
});

test('the notice says the workspace is shared', async ({ page }) => {
	await openSlot(page, 's/1');

	await expect(page.getByRole('note')).toBeVisible();
	await expect(page.getByRole('note')).toHaveText(
		'Shared workspace. Anyone who can open this page can see it and edit it.'
	);
});

test('without an edit token every browser edits, and an edit link changes only the address', async ({
	page,
	person,
	baseURL
}) => {
	// The last sentence of T-008: with the token empty, both clients can edit.
	// One of the two comes by a link that carries a token, as an old link would.
	const slot = SLOTS.tools;
	const row = ['direct', 'root', 'board'].indexOf(test.info().project.name);
	const other = await person('Bea');

	await page.goto(`s/${slot}#e=an-old-token`);
	await expectEditor(page);
	await expectLive(page);
	await joinSlot(other, slot);

	// The fragment goes, here as on a segl that has a token.
	await expect(page).toHaveURL(new URL(`s/${slot}`, baseURL).href);
	for (const browser of [page, other]) {
		await expect(browser.getByRole('note')).toHaveAttribute('data-editing', 'open');
		await expect(browser.getByRole('note')).toHaveText(
			'Shared workspace. Anyone who can open this page can see it and edit it.'
		);
	}
	const mine = await drawRectangle(page, -330, 120 + row * 70);
	await expect.poll(() => elementIds(other)).toContain(mine);
	const theirs = await drawRectangle(other, -210, 120 + row * 70);
	await expect.poll(() => elementIds(page)).toContain(theirs);
	// This segl lets every hello edit, so the link's token counts as taken and
	// is kept (docs/SECURITY.md). It opens nothing: there is nothing to open.
	expect(await page.evaluate((key) => localStorage.getItem(key), tokenKey(baseURL))).toBe(
		'an-old-token'
	);
});

test('a slot nobody has drawn on loads empty', async ({ page }) => {
	await openSlot(page, `s/${SLOTS.empty}`);

	expect((await sceneDocument(page)).elements).toEqual([]);
});

test('the canvas tools work', async ({ page }) => {
	// Not an empty slot: the room keeps what this test drew the last time.
	await openSlot(page, `s/${SLOTS.tools}`);
	const before = await elementIds(page);

	const id = await drawRectangle(page);

	expect(before).not.toContain(id);
	expect(await elementOf(page, id)).toMatchObject({ type: 'rectangle', isDeleted: false });
});

test('the root opens slot 1 first, and afterwards the last slot', async ({ page, baseURL }) => {
	const { basePath } = mountOf(baseURL);

	await page.goto('./');
	await expect(page).toHaveURL(new URL('s/1', baseURL).href);
	await expectEditor(page);

	await openSlot(page, 's/4');
	await expect(page.getByRole('heading', { level: 1 })).toHaveText('Workspace 4');
	// The key carries the mount, so two mounts on one origin stay separate.
	const stored = await page.evaluate(
		(key) => localStorage.getItem(key),
		`segl:${basePath}:lastSlot`
	);
	expect(stored).toBe('4');

	await page.goto('./');
	await expect(page).toHaveURL(new URL('s/4', baseURL).href);
	await expectEditor(page);
});

for (const path of ['s/0', 's/10', 's/01', 's/abc', 's/']) {
	test(`${path} goes to slot 1`, async ({ page, baseURL }) => {
		await page.goto(path);

		await expect(page).toHaveURL(new URL('s/1', baseURL).href);
		await expect(page.getByRole('heading', { level: 1 })).toHaveText('Workspace 1');
		await expectEditor(page);
	});
}

test('a slot button opens that slot', async ({ page, baseURL }) => {
	await openSlot(page, 's/1');

	await page.getByRole('link', { name: 'Slot 3: Workspace 3' }).click();

	await expect(page).toHaveURL(new URL('s/3', baseURL).href);
	await expect(page.getByRole('heading', { level: 1 })).toHaveText('Workspace 3');
	await expect(page.getByRole('link', { name: 'Slot 3: Workspace 3' })).toHaveAttribute(
		'aria-current',
		'page'
	);
	await expectEditor(page);
	// A reload of the new address works too: Python serves the page for every slot.
	await page.reload();
	await expect(page.getByRole('heading', { level: 1 })).toHaveText('Workspace 3');
});
