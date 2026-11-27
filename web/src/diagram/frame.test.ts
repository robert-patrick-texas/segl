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

import { describe, expect, test } from 'vitest';
import {
	DiagramFrame,
	drawioAddress,
	EMBED_PARAMETERS,
	viewOf,
	type DiagramEdit
} from './frame.ts';

const ORIGIN = 'https://dev.example.com';

/** drawio's window: what the adapter posted to it. */
class FakeWindow {
	readonly posted: Record<string, unknown>[] = [];
	readonly origins: string[] = [];

	postMessage(message: string, targetOrigin: string): void {
		this.posted.push(JSON.parse(message) as Record<string, unknown>);
		this.origins.push(targetOrigin);
	}

	take(): Record<string, unknown>[] {
		return this.posted.splice(0);
	}
}

function setUp() {
	const window = new FakeWindow();
	const edits: DiagramEdit[] = [];
	const frame = new DiagramFrame({
		target: () => window,
		origin: ORIGIN,
		onEdit: (edit) => edits.push(edit)
	});
	/** drawio said something. */
	const say = (message: unknown, source: unknown = window, origin = ORIGIN) =>
		frame.handle({ source, origin, data: JSON.stringify(message) });
	return { window, edits, frame, say };
}

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

describe('the adapter takes messages only from its own frame', () => {
	test('a message from another window or another origin is ignored', async () => {
		const { window, frame, say } = setUp();
		let ready = false;
		void frame.ready.then(() => (ready = true));

		say({ event: 'init' }, {});
		say({ event: 'init' }, window, 'https://other.example.net');
		await flush();
		expect(ready).toBe(false);

		say({ event: 'init' });
		await flush();
		expect(ready).toBe(true);
	});

	test('text that is not a JSON object is ignored', () => {
		const { frame, window, edits } = setUp();

		for (const data of ['not json', '[1]', 'null', '7', { event: 'autosave' }]) {
			frame.handle({ source: window, origin: ORIGIN, data });
		}

		expect(edits).toEqual([]);
	});

	test('an edit from another window is not taken', () => {
		const { say, edits } = setUp();

		say({ event: 'autosave', patch: {}, checksum: 1, xml: '<mxfile/>' }, {});

		expect(edits).toEqual([]);
	});
});

describe('actions go one at a time, once drawio is ready', () => {
	test('nothing is posted before drawio says init', async () => {
		const { window, frame, say } = setUp();

		const loaded = frame.load('<mxfile/>', false);
		expect(window.take()).toEqual([]);

		say({ event: 'init' });
		expect(window.take()).toEqual([
			{ action: 'load', xml: '<mxfile/>', autosave: 1, diffSync: true, readOnly: false }
		]);
		say({ event: 'load', xml: '<mxfile/>' });
		await loaded;
	});

	test('a patch waits for the load before it, and each for its answer', async () => {
		const { window, frame, say } = setUp();
		say({ event: 'init' });

		const loaded = frame.load('<mxfile/>', true);
		const first = frame.patch({ a: 1 }, 42);
		const second = frame.patch({ b: 2 }, null);
		expect(window.take().map((m) => m['action'])).toEqual(['load']);

		say({ event: 'load' });
		await loaded;
		expect(window.take()).toEqual([{ action: 'patch', patch: { a: 1 }, checksum: 42 }]);

		say({ event: 'patch', checksum: 42 });
		expect(await first).toEqual({ mismatch: false, error: null });
		// No checksum: drawio has nothing to compare.
		expect(window.take()).toEqual([{ action: 'patch', patch: { b: 2 } }]);

		say({ event: 'patch', checksum: 9, checksumMismatch: true });
		expect(await second).toEqual({ mismatch: true, error: null });
	});

	test('a patch drawio could not apply says why', async () => {
		const { frame, say } = setUp();
		say({ event: 'init' });

		const result = frame.patch({ a: 1 }, null);
		say({ event: 'patch', error: 'no such cell' });

		expect(await result).toEqual({ mismatch: false, error: 'no such cell' });
	});

	test('xml() asks drawio for its whole diagram', async () => {
		const { window, frame, say } = setUp();
		say({ event: 'init' });

		const xml = frame.xml();
		expect(window.take()).toEqual([{ action: 'export', format: 'xml' }]);
		say({ event: 'export', format: 'xml', xml: '<mxfile>x</mxfile>' });

		expect(await xml).toBe('<mxfile>x</mxfile>');
	});

	test('an answer to an action not asked is ignored', async () => {
		const { window, frame, say } = setUp();
		say({ event: 'init' });

		const loaded = frame.load('<mxfile/>', false);
		window.take();
		say({ event: 'patch' });
		const patched = frame.patch({ a: 1 }, null);
		expect(window.take()).toEqual([]);

		say({ event: 'load' });
		await loaded;
		say({ event: 'patch' });
		await patched;
	});

	test('everything goes to segl’s own origin', () => {
		const { window, frame, say } = setUp();
		say({ event: 'init' });

		void frame.xml();

		expect(window.origins).toEqual([ORIGIN]);
	});
});

