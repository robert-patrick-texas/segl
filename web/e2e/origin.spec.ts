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
 * The Origin check in a real browser (docs/TEST-PLAN.md T-012,
 * docs/SECURITY.md): a page of another site cannot change a slot or open its
 * collaboration socket.
 *
 * "Another site" is this project's own page: the three projects reach one
 * segl at three origins, so a page of one is a cross-site page to the next.
 * The browser itself writes the `Origin` header, which no script can set.
 * This segl has no edit token, so the check is all that stands in the way.
 */
import { expect, type APIRequestContext, type Page } from '@playwright/test';
import { collabUrl, openSlot, SLOTS, test } from './pages.ts';
import { SITES } from './sites.ts';

/** The site each project's page asks, as a stranger. Both are behind nginx. */
const OTHER_SITE = { direct: SITES.root, root: SITES.board, board: SITES.root } as const;

function otherSite(): string {
	return OTHER_SITE[test.info().project.name as keyof typeof OTHER_SITE];
}

const EMPTY_SCENE = JSON.stringify({ type: 'excalidraw', version: 2, elements: [], files: {} });

/**
 * Send a request a page needs nobody's leave for: a `POST` whose body is
 * plain text. The page cannot read the answer, and the browser keeps its body
 * from the test too, and does not show the `Origin` header it added. The
 * status and the answer's headers are read off the wire.
 */
async function crossSitePost(
	page: Page,
	url: string,
	body: string | null
): Promise<{ status: number; headers: string[] }> {
	const answered = page.waitForResponse((response) => response.url() === url);
	await page.evaluate(
		([address, text]) => fetch(address, { method: 'POST', mode: 'no-cors', body: text }),
		[url, body] as const
	);
	const response = await answered;
	return { status: response.status(), headers: Object.keys(await response.allHeaders()) };
}

/** The same request from the test itself, which can read what segl answers that `Origin`. */
async function sameFromTheTest(
	request: APIRequestContext,
	url: string,
	origin: string,
	body: string | null
): Promise<{ status: number; error: string }> {
	const response = await request.post(url, {
		headers: { Origin: origin, 'Content-Type': 'text/plain;charset=UTF-8' },
		...(body === null ? {} : { data: body })
	});
	return { status: response.status(), error: ((await response.json()) as { error: string }).error };
}

test('a request from a page of another site is refused with bad_origin, and changes nothing', async ({
	page,
	request,
	baseURL
}) => {
	// T-012.
	const slot = SLOTS.empty;
	const site = otherSite();
	const own = new URL(baseURL!).origin;
	expect(new URL(site).origin).not.toBe(own);
	await openSlot(page, `s/${slot}`);
	const slotUrl = new URL(`api/v1/slots/${slot}`, site).href;
	const before = await (await request.get(slotUrl)).json();

	// An import: it would replace the slot's scene for everyone. This segl
	// has no edit token, so the only thing it answers `403` for is the origin:
	// the browser sent this page's, and it was refused.
	const imported = await crossSitePost(page, `${slotUrl}/import`, EMPTY_SCENE);
	expect(imported.status).toBe(403);
	expect(await sameFromTheTest(request, `${slotUrl}/import`, own, EMPTY_SCENE)).toEqual({
		status: 403,
		error: 'bad_origin'
	});
	// A display name: it would use up one of this address's thirty a minute.
	const nameUrl = new URL('api/v1/display-name', site).href;
	const named = await crossSitePost(page, nameUrl, null);
	expect(named.status).toBe(403);
	expect(await sameFromTheTest(request, nameUrl, own, null)).toEqual({
		status: 403,
		error: 'bad_origin'
	});
	// Neither answer sets a cookie or gives the other site leave to read it.
	for (const answer of [imported, named]) {
		expect(answer.headers).not.toContain('set-cookie');
		expect(answer.headers.filter((name) => name.startsWith('access-control-'))).toEqual([]);
	}

	// A title change is a request the browser asks leave for first. segl gives
	// none, so it is never sent.
	const patched = await page.evaluate(async (address) => {
		try {
			await fetch(address, {
				method: 'PATCH',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ title: 'Taken over' })
			});
			return 'sent';
		} catch {
			return 'not sent';
		}
	}, slotUrl);
	expect(patched).toBe('not sent');
	// And a page of another site cannot read a slot: segl sends no CORS header.
	const read = await page.evaluate(async (address) => {
		try {
			return (await fetch(address)).status;
		} catch {
			return 'not readable';
		}
	}, slotUrl);
	expect(read).toBe('not readable');

	expect(await (await request.get(slotUrl)).json()).toEqual(before);
});

test("a page of another site cannot open the collaboration socket, and the site's own page can", async ({
	page,
	context
}) => {
	// T-012. A browser applies no same-origin rule to a WebSocket, so the
	// server's check in the handshake is the only one there is.
	const slot = SLOTS.empty;
	const site = otherSite();
	const url = collabUrl(site, slot);
	const tryOpen = (from: Page) =>
		from.evaluate(
			(address) =>
				new Promise<string>((resolve) => {
					const socket = new WebSocket(address);
					socket.onopen = () => {
						socket.close();
						resolve('opened');
					};
					socket.onclose = (event) => resolve(`closed ${event.code}`);
				}),
			url
		);
	await openSlot(page, `s/${slot}`);

	// Refused in the handshake: the socket never opens.
	expect(await tryOpen(page)).toBe('closed 1006');

	// The same address from a page of the site it belongs to.
	const own = await context.newPage();
	await openSlot(own, new URL(`s/${slot}`, site).href);
	expect(await tryOpen(own)).toBe('opened');
});
