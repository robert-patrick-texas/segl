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
 * A pass that ends (S-008, D2-033; docs/TEST-PLAN.md T-019): after
 * `access_pass_hours`, the person enters a code again. `welcome` tells the
 * page how long its pass has, and the page stops taking edits a second
 * before that, so that nothing is drawn which the server would refuse.
 *
 * This spec is in the `restart` project, beside `durability.spec.ts`. Each
 * test has a segl of its own (`server.ts`), whose passes last seconds, on a
 * port no other project uses.
 */
import { expect, type Page } from '@playwright/test';
import {
	drawRectangle,
	elementIds,
	expectEditor,
	expectLive,
	expectSaved,
	joinSlot,
	passKey,
	test as base
} from './pages.ts';
import { RestartableServer } from './server.ts';
import { ACCESS_CODE, ACCESS_SECRET, PASS_SHAPE } from './sites.ts';

/** How long a pass of this server lasts: 0.004 hours. */
const PASS_SECONDS = 14.4;

const test = base.extend<{ server: RestartableServer }>({
	server: async ({ baseURL }, use) => {
		const server = new RestartableServer(baseURL!, [
			`access_codes = [${JSON.stringify(ACCESS_CODE)}]`,
			`access_secret = ${JSON.stringify(ACCESS_SECRET)}`,
			'access_pass_hours = 0.004'
		]);
		try {
			await server.start();
			await use(server);
		} finally {
			await server.remove();
		}
	}
});

function notice(page: Page) {
	return page.locator('header.segl-bar .segl-bar__notice');
}

function accessLink(page: Page) {
	return notice(page).getByRole('link', { name: 'Enter access code' });
}

function rectangleTool(page: Page) {
	return page.locator('[data-testid="toolbar-rectangle"]');
}

/** Follow the bar's link, enter the code, and return when the server said the pass ends. */
async function enterCode(page: Page): Promise<number> {
	await accessLink(page).click();
	const answered = page.waitForResponse(
		(response) => response.url().endsWith('/api/v1/access') && response.status() === 200
	);
	await page.getByRole('textbox', { name: 'Access code' }).fill(ACCESS_CODE);
	await page.keyboard.press('Enter');
	const body = (await (await answered).json()) as { pass: string; expiresAt: string };
	expect(body.pass).toMatch(PASS_SHAPE);
	return Date.parse(body.expiresAt);
}

async function storedHead(page: Page, slot: number): Promise<string[]> {
	const head = (await (await page.request.get(`api/v1/slots/${slot}/scene`)).json()) as {
		scene: { elements: { id: string }[] };
	};
	return head.scene.elements.map((each) => each.id);
}

interface Frame {
	at: number;
	sent: boolean;
	type: string;
	error?: string;
	/** Of a `welcome`: the seconds its pass has left, or null. */
	editEndsIn?: number | null;
}

/** Record every message on the page's collaboration sockets, each with its time. Call before `goto`. */
function watchFrames(page: Page): Frame[] {
	const frames: Frame[] = [];
	page.on('websocket', (socket) => {
		const note = (sent: boolean) => (frame: { payload: string | Buffer }) => {
			const message = JSON.parse(String(frame.payload)) as Omit<Frame, 'at' | 'sent'>;
			frames.push({
				at: Date.now(),
				sent,
				type: message.type,
				error: message.error,
				editEndsIn: message.editEndsIn
			});
		};
		socket.on('framesent', note(true));
		socket.on('framereceived', note(false));
	});
	return frames;
}

/** Note, in the page, the moment its bar first says that its access has ended. */
async function noteTheLock(page: Page): Promise<void> {
	await page.evaluate(() => {
		const notice = document.querySelector('header.segl-bar .segl-bar__notice')!;
		const seen = window as unknown as { lockedAt?: number };
		new MutationObserver(() => {
			if (seen.lockedAt === undefined && notice.getAttribute('data-editing') === 'refused') {
				seen.lockedAt = Date.now();
			}
		}).observe(notice, { attributes: true });
	});
}

