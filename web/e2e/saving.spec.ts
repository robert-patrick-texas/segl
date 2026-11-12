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
 * What is drawn is kept (S-004, S-013): the bar says saving and then saved,
 * the slot's stored head has the drawing by then, and it is there after
 * everyone has left (docs/TEST-PLAN.md T-005).
 *
 * `durability.spec.ts` kills and restarts a server of its own for T-006.
 */
import { expect, type APIRequestContext, type Page } from '@playwright/test';
import {
	connectionStatus,
	drawRectangle,
	elementIds,
	expectSaved,
	joinSlot,
	SLOTS,
	test,
	type SceneDocument
} from './pages.ts';

interface StoredScene {
	scene: SceneDocument;
	epoch: number;
	savedAt: string;
	editorLabel: string;
	files: unknown[];
}

/** A slot's head, as the server has it on its disk. */
async function storedScene(request: APIRequestContext, slot: number): Promise<StoredScene> {
	const response = await request.get(`api/v1/slots/${slot}/scene`);
	expect(response.status()).toBe(200);
	return (await response.json()) as StoredScene;
}

/** Record every state the bar's status goes through from now on. */
async function recordStatus(page: Page): Promise<() => Promise<string[]>> {
	await connectionStatus(page).evaluate((status) => {
		const seen: string[] = [];
		(window as unknown as { seglStates: string[] }).seglStates = seen;
		new MutationObserver(() => {
			const state = status.getAttribute('data-state') ?? '';
			if (seen[seen.length - 1] !== state) seen.push(state);
		}).observe(status, { attributes: true, attributeFilter: ['data-state'] });
	});
	return () => page.evaluate(() => (window as unknown as { seglStates: string[] }).seglStates);
}

test('the bar says saving and then saved, and the stored head has the drawing', async ({
	page,
	request
}) => {
	// S-013, and what "saved" means: the head on the server's disk.
	await joinSlot(page, SLOTS.drawing);
	await expect(connectionStatus(page)).toHaveText('Live');
	const before = await storedScene(request, SLOTS.drawing);
	const states = await recordStatus(page);

	const drawn = await drawRectangle(page, 150, -220);
	await expectSaved(page);

	const seen = await states();
	expect(seen[0]).toBe('saving');
	expect(seen[seen.length - 1]).toBe('saved');
	expect(new Set(seen)).toEqual(new Set(['saving', 'saved']));
	const head = await storedScene(request, SLOTS.drawing);
	const stored = head.scene.elements.find((element) => element.id === drawn);
	// The same copy the canvas holds, not an earlier one of the same drag.
	const mine = (await page.evaluate(() => window.SEGL_CANVAS!.document())) as string;
	const held = (JSON.parse(mine) as SceneDocument).elements.find((each) => each.id === drawn);
	expect(stored).toMatchObject({ type: 'rectangle', version: held!.version, x: held!.x });
	expect(head.editorLabel).toBe('Tester');
	expect(Date.parse(head.savedAt)).toBeGreaterThan(Date.parse(before.savedAt));
	// The rest of the document is still the editor's.
	expect(head.scene).toMatchObject({ type: 'excalidraw', version: 2, source: 'segl' });

	// A second edit goes through saving again.
	const again = await recordStatus(page);
	await page.keyboard.press('Shift+ArrowRight');
	await expect.poll(again).toContain('saving');
	await expectSaved(page);
});

test('a drawing is still there after both browsers closed, and slot 1 is unchanged', async ({
	page,
	person,
	request
}) => {
	// T-005.
	const slot = SLOTS.drawing;
	const untouched = await storedScene(request, 1);
	const other = await person('Bea');
	await joinSlot(page, slot);
	await joinSlot(other, slot);
	const mine = await drawRectangle(page, -330, -230);
	const theirs = await drawRectangle(other, 330, -230);
	await expect.poll(() => elementIds(page)).toContain(theirs);

	await other.context().close();
	await page.close();

	// Nobody is on the slot. Its head, on the disk, has both drawings.
	await expect
		.poll(async () => (await storedScene(request, slot)).scene.elements.map((each) => each.id))
		.toEqual(expect.arrayContaining([mine, theirs]));
	const again = await person('Cy');
	await joinSlot(again, slot);
	await expect.poll(() => elementIds(again)).toEqual(expect.arrayContaining([mine, theirs]));
	// Slot 1, which no test draws on, is as it was made.
	const still = await storedScene(request, 1);
	expect(still).toEqual(untouched);
	expect(still.scene.elements).toEqual([]);
	expect(still.editorLabel).toBe('System');
});

test('a deleted element is not brought back by the stored head', async ({ page, person }) => {
	// T-003 again, now that a reload starts from the head on the disk.
	await joinSlot(page, SLOTS.deleting);
	const gone = await drawRectangle(page, 200, 150);
	await expectSaved(page);
	await page.keyboard.press('Delete');
	await expect.poll(() => elementIds(page)).not.toContain(gone);
	await expectSaved(page);

	const later = await person('Bea');
	await joinSlot(later, SLOTS.deleting);
	const kept = await drawRectangle(later, 200, 230);

	// Once what the later browser drew is here, the room's whole scene is.
	await expect.poll(() => elementIds(page)).toContain(kept);
	expect(await elementIds(later)).not.toContain(gone);
	expect(await elementIds(page)).not.toContain(gone);
});
