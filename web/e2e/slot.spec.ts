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
import { expect, test } from '@playwright/test';
import { readProjectVersion } from '../scripts/app-version.ts';
import { expectEditor, mountOf, openSlot, sceneDocument } from './pages.ts';

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

test('the empty scene loads, and the canvas tools work', async ({ page }) => {
	await openSlot(page, 's/2');
	expect((await sceneDocument(page)).elements).toEqual([]);

	await page.locator('[data-testid="toolbar-rectangle"]').click({ force: true });
	const canvas = (await page.locator('.excalidraw canvas.interactive').boundingBox())!;
	const x = canvas.x + canvas.width / 2;
	const y = canvas.y + canvas.height / 2;
	await page.mouse.move(x - 80, y - 50);
	await page.mouse.down();
	await page.mouse.move(x + 80, y + 50, { steps: 5 });
	await page.mouse.up();

	const { elements } = await sceneDocument(page);
	expect(elements.map((element) => element.type)).toEqual(['rectangle']);
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