test('a pass ends: the browser stops taking edits before the server would refuse one, and a code entered again lets it edit', async ({
	server,
	page,
	person,
	baseURL
}) => {
	test.setTimeout(90_000);
	void server;
	const slot = 2;
	const frames = watchFrames(page);
	const watcher = await person('Wim');
	await joinSlot(page, slot);
	await joinSlot(watcher, slot);
	await expect(notice(page)).toHaveAttribute('data-editing', 'locked');

	const issuedAt = Date.now();
	const endsAt = await enterCode(page);
	// The server said when: its setting from the second the pass was stamped
	// with, which is up to a second before the answer.
	expect(endsAt - issuedAt).toBeGreaterThan((PASS_SECONDS - 2) * 1000);
	expect(endsAt - issuedAt).toBeLessThanOrEqual(PASS_SECONDS * 1000 + 500);
	await expect(page).toHaveURL(new URL(`s/${slot}`, baseURL).href);
	await expectEditor(page);
	await expectLive(page);
	await expect(notice(page)).toHaveAttribute('data-editing', 'unlocked');
	await noteTheLock(page);
	const first = await page.evaluate((key) => localStorage.getItem(key), passKey(baseURL));
	// `welcome` told the page how long its pass has: a length, a little under the whole.
	const welcomes = frames.filter((frame) => !frame.sent && frame.type === 'welcome');
	expect(welcomes).toHaveLength(2);
	// The viewer it was had nothing that ends.
	expect(welcomes[0]!.editEndsIn).toBeNull();
	expect(welcomes[1]!.editEndsIn).toBeGreaterThan(PASS_SECONDS - 3);
	expect(welcomes[1]!.editEndsIn).toBeLessThanOrEqual(PASS_SECONDS);
	// The length and the time of day the access route gave are one moment.
	expect(Math.abs(welcomes[1]!.at + welcomes[1]!.editEndsIn! * 1000 - endsAt)).toBeLessThan(1000);

	// While the pass lasts, the browser edits, and the watcher sees it.
	const drawn = await drawRectangle(page, -200, -100);
	await expectSaved(page);
	await expect.poll(() => elementIds(watcher)).toContain(drawn);
	expect(Date.now()).toBeLessThan(endsAt - 1500);

	// The page stops by itself, with nothing drawn and nothing said by the
	// server: the bar says that its access has ended, and the tools go.
	await expect(notice(page)).toHaveAttribute('data-editing', 'refused', {
		timeout: Math.max(0, endsAt - Date.now()) + 5000
	});
	await expect(notice(page)).toContainText('Editing locked: access expired');
	await expect(accessLink(page)).toBeVisible();
	await expect(rectangleTool(page)).toHaveCount(0);
	// It stopped before the pass ended on the server, and about a second before.
	const lockedAt = await page.evaluate(() => (window as unknown as { lockedAt: number }).lockedAt);
	expect(lockedAt).toBeLessThan(endsAt);
	expect(endsAt - lockedAt).toBeLessThan(2500);

	// After the end, whatever the person tries draws nothing, on this canvas too.
	await page.waitForTimeout(Math.max(0, endsAt - Date.now()) + 300);
	const canvas = (await page.locator('.excalidraw canvas.interactive').boundingBox())!;
	await page.mouse.click(canvas.x + canvas.width / 2, canvas.y + canvas.height - 150);
	await page.keyboard.press('r');
	await page.mouse.move(canvas.x + 500, canvas.y + 400);
	await page.mouse.down();
	await page.mouse.move(canvas.x + 620, canvas.y + 470, { steps: 5 });
	await page.mouse.up();
	await page.mouse.dblclick(canvas.x + 700, canvas.y + 300);
	await page.keyboard.type('late');
	await page.keyboard.press('Escape');
	await page.waitForTimeout(700);
	expect(await elementIds(page)).toEqual([drawn]);
	expect(await elementIds(watcher)).toEqual([drawn]);
	expect(await storedHead(page, slot)).toEqual([drawn]);
	// No edit left the page after its pass had ended, and the server had none to refuse.
	const edits = frames.filter((frame) => frame.sent && frame.type === 'elements');
	expect(edits.length).toBeGreaterThan(0);
	expect(edits.filter((frame) => frame.at >= endsAt)).toEqual([]);
	expect(frames.filter((frame) => frame.error === 'view_only')).toEqual([]);

	// A reload shows the same: the stored pass is the one that ended, and the
	// server now says so in `welcome`.
	await page.reload();
	await expectEditor(page);
	await expectLive(page);
	await expect(notice(page)).toHaveAttribute('data-editing', 'refused');
	expect(await elementIds(page)).toEqual([drawn]);

	// The person enters a code again, and edits again.
	await enterCode(page);
	await expect(page).toHaveURL(new URL(`s/${slot}`, baseURL).href);
	await expectEditor(page);
	await expectLive(page);
	await expect(notice(page)).toHaveAttribute('data-editing', 'unlocked');
	const second = await page.evaluate((key) => localStorage.getItem(key), passKey(baseURL));
	expect(second).toMatch(PASS_SHAPE);
	expect(second).not.toBe(first);
	const again = await drawRectangle(page, 200, -100);
	await expectSaved(page);
	await expect.poll(() => elementIds(watcher)).toContain(again);
	expect(await storedHead(page, slot)).toEqual([drawn, again]);
});
