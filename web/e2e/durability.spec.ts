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
 * What the bar called saved is there after the server is killed and started
 * again (S-004, S-012; docs/TEST-PLAN.md T-006 and the second half of T-007).
 *
 * This spec is the `restart` project. Each test has a segl of its own
 * (`server.ts`), with a new database, on a port no other project uses.
 */
import { expect, type APIRequestContext } from '@playwright/test';
import {
	connectionStatus,
	drawRectangle,
	dropImage,
	elementIds,
	elementOf,
	expectLive,
	expectPainted,
	expectSaved,
	imageOf,
	joinSlot,
	png,
	test as base,
	type Rgb,
	type SceneDocument
} from './pages.ts';
import { RestartableServer } from './server.ts';

const test = base.extend<{ server: RestartableServer }>({
	server: async ({ baseURL }, use) => {
		const server = new RestartableServer(baseURL!);
		try {
			await server.start();
			await use(server);
		} finally {
			await server.remove();
		}
	}
});

interface StoredScene {
	scene: SceneDocument;
	epoch: number;
	savedAt: string;
	editorLabel: string;
	files: { id: string; hash: string; mimeType: string }[];
}

async function storedScene(request: APIRequestContext, slot: number): Promise<StoredScene> {
	const response = await request.get(`api/v1/slots/${slot}/scene`);
	expect(response.status()).toBe(200);
	return (await response.json()) as StoredScene;
}

test('after the bar says saved, a killed and restarted server has the scene', async ({
	page,
	person,
	request,
	server
}) => {
	// T-006, and S-004: "after the process is killed once the UI says saved".
	const empty = await storedScene(request, 1);
	await joinSlot(page, 2);
	const kept = await drawRectangle(page, -150, 0);
	const gone = await drawRectangle(page, 150, 0);
	await page.keyboard.press('Delete');
	await expect.poll(() => elementIds(page)).not.toContain(gone);
	// Moved after it was drawn: the copy that must come back is the last one.
	await page.keyboard.press('Control+a');
	for (let step = 0; step < 4; step += 1) await page.keyboard.press('Shift+ArrowDown');
	const mine = (await elementOf(page, kept))!;
	await expectSaved(page);
	const before = await storedScene(request, 2);
	expect(before.scene.elements.find((element) => element.id === kept)).toMatchObject({
		version: mine.version,
		y: mine.y
	});

	await server.kill();

	await expect(connectionStatus(page)).toHaveText('Disconnected');
	await server.start();

	// The head scene matches: the same document, written at the same time.
	const after = await storedScene(request, 2);
	expect(after).toEqual(before);
	expect(after.editorLabel).toBe('Tester');
	// Slot 1 is as it was made.
	expect(await storedScene(request, 1)).toEqual(empty);
	// A browser that loads the slot now has the drawing, and not what was deleted.
	const fresh = await person('Bea');
	await joinSlot(fresh, 2);
	expect(await elementOf(fresh, kept)).toMatchObject({ version: mine.version, y: mine.y });
	expect(await elementIds(fresh)).not.toContain(gone);
	// The page that was open all along finds the server again by itself, and
	// has nothing to send that the server lacks.
	await expectLive(page);
	await expect(connectionStatus(page)).toHaveText('Live');
	expect(await elementOf(page, kept)).toMatchObject({ version: mine.version, y: mine.y });
	// Drawing goes on, and is saved again.
	const next = await drawRectangle(fresh, 0, 200);
	await expectSaved(fresh);
	await expect.poll(() => elementIds(page)).toContain(next);
});

test('an image is there after the server is killed and restarted', async ({
	page,
	person,
	request,
	server
}) => {
	// T-007: reach saved, restart, load the slot in a fresh context.
	const color: Rgb = [0, 200, 120];
	const other = await person('Bea');
	await joinSlot(page, 6);
	await joinSlot(other, 6);
	const placed = await dropImage(page, png(160, 100, color), 500, 320);
	// The context that was already open shows it without reloading.
	await expectPainted(other, placed.id, color);
	await expectSaved(page);
	const before = await storedScene(request, 6);
	expect(before.files).toHaveLength(1);

	await server.kill();
	await other.context().close();
	await page.close();
	await server.start();

	expect(await storedScene(request, 6)).toEqual(before);
	const fresh = await person('Cy');
	await joinSlot(fresh, 6);
	expect(await imageOf(fresh, placed.id)).toMatchObject({
		fileId: placed.fileId,
		x: placed.x,
		y: placed.y
	});
	// The image renders: the canvas shows its color where the image is.
	await expectPainted(fresh, placed.id, color);
});
