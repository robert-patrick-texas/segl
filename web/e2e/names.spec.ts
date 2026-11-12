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
 * Display names in the segl bar (S-009, the browser's side of
 * docs/TEST-PLAN.md T-014): a new browser is given a label once and keeps it
 * across reloads, and a typed name is title-cased and kept.
 *
 * The test server's word file is `Guest` and `Staff`. The numbers depend on
 * which test asked first, so the tests check the shape. tests/test_names.py
 * checks the order, `Guest1`, `Staff2`, `Guest3`, and the limit through nginx.
 */
import { expect, type Page } from '@playwright/test';
import {
	expectEditor,
	nameButton,
	nameKey,
	openSlot,
	sceneDocument,
	STORED_NAME,
	test
} from './pages.ts';

const ASSIGNED = /^(Guest|Staff)[1-9]\d*$/;

/** Count this page's requests for a new display name. */
function allocations(page: Page): () => number {
	let count = 0;
	page.on('request', (request) => {
		const path = new URL(request.url()).pathname;
		if (request.method() === 'POST' && path.endsWith('/api/v1/display-name')) count += 1;
	});
	return () => count;
}

function storedName(page: Page, baseURL: string | undefined): Promise<string | null> {
	return page.evaluate((key) => localStorage.getItem(key), nameKey(baseURL));
}

function nameField(page: Page) {
	return page.getByRole('textbox', { name: 'Your name' });
}

test.describe('a new visitor', () => {
	test.use({ storedName: null });

	test('is given a label once, and keeps it across reloads and slots', async ({
		page,
		baseURL
	}) => {
		const asked = allocations(page);

		await openSlot(page, 's/1');
		await expect(nameButton(page)).toHaveText(ASSIGNED);
		const label = (await nameButton(page).textContent())!;
		await expect(nameButton(page)).toHaveAccessibleName(`Your name: ${label}. Change it`);
		expect(await storedName(page, baseURL)).toBe(label);

		await page.reload();
		await expectEditor(page);
		await expect(nameButton(page)).toHaveText(label);

		await openSlot(page, 's/4');
		await expect(nameButton(page)).toHaveText(label);
		await page.getByRole('link', { name: 'Slot 3: Workspace 3' }).click();
		await expect(page.getByRole('heading', { level: 1 })).toHaveText('Workspace 3');
		await expect(nameButton(page)).toHaveText(label);

		await page.goto('./');
		await expectEditor(page);
		await expect(nameButton(page)).toHaveText(label);

		expect(await storedName(page, baseURL)).toBe(label);
		expect(asked()).toBe(1);
	});

	test('two browsers get different labels', async ({ browser, baseURL }) => {
		const labels: string[] = [];
		for (let visitor = 0; visitor < 2; visitor += 1) {
			const context = await browser.newContext({ baseURL, ignoreHTTPSErrors: true });
			const page = await context.newPage();
			await openSlot(page, 's/1');
			await expect(nameButton(page)).toHaveText(ASSIGNED);
			labels.push((await nameButton(page).textContent())!);
			await context.close();
		}

		// The counter never repeats, so the numbers differ even when the word does not.
		const numbers = labels.map((label) => Number(label.replace(/\D+/g, '')));
		expect(numbers[0]).not.toBe(numbers[1]);
	});

	test('a refusal leaves the page usable, and the label arrives later', async ({ page }) => {
		// The limit of 30 names a minute, as this page would meet it.
		let refusing = true;
		await page.route('**/api/v1/display-name', (route) =>
			refusing
				? route.fulfill({
						status: 429,
						headers: { 'Retry-After': '1' },
						json: { error: 'rate_limited', message: 'Too many names.' }
					})
				: route.continue()
		);

		await page.goto('s/1');
		await expect(nameButton(page)).toHaveText('Set your name');
		await expectEditor(page);
		await expect(page.getByRole('heading', { level: 1 })).toHaveText('Workspace 1');
		await expect(nameButton(page)).toHaveText('Set your name');

		refusing = false;
		await expect(nameButton(page)).toHaveText(ASSIGNED, { timeout: 10_000 });
	});

	test('a name typed during a refusal stays, and no label is asked for after it', async ({
		page,
		baseURL
	}) => {
		let refusing = true;
		let passed = 0;
		await page.route('**/api/v1/display-name', (route) => {
			if (!refusing) {
				passed += 1;
				return route.continue();
			}
			return route.fulfill({
				status: 429,
				headers: { 'Retry-After': '1' },
				json: { error: 'rate_limited', message: 'Too many names.' }
			});
		});
		await openSlot(page, 's/1');
		await expect(nameButton(page)).toHaveText('Set your name');

		await nameButton(page).click();
		await expect(nameField(page)).toHaveValue('');
		await nameField(page).fill('ada lovelace');
		await nameField(page).press('Enter');
		await expect(nameButton(page)).toHaveText('Ada Lovelace');

		// Longer than the retry the refusal asked for.
		refusing = false;
		await page.waitForTimeout(2_500);
		expect(passed).toBe(0);
		await expect(nameButton(page)).toHaveText('Ada Lovelace');
		expect(await storedName(page, baseURL)).toBe('Ada Lovelace');
	});

	test('a browser that refuses storage still gets a label, and keeps a typed one', async ({
		page
	}) => {
		await page.addInitScript(() => {
			Object.defineProperty(window, 'localStorage', {
				get: () => {
					throw new DOMException('storage is blocked', 'SecurityError');
				}
			});
		});
		// Hold the server's answer until the person has typed a name.
		let release = () => {};
		const held = new Promise<void>((resolve) => (release = resolve));
		await page.route('**/api/v1/display-name', async (route) => {
			await held;
			await route.continue();
		});

		await openSlot(page, 's/1');
		await expect(nameButton(page)).toHaveText('Set your name');
		await nameButton(page).click();
		await nameField(page).fill('ada lovelace');
		await nameField(page).press('Enter');
		await expect(nameButton(page)).toHaveText('Ada Lovelace');

		const answered = page.waitForResponse((response) =>
			response.url().endsWith('/api/v1/display-name')
		);
		release();
		expect((await answered).status()).toBe(200);
		// The late answer does not replace what the person typed.
		await page.waitForTimeout(500);
		await expect(nameButton(page)).toHaveText('Ada Lovelace');
	});
});

