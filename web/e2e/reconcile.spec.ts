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
 * The pinned editor's `reconcileElements`, held to the table the server's
 * rule is held to (`tests/reconcile_cases.json`, D2-025).
 *
 * The helper runs in the page, from the production build, through the canvas
 * handle. Each case is tried with either side as the local one: the same
 * scene has to come out, or two browsers and the server would not converge.
 */
import { readFileSync } from 'node:fs';
import { expect } from '@playwright/test';
import { openSlot, SLOTS, test } from './pages.ts';

interface Stamped {
	id: string;
	version: number;
	versionNonce: number;
	isDeleted: boolean;
}

interface Case {
	name: string;
	stored: Stamped[];
	incoming: Stamped[];
	result: Stamped[];
}

const { cases } = JSON.parse(
	readFileSync(new URL('../../tests/reconcile_cases.json', import.meta.url), 'utf8')
) as { cases: Case[] };

test('the editor keeps the copy the table says, whichever side is local', async ({ page }) => {
	expect(cases.length).toBeGreaterThanOrEqual(15);
	await openSlot(page, `s/${SLOTS.empty}`);

	const outcomes = await page.evaluate((table) => {
		const reconcile = (local: unknown, remote: unknown) =>
			(
				JSON.parse(
					window.SEGL_CANVAS!.reconcile(JSON.stringify(local), JSON.stringify(remote))
				) as Stamped[]
			).map(({ id, version, versionNonce, isDeleted }) => ({
				id,
				version,
				versionNonce,
				isDeleted
			}));
		return table.map(({ stored, incoming }) => ({
			arriving: reconcile(stored, incoming),
			held: reconcile(incoming, stored)
		}));
	}, cases);

	for (const [index, { name, result }] of cases.entries()) {
		expect(outcomes[index]!.arriving, `${name}: the incoming elements arrive`).toEqual(result);
		expect(outcomes[index]!.held, `${name}: the stored elements arrive`).toEqual(result);
	}
	// The table was reconciled beside the canvas, not into it.
	expect(await page.evaluate(() => JSON.parse(window.SEGL_CANVAS!.document()).elements)).toEqual(
		[]
	);
});
