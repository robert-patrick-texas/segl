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

/** What the specs share: where a project is mounted, and how to read the canvas. */
import { expect, type Page } from '@playwright/test';

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
