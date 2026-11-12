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
 * `src/segl/empty_scene.json`, the scene a new slot starts with, is the
 * pinned editor's own empty scene (docs/DATA-MODEL.md).
 *
 * The editor is given a slot with no elements and nothing else, and the
 * document it would store has to equal the fixture. A new Excalidraw release
 * that changes the document fails here. To capture it again:
 *
 *     SEGL_UPDATE_FIXTURE=1 npm run e2e -- fixture.spec.ts --project direct
 */
import { readFileSync, writeFileSync } from 'node:fs';
import { expect } from '@playwright/test';
import { openSlot, sceneDocument, test } from './pages.ts';

const FIXTURE = new URL('../../src/segl/empty_scene.json', import.meta.url);

test("the bootstrap fixture is the editor's own empty scene", async ({ page }) => {
	// Not the stored head, which is the fixture itself once a database is new.
	await page.route('**/api/v1/slots/1/scene', async (route) => {
		const response = await route.fetch();
		const body = (await response.json()) as Record<string, unknown>;
		await route.fulfill({ response, json: { ...body, scene: { elements: [] } } });
	});
	await openSlot(page, 's/1');
	const captured = await sceneDocument(page);

	if (process.env['SEGL_UPDATE_FIXTURE']) {
		writeFileSync(FIXTURE, `${JSON.stringify(captured, null, 2)}\n`);
	}
	expect(captured).toEqual(JSON.parse(readFileSync(FIXTURE, 'utf8')));
	expect(captured.elements).toEqual([]);
});

test('a new slot starts with the fixture, and the editor keeps it as it is', async ({
	page,
	request
}) => {
	const fixture: unknown = JSON.parse(readFileSync(FIXTURE, 'utf8'));
	const head = (await (await request.get('api/v1/slots/9/scene')).json()) as { scene: unknown };
	expect(head.scene).toEqual(fixture);

	await openSlot(page, 's/9');
	expect(await sceneDocument(page)).toEqual(fixture);
});
