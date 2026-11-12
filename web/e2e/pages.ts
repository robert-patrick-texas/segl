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
 * What the specs share: where a project is mounted, a browser that already
 * has a display name, and how to read the canvas.
 */
import { test as base, expect, type Locator, type Page } from '@playwright/test';

export interface Mount {
	/** `https://127.0.0.1:18951`. */
	origin: string;
	/** `/board/`, or `/` at a host root. */
	basePath: string;
}

export function mountOf(baseURL: string | undefined): Mount {
	const url = new URL(baseURL ?? '');
	return { origin: url.origin, basePath: url.pathname };
}

/** The `localStorage` key of this mount's display name. */
export function nameKey(baseURL: string | undefined): string {
	return `segl:${mountOf(baseURL).basePath}:displayName`;
}

/** The label a test's browser has, unless the test asks for another or for none. */
export const STORED_NAME = 'Tester';

/**
 * `test`, with a display name already in the browser's `localStorage`.
 *
 * The server gives one address 30 names a minute (docs/SECURITY.md), and
 * every test here comes from 127.0.0.1. So a test's browser starts with a
 * label, as a returning visitor does, and asks the server for nothing. The
 * few tests about a new visitor say `test.use({ storedName: null })`.
 */
export const test = base.extend<{ storedName: string | null }>({
	storedName: [STORED_NAME, { option: true }],
	context: async ({ context, baseURL, storedName }, use) => {
		if (storedName !== null) {
			await context.addInitScript(
				([key, name]) => {
					try {
						// Only when absent, so a rename survives a reload.
						if (localStorage.getItem(key) === null) localStorage.setItem(key, name);
					} catch {
						// A page without storage, such as about:blank.
					}
				},
				[nameKey(baseURL), storedName] as const
			);
		}
		await use(context);
	}
});

/** The button in the segl bar that shows this browser's display name. */
export function nameButton(page: Page): Locator {
	return page.locator('header.segl-bar button.segl-bar__name');
}

/** Open a path under the mount, such as `s/1`, and wait for the editor to paint. */
export async function openSlot(page: Page, path: string): Promise<void> {
	await page.goto(path);
	await expectEditor(page);
}

export async function expectEditor(page: Page): Promise<void> {
	await expect(page.locator('.excalidraw canvas.interactive')).toBeVisible();
	await page.waitForFunction(() => window.SEGL_CANVAS !== undefined);
}

export interface SceneDocument {
	type: string;
	version: number;
	source: string;
	elements: { type: string; isDeleted: boolean }[];
	appState: Record<string, unknown>;
	/** Left out of a document made for storage: files are stored apart (T07). */
	files?: Record<string, unknown>;
}

/** The scene document the mounted editor would store. */
export async function sceneDocument(page: Page): Promise<SceneDocument> {
	const text = await page.evaluate(() => window.SEGL_CANVAS!.document());
	return JSON.parse(text) as SceneDocument;
}
