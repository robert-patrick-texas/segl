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
 * An image on the canvas (S-012; docs/TEST-PLAN.md T-007, up to the restart):
 * it shows in the other browser on the slot without a reload, and in a browser
 * that loads the slot afterwards. `durability.spec.ts` restarts the server.
 *
 * Every test runs in each project, so the upload and the fetch go through
 * nginx at a host root and at `/board/` too.
 */
import { createHash } from 'node:crypto';
import { expect } from '@playwright/test';
import {
	canvasImages,
	connectionStatus,
	dropImage,
	expectPainted,
	expectSaved,
	imageOf,
	joinSlot,
	mountOf,
	openSlot,
	png,
	SLOTS,
	test,
	type Rgb
} from './pages.ts';

/**
 * Each project's image is another color, so another file, and has a place
 * of its own. The three projects share one server, and an image a project
 * placed is still on the slot when the next one runs.
 */
const PICTURES: Record<string, { color: Rgb; small: Rgb; x: number }> = {
	direct: { color: [255, 0, 200], small: [200, 90, 40], x: 330 },
	root: { color: [0, 190, 255], small: [40, 200, 90], x: 560 },
	board: { color: [255, 170, 0], small: [90, 40, 200], x: 790 }
};

interface FileRef {
	id: string;
	hash: string;
	mimeType: string;
}

test('an image placed in one browser shows in the other and in a later one', async ({
	page,
	person,
	request,
	baseURL
}) => {
	const { color, x } = PICTURES[test.info().project.name]!;
	const file = png(160, 100, color);
	const slot = SLOTS.images;
	const { origin, basePath } = mountOf(baseURL);
	// Every request for an uploaded file, as method and path.
	const transfers: string[] = [];
	const watch = (who: string) => (request: { method(): string; url(): string }) => {
		const url = new URL(request.url());
		if (url.pathname.includes('/assets') && url.pathname.includes('/api/')) {
			expect(url.origin).toBe(origin);
			transfers.push(`${who} ${request.method()} ${url.pathname}`);
		}
	};
	const other = await person('Bea');
	page.on('request', watch('page'));
	other.on('request', watch('other'));
	await joinSlot(page, slot);
	await joinSlot(other, slot);

	const placed = await dropImage(page, file, x, 300);

	// The other browser, already open, gets the element, then the file, and
	// paints it, without a reload.
	await expect
		.poll(async () => (await imageOf(other, placed.id))?.mimeType ?? null, {
			message: 'the other browser has the image with its file'
		})
		.toBe('image/png');
	expect(await imageOf(other, placed.id)).toMatchObject({
		fileId: placed.fileId,
		x: placed.x,
		y: placed.y,
		width: 160,
		height: 100
	});
	await expectPainted(page, placed.id, color);
	await expectPainted(other, placed.id, color);

	// Saved covers the file: the head on the server names it.
	await expectSaved(page);
	const head = (await (await request.get(`api/v1/slots/${slot}/scene`)).json()) as {
		scene: { elements: { id: string; fileId?: string }[] };
		files: FileRef[];
	};
	expect(head.scene.elements.find((element) => element.id === placed.id)).toMatchObject({
		fileId: placed.fileId
	});
	const listed = head.files.find((entry) => entry.id === placed.fileId);
	expect(listed).toEqual({
		id: placed.fileId,
		hash: expect.stringMatching(/^[0-9a-f]{64}$/),
		mimeType: 'image/png'
	});

	// One upload, under the mount, and one fetch of it, by the browser that
	// lacked it. Images an earlier project left on the slot were fetched too.
	const fetches = () => transfers.filter((line) => line.endsWith(`/assets/${listed!.hash}`));
	expect(transfers.filter((line) => line.includes(' POST '))).toEqual([
		`page POST ${basePath}api/v1/slots/${slot}/assets`
	]);
	expect(fetches()).toEqual([`other GET ${basePath}api/v1/assets/${listed!.hash}`]);
	// The bytes are served as bytes, which no browser will run or sniff.
	const served = await request.get(`api/v1/assets/${listed!.hash}`);
	expect(served.status()).toBe(200);
	expect(served.headers()['content-type']).toBe('application/octet-stream');
	expect(served.headers()['x-content-type-options']).toBe('nosniff');
	expect(served.headers()['set-cookie']).toBeUndefined();
	// They are named by their own SHA-256. They are a PNG, and not the very
	// file that was dropped: the editor keeps its own encoding of an image.
	const bytes = await served.body();
	expect(createHash('sha256').update(bytes).digest('hex')).toBe(listed!.hash);
	expect(bytes.subarray(0, 8)).toEqual(file.subarray(0, 8));

	// A browser that loads the slot afterwards has the image from the head.
	const later = await person('Cy');
	later.on('request', watch('later'));
	await joinSlot(later, slot);
	await expectPainted(later, placed.id, color);
	expect(fetches()[1]).toBe(`later GET ${basePath}api/v1/assets/${listed!.hash}`);
	// Nobody uploaded it again: the file was the server's already.
	expect(transfers.filter((line) => line.includes(' POST '))).toHaveLength(1);
});

test('a deleted image is gone from the other browser, and its file is not fetched again', async ({
	page,
	person
}) => {
	const slot = SLOTS.images;
	const other = await person('Bea');
	await joinSlot(page, slot);
	await joinSlot(other, slot);
	// Its own color and place, apart from the three above.
	const { x } = PICTURES[test.info().project.name]!;
	const placed = await dropImage(page, png(60, 40, [20, 20, x % 256]), x, 520);
	await expect.poll(async () => (await imageOf(other, placed.id))?.mimeType).toBe('image/png');

	// A press on the image selects it, and puts the keyboard on the canvas.
	const canvas = (await page.locator('.excalidraw canvas.interactive').boundingBox())!;
	await page.mouse.click(
		canvas.x + placed.x + placed.width / 2,
		canvas.y + placed.y + placed.height / 2
	);
	await page.keyboard.press('Delete');

	await expect.poll(() => imageOf(page, placed.id)).toBeUndefined();
	await expect.poll(() => imageOf(other, placed.id)).toBeUndefined();
	await expectSaved(page);
	// A browser that loads the slot now does not ask for the deleted image's file.
	const later = await person('Cy');
	const fetched: string[] = [];
	later.on('request', (request) => {
		if (request.url().includes('/api/v1/assets/')) fetched.push(request.url());
	});
	await joinSlot(later, slot);
	await expect
		.poll(async () => (await canvasImages(later)).every((image) => image.mimeType !== null))
		.toBe(true);
	expect(await imageOf(later, placed.id)).toBeUndefined();
	// What it fetched is the files of the images that are still there.
	expect(fetched).toHaveLength((await canvasImages(later)).length);
});

test('a loaded slot shows its images although the socket never opens', async ({ page, person }) => {
	// The file list comes with the scene over HTTP, and needs no room.
	const slot = SLOTS.images;
	const { small, x } = PICTURES[test.info().project.name]!;
	await joinSlot(page, slot);
	const placed = await dropImage(page, png(60, 40, small), x, 610);
	await expectSaved(page);

	const cut = await person('Cy');
	await cut.routeWebSocket(/\/collab\?slot=\d$/, (route) => {
		void route.close({ code: 1001, reason: 'the test took the network away' });
	});
	await openSlot(cut, `s/${slot}`);

	await expect(connectionStatus(cut)).toHaveText('Disconnected');
	await expectPainted(cut, placed.id, small);
});
