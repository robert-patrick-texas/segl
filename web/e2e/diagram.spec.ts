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
 * T-024, Diagram mode on slot 9: drawio's editor, co-editing, and the pen.
 *
 * Every test draws its own rectangles and counts them, since the three
 * projects share one server and the room keeps what was drawn. A restart is
 * in `durability.spec.ts`, and a viewer in `access.spec.ts`.
 */
import { expect, type Page } from '@playwright/test';
import {
	diagramCounts,
	diagramXml,
	drawio,
	drawShape,
	expectVertices,
	openDiagram,
	penStatus,
	shapes,
	vertexCount,
	vertices
} from './diagram.ts';
import { collabUrl, expectSaved, mountOf, SLOTS, test } from './pages.ts';

async function headVertices(page: Page): Promise<number> {
	const reply = await page.request.get(`api/v1/slots/${SLOTS.diagram}/scene`);
	const body = (await reply.json()) as { scene: { diagram: string } };
	return vertexCount(body.scene.diagram);
}

test('slot 9 is drawio’s editor under the bar, which says Diagram mode', async ({ page }) => {
	await openDiagram(page);

	const bar = page.locator('header.segl-bar');
	await expect(bar.locator('.segl-bar__mode')).toHaveText('Diagram mode');
	await expect(penStatus(page)).toContainText('Pen free');
	// History and Import come to Diagram mode later.
	await expect(bar.getByRole('button', { name: /History/ })).toHaveCount(0);
	await expect(bar.getByRole('button', { name: /Import/ })).toHaveCount(0);
	// drawio's own panel has its network and Cisco sets.
	const sets = drawio(page);
	await expect(sets.getByText('Network 2018', { exact: true })).toBeVisible();
	await expect(sets.getByText('Cisco 19 / Routing WAN', { exact: true })).toBeVisible();
	// No Save or Exit: the diagram is saved as it changes.
	await expect(sets.getByRole('button', { name: /^(Save|Exit)$/ })).toHaveCount(0);
});

test('two browsers on slot 9 see each other’s shapes', async ({ page, person }) => {
	await openDiagram(page);
	const other = await person('Bravo2');
	await openDiagram(other);
	const before = await vertices(page);

	await drawShape(page);
	await expectVertices(other, before + 1);
	await drawShape(other);
	await expectVertices(page, before + 2);

	await expectSaved(page);
	await expectSaved(other);
	expect(await diagramXml(page)).toBe(await diagramXml(other));
	expect(await headVertices(page)).toBe(before + 2);
});

test('each draws at the same time, and both shapes remain in both', async ({ page, person }) => {
	await openDiagram(page);
	const other = await person('Bravo2');
	await openDiagram(other);
	const before = await vertices(page);

	await Promise.all([drawShape(page), drawShape(other)]);

	await expectVertices(page, before + 2);
	await expectVertices(other, before + 2);
	await expectSaved(page);
	await expectSaved(other);
	await expect.poll(() => headVertices(page)).toBe(before + 2);
});

test('a reload keeps the diagram', async ({ page }) => {
	await openDiagram(page);
	const before = await vertices(page);
	await drawShape(page);
	await expectSaved(page);

	await page.reload();
	await openDiagram(page, page.url());

	await expectVertices(page, before + 1);
});

test('one browser takes the pen: the other sees its changes and cannot edit, then takes it in turn', async ({
	page,
	person
}) => {
	await openDiagram(page);
	const other = await person('Bravo2');
	await openDiagram(other);
	const before = await vertices(page);

	await page.getByRole('button', { name: 'Take pen' }).click();
	await expect(penStatus(page)).toContainText('You have the pen');
	await expect(penStatus(other)).toContainText('Pen: Tester');

	// The watcher's drawio is read-only: a click on a shape adds nothing.
	await shapes(other).first().click();
	await drawShape(page);
	await expectVertices(other, before + 1);
	await expectVertices(page, before + 1);

	await other.getByRole('button', { name: 'Take pen' }).click();
	await expect(penStatus(page)).toContainText('Pen: Bravo2');
	await shapes(page).first().click();
	await drawShape(other);
	await expectVertices(page, before + 2);
	await expectVertices(other, before + 2);

	await other.getByRole('button', { name: 'Give pen back' }).click();
	await expect(penStatus(page)).toContainText('Pen free');
	await drawShape(page);
	await expectVertices(other, before + 3);
});

test('the holder leaves, and the pen is free', async ({ page, person }) => {
	await openDiagram(page);
	const other = await person('Bravo2');
	await openDiagram(other);
	await other.getByRole('button', { name: 'Take pen' }).click();
	await expect(penStatus(page)).toContainText('Pen: Bravo2');

	await other.close();

	await expect(penStatus(page)).toContainText('Pen free');
	const before = await vertices(page);
	await drawShape(page);
	await expectVertices(page, before + 1);
	await expectSaved(page);
	expect(await diagramCounts(page)).toEqual({ mismatches: 0, reloads: 0 });
});

test('Diagram mode asks for nothing off its origin, sets no cookie, and stays in its mount', async ({
	page,
	baseURL
}) => {
	const { origin, basePath } = mountOf(baseURL);
	const outside: string[] = [];
	const local: string[] = [];
	const cookies: string[] = [];
	const sockets: string[] = [];
	page.on('websocket', (socket) => sockets.push(socket.url()));
	await page.context().route('**/*', async (route) => {
		const url = new URL(route.request().url());
		if (url.protocol === 'data:' || url.protocol === 'blob:') return route.continue();
		if (url.origin !== origin) {
			outside.push(url.href);
			return route.abort('internetdisconnected');
		}
		local.push(url.pathname);
		return route.continue();
	});
	page.on('response', async (response) => {
		if ((await response.headerValue('set-cookie')) !== null) cookies.push(response.url());
	});

	await openDiagram(page);
	const before = await vertices(page);
	await drawShape(page);
	await expectSaved(page);
	await page.waitForLoadState('networkidle');

	expect(outside).toEqual([]);
	expect(cookies).toEqual([]);
	expect(sockets).toEqual([collabUrl(baseURL, SLOTS.diagram)]);
	expect(local.every((path) => path.startsWith(basePath))).toBe(true);
	expect(local).toContain(`${basePath}drawio/js/app.min.js`);
	// drawio keeps its settings beside segl's, under keys of its own.
	const keys = await drawio(page)
		.locator('body')
		.evaluate(() => Object.keys(localStorage));
	expect(keys.filter((key) => !key.startsWith('segl:'))).toEqual(['.drawio-config']);
	// No service worker: drawio's offline mode is off.
	expect(
		await page.evaluate(async () => (await navigator.serviceWorker.getRegistrations()).length)
	).toBe(0);
	await expectVertices(page, before + 1);
});
