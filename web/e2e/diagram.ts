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
 * Diagram mode in a browser test (T-024): drawio's editor in its frame on
 * slot 9. A test draws by clicking the first shape of drawio's General set,
 * a rectangle, which adds one vertex. It reads the diagram through
 * `window.SEGL_DIAGRAM` and counts the vertices, since the slot is shared and
 * outlasts a test.
 */
import { expect, type FrameLocator, type Locator, type Page } from '@playwright/test';
import { expectLive, SLOTS } from './pages.ts';

/** drawio's frame. */
export function drawio(page: Page): FrameLocator {
	return page.frameLocator('iframe.segl-diagram');
}

/** The shapes of drawio's panel. The first is a rectangle. */
export function shapes(page: Page): Locator {
	return drawio(page).locator('.geSidebarContainer .geSidebar a');
}

/**
 * How long drawio may take to start in its frame. It loads 22 MB of script,
 * which took over 5 seconds on a busy CI runner (run 46038213846).
 */
export const DRAWIO_START_MS = 30_000;

/** Open slot 9, or another path to it, and wait until drawio and the room are ready. */
export async function openDiagram(page: Page, path = `s/${SLOTS.diagram}`): Promise<void> {
	await page.goto(path);
	await page.waitForFunction(() => window.SEGL_DIAGRAM !== undefined);
	await expect(shapes(page).first()).toBeVisible({ timeout: DRAWIO_START_MS });
	await expectLive(page);
}

/** The frame's whole diagram, as drawio's XML. */
export async function diagramXml(page: Page): Promise<string> {
	return page.evaluate(() => window.SEGL_DIAGRAM!.xml());
}

/** How many vertices a diagram's XML holds. */
export function vertexCount(xml: string): number {
	return (xml.match(/vertex="1"/g) ?? []).length;
}

export async function vertices(page: Page): Promise<number> {
	return vertexCount(await diagramXml(page));
}

/** Wait until the page's diagram holds this many vertices. */
export async function expectVertices(page: Page, count: number): Promise<void> {
	await expect.poll(() => vertices(page)).toBe(count);
}

/** Draw one rectangle. */
export async function drawShape(page: Page): Promise<void> {
	await shapes(page).first().click();
}

/** What the bar says of the pen. */
export function penStatus(page: Page): Locator {
	return page.locator('header.segl-bar .segl-bar__pen');
}

/** `{ mismatches, reloads }` of this page. */
export async function diagramCounts(page: Page): Promise<{ mismatches: number; reloads: number }> {
	return JSON.parse(await page.evaluate(() => window.SEGL_DIAGRAM!.counts())) as {
		mismatches: number;
		reloads: number;
	};
}
