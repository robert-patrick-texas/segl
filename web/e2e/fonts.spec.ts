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
 * The one font file that is not the editor's own (D2-026).
 *
 * The editor ships Liberation Sans 1.05, which is under the GNU General
 * Public License. The build puts version 2.1.5 in its place, under the SIL
 * Open Font License (`web/licenses/README.md`). The editor registers the
 * face and fetches the file only when some text uses it, so the test asks
 * the page to load it, and compares what came back with the file in `fonts/`.
 */
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { expect } from '@playwright/test';
import { openSlot, test } from './pages.ts';

const FONT = 'fonts/Liberation/LiberationSans-Regular.woff2';
const SHIPPED = new URL(`../${FONT}`, import.meta.url);

function sha256(bytes: Uint8Array): string {
	return createHash('sha256').update(bytes).digest('hex');
}

test('the Liberation Sans a page loads is the file segl ships, from its own mount', async ({
	page,
	baseURL
}) => {
	const answers: { url: string; status: number; hash: string }[] = [];
	page.on('response', async (response) => {
		if (!response.url().endsWith(FONT)) return;
		const body = await response.body();
		answers.push({ url: response.url(), status: response.status(), hash: sha256(body) });
	});

	await openSlot(page, 's/1');
	// Nothing on an empty slot uses the face, so nothing has asked for it.
	expect(answers).toEqual([]);

	const loaded = await page.evaluate(async () => {
		const faces = await document.fonts.load('20px "Liberation Sans"', 'segl');
		return faces.map((face) => `${face.family} ${face.status}`);
	});

	// The browser took the file as a font.
	expect(loaded).toEqual(['"Liberation Sans" loaded']);
	await expect
		.poll(() => answers)
		.toEqual([
			{ url: new URL(FONT, baseURL).href, status: 200, hash: sha256(readFileSync(SHIPPED)) }
		]);
});
