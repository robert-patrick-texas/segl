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
 * The page half of T-013, and T-010: one build, at a host root and under
 * `/board/`, asks for nothing outside its mount and nothing off its host.
 *
 * Every request to another origin is refused, as with outbound network
 * blocked, and counted. The editor still has to paint, with its fonts.
 *
 * The first test's browser is a new visitor, so the request for a display
 * name is part of what is watched.
 */
import { expect, type Page } from '@playwright/test';
import { expectEditor, mountOf, nameButton, sceneDocument, test } from './pages.ts';

interface Traffic {
	/** Paths asked of the page's own origin. */
	local: string[];
	/** Requests to any other origin. All of them were refused. */
	outside: string[];
	/** Responses with a status of 400 or more. */
	failed: string[];
	/** Responses that set a cookie. */
	cookies: string[];
}

async function watch(page: Page, origin: string): Promise<Traffic> {
	const traffic: Traffic = { local: [], outside: [], failed: [], cookies: [] };
	await page.route('**/*', async (route) => {
		const url = new URL(route.request().url());
		if (url.protocol === 'data:' || url.protocol === 'blob:') return route.continue();
		if (url.origin !== origin) {
			traffic.outside.push(url.href);
			return route.abort('internetdisconnected');
		}
		traffic.local.push(url.pathname);
		return route.continue();
	});
	page.on('response', async (response) => {
		if (response.status() >= 400) traffic.failed.push(`${response.status()} ${response.url()}`);
		if ((await response.headerValue('set-cookie')) !== null) traffic.cookies.push(response.url());
	});
	return traffic;
}

test.describe('a new visitor', () => {
	test.use({ storedName: null });

	test('the slot page stays inside its mount, with outbound network blocked', async ({
		page,
		baseURL
	}) => {
		const { origin, basePath } = mountOf(baseURL);
		const traffic = await watch(page, origin);

		await page.goto('s/1');
		await expectEditor(page);
		await expect(page.getByRole('heading', { level: 1 })).toHaveText('Workspace 1');
		// The label came from this segl, under the mount.
		await expect(nameButton(page)).toHaveText(/^(Guest|Staff)\d+$/);

		// A text element makes the editor fetch a canvas font, which it would take
		// from a public CDN if it were not pointed at segl.
		const font = page.waitForResponse((response) => response.url().includes('/fonts/'));
		await page.locator('[data-testid="toolbar-text"]').click({ force: true });
		const canvas = (await page.locator('.excalidraw canvas.interactive').boundingBox())!;
		await page.mouse.click(canvas.x + canvas.width / 2, canvas.y + canvas.height / 2);
		await page.keyboard.type('segl');
		await page.keyboard.press('Escape');
		expect((await font).status()).toBe(200);
		expect((await sceneDocument(page)).elements.map((element) => element.type)).toEqual(['text']);
		await page.waitForLoadState('networkidle');

		expect(traffic.outside).toEqual([]);
		expect(traffic.failed).toEqual([]);
		expect(traffic.local.filter((path) => !path.startsWith(basePath))).toEqual([]);
		// The page, the API, the build's files, and the editor's fonts, all under the mount.
		expect(traffic.local).toContain(`${basePath}s/1`);
		expect(traffic.local).toContain(`${basePath}api/v1/slots/1/scene`);
		expect(traffic.local).toContain(`${basePath}api/v1/display-name`);
		expect(traffic.local.some((path) => path.startsWith(`${basePath}assets/`))).toBe(true);
		expect(traffic.local.some((path) => path.startsWith(`${basePath}fonts/`))).toBe(true);
		// No cookie (S-007).
		expect(traffic.cookies).toEqual([]);
		expect(await page.evaluate(() => document.cookie)).toBe('');
	});
});

test('opening the root stays inside the mount too', async ({ page, baseURL }) => {
	const { origin, basePath } = mountOf(baseURL);
	const traffic = await watch(page, origin);

	await page.goto('./');
	await expect(page).toHaveURL(new URL('s/1', baseURL).href);
	await expectEditor(page);
	await page.waitForLoadState('networkidle');

	expect(traffic.outside).toEqual([]);
	expect(traffic.failed).toEqual([]);
	expect(traffic.local.filter((path) => !path.startsWith(basePath))).toEqual([]);
});