describe('the person’s edits', () => {
	test('an autosave with a patch is an edit with its patch, checksum, and diagram', () => {
		const { say, edits } = setUp();

		say({ event: 'autosave', patch: { u: {} }, checksum: -5, xml: '<mxfile>1</mxfile>' });

		expect(edits).toEqual([{ patch: { u: {} }, checksum: -5, xml: '<mxfile>1</mxfile>' }]);
	});

	test('an autosave without a patch is a change outside the pages', () => {
		const { say, edits } = setUp();

		say({ event: 'autosave', xml: '<mxfile>2</mxfile>' });

		expect(edits).toEqual([{ patch: null, checksum: null, xml: '<mxfile>2</mxfile>' }]);
	});

	test('an autosave without the diagram is not an edit', () => {
		const { say, edits } = setUp();

		say({ event: 'autosave', patch: { u: {} }, checksum: 1 });

		expect(edits).toEqual([]);
	});
});

describe('the read-only view', () => {
	const toggle = { action: 'invokeAction', actionName: 'readOnly' };

	test('nothing is toggled before drawio has said where it is', () => {
		const { window, frame, say } = setUp();
		say({ event: 'init' });

		frame.setReadOnly(true);

		expect(window.take()).toEqual([]);
	});

	test('drawio is turned read-only when it is not, and back', () => {
		const { window, frame, say } = setUp();
		say({ event: 'init' });
		say({ event: 'readOnly', readOnly: false });

		frame.setReadOnly(true);
		frame.setReadOnly(true);
		expect(window.take()).toEqual([toggle]);

		say({ event: 'readOnly', readOnly: true });
		frame.setReadOnly(false);
		expect(window.take()).toEqual([toggle]);
	});

	test('a person who turns it off by drawio’s menu has it turned back', () => {
		const { window, frame, say } = setUp();
		say({ event: 'init' });
		frame.setReadOnly(true);
		say({ event: 'readOnly', readOnly: true });
		expect(window.take()).toEqual([]);

		say({ event: 'readOnly', readOnly: false });

		expect(window.take()).toEqual([toggle]);
	});

	test('a load carries the read-only view the page wants', async () => {
		const { window, frame, say } = setUp();
		say({ event: 'init' });

		void frame.load('<mxfile/>', true);

		expect(window.take()[0]?.['readOnly']).toBe(true);
	});
});

test('drawio’s page is under segl’s root, in embed mode, with nothing outside', () => {
	expect(drawioAddress(new URL('https://dev.example.com/board/'))).toBe(
		`https://dev.example.com/board/drawio/index.html?${EMBED_PARAMETERS}`
	);
	expect(drawioAddress(new URL('https://board.example.com/'))).toBe(
		`https://board.example.com/drawio/index.html?${EMBED_PARAMETERS}`
	);
	const parameters = new URLSearchParams(EMBED_PARAMETERS);
	expect(Object.fromEntries(parameters)).toMatchObject({
		embed: '1',
		proto: 'json',
		stealth: '1',
		lockdown: '1',
		pwa: '0'
	});
	// offline=1 would turn on drawio's service worker.
	expect(parameters.has('offline')).toBe(false);
});

describe('a person’s view and typing', () => {
	test('idle waits while a label is being edited', async () => {
		const { frame, say } = setUp();
		let idle = false;

		await frame.idle();
		say({ event: 'editing', editing: true });
		void frame.idle().then(() => (idle = true));
		await flush();
		expect(idle).toBe(false);

		say({ event: 'editing', editing: false });
		await flush();
		expect(idle).toBe(true);
	});

	test('the view is the scale and the point at the top left', async () => {
		const { frame, say } = setUp();
		say({ event: 'init' });

		const view = frame.view();
		say({
			event: 'export',
			xml: '<m/>',
			scale: 2,
			translate: { x: 10, y: 20 },
			scroll: { left: 300, top: 100 }
		});

		expect(await view).toEqual({ scale: 2, x: 140, y: 30 });
	});

	test('an answer without segl’s scroll gives no view', () => {
		expect(viewOf({ scale: 1, translate: { x: 0, y: 0 } })).toBeNull();
		expect(viewOf({ scale: 0, translate: { x: 0, y: 0 }, scroll: { left: 0, top: 0 } })).toBeNull();
		expect(viewOf({ scale: 1, translate: null, scroll: { left: 0, top: 0 } })).toBeNull();
		expect(
			viewOf({ scale: 1, translate: { x: 0, y: 0 }, scroll: { left: 'a', top: 0 } })
		).toBeNull();
	});

	test('a load with a view asks drawio to scale and scroll to it', () => {
		const { window, frame, say } = setUp();
		say({ event: 'init' });

		void frame.load('<m/>', false, { scale: 1.5, x: 40, y: 60 });

		expect(window.take()).toEqual([
			{
				action: 'load',
				xml: '<m/>',
				autosave: 1,
				diffSync: true,
				readOnly: false,
				scale: 1.5,
				scroll: { x: 40, y: 60 }
			}
		]);
	});
});