test('a returning visitor keeps the stored label and asks for none', async ({ page, baseURL }) => {
	const asked = allocations(page);

	await openSlot(page, 's/2');
	await expect(nameButton(page)).toHaveText(STORED_NAME);
	await page.reload();
	await expectEditor(page);
	await expect(nameButton(page)).toHaveText(STORED_NAME);
	await page.waitForLoadState('networkidle');

	expect(await storedName(page, baseURL)).toBe(STORED_NAME);
	expect(asked()).toBe(0);
});

test('a rename is title-cased, stored, and kept across a reload', async ({ page, baseURL }) => {
	const asked = allocations(page);
	await openSlot(page, 's/1');

	await nameButton(page).click();
	await expect(nameField(page)).toBeFocused();
	await expect(nameField(page)).toHaveValue(STORED_NAME);
	await nameField(page).fill('john smith');
	await nameField(page).press('Enter');

	await expect(nameButton(page)).toHaveText('John Smith');
	await expect(nameButton(page)).toBeFocused();
	expect(await storedName(page, baseURL)).toBe('John Smith');
	// The letters went to the field, not to the editor's tool shortcuts.
	expect((await sceneDocument(page)).elements).toEqual([]);

	await page.reload();
	await expectEditor(page);
	await expect(nameButton(page)).toHaveText('John Smith');
	await openSlot(page, 's/5');
	await expect(nameButton(page)).toHaveText('John Smith');
	expect(asked()).toBe(0);
});

test('Escape keeps the old name, and so does a name that is not usable', async ({
	page,
	baseURL
}) => {
	await openSlot(page, 's/1');

	await nameButton(page).click();
	await nameField(page).fill('someone else');
	await nameField(page).press('Escape');
	await expect(nameButton(page)).toHaveText(STORED_NAME);
	await expect(nameButton(page)).toBeFocused();

	// Only spaces, and then 41 characters: the field stays open and says why.
	await nameButton(page).click();
	await nameField(page).fill('   ');
	await nameField(page).press('Enter');
	await expect(page.getByRole('alert')).toHaveText('1 to 40 characters');
	await expect(nameField(page)).toHaveAttribute('aria-invalid', 'true');
	await nameField(page).fill('x'.repeat(41));
	await expect(page.getByRole('alert')).toHaveCount(0);
	await nameField(page).press('Enter');
	await expect(page.getByRole('alert')).toHaveText('1 to 40 characters');
	await nameField(page).press('Escape');
	await expect(nameButton(page)).toHaveText(STORED_NAME);
	expect(await storedName(page, baseURL)).toBe(STORED_NAME);

	// Leaving the field keeps a usable name, and drops one that is not.
	await nameButton(page).click();
	await nameField(page).fill('grace  HOPPER');
	await page.getByRole('heading', { level: 1 }).click();
	await expect(nameButton(page)).toHaveText('Grace Hopper');
	await nameButton(page).click();
	await nameField(page).fill('  ');
	await page.getByRole('heading', { level: 1 }).click();
	await expect(nameButton(page)).toHaveText('Grace Hopper');
	expect(await storedName(page, baseURL)).toBe('Grace Hopper');
});

test.describe('a label from the word file', () => {
	test.use({ storedName: 'McKinley7' });

	test('keeps its spelling when the field is opened and closed', async ({ page, baseURL }) => {
		await openSlot(page, 's/1');
		await expect(nameButton(page)).toHaveText('McKinley7');

		await nameButton(page).click();
		await expect(nameField(page)).toHaveValue('McKinley7');
		await nameField(page).press('Enter');
		await expect(nameButton(page)).toHaveText('McKinley7');
		await nameButton(page).click();
		await page.getByRole('heading', { level: 1 }).click();
		await expect(nameButton(page)).toHaveText('McKinley7');

		expect(await storedName(page, baseURL)).toBe('McKinley7');
	});
});
