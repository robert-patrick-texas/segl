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
import type { Cursor, View } from '../collab/protocol.ts';
import {
	DiagramFrame,
	drawioAddress,
	EMBED_PARAMETERS,
	parseSelection,
	SELECTION_LIMIT,
	viewOf,
	type DiagramEdit,
	type FrameSelection,
	type Selection
} from './frame.ts';

const ORIGIN = 'https://dev.example.com';

/** drawio's window: what the adapter posted to it. */
class FakeWindow {
	readonly posted: Record<string, unknown>[] = [];
	readonly origins: string[] = [];
	/** segl's own messages, which go as objects and not as text. */
	readonly objects: Record<string, unknown>[] = [];
	/** Both kinds in the order posted: drawio's action, or segl's message. */
	readonly order: string[] = [];

	postMessage(message: unknown, targetOrigin: string): void {
		if (typeof message === 'string') {
			const action = JSON.parse(message) as Record<string, unknown>;
			this.posted.push(action);
			this.order.push(String(action['action']));
		} else {
			const own = message as Record<string, unknown>;
			this.objects.push(own);
			this.order.push(`segl:${String(own['segl'])}`);
		}
		this.origins.push(targetOrigin);
	}

	take(): Record<string, unknown>[] {
		return this.posted.splice(0);
	}
}

function setUp() {
	const window = new FakeWindow();
	const edits: DiagramEdit[] = [];
	const views: View[] = [];
	const pointers: Cursor[] = [];
	const selections: (Selection | null)[] = [];
	let looks = 0;
	const frame = new DiagramFrame({
		target: () => window,
		origin: ORIGIN,
		onEdit: (edit) => edits.push(edit),
		onView: (view) => views.push(view),
		onPointer: (cursor) => pointers.push(cursor),
		onLooked: () => (looks += 1),
		onSelection: (selection) => selections.push(selection)
	});
	/** drawio said something. */
	const say = (message: unknown, source: unknown = window, origin = ORIGIN) =>
		frame.handle({ source, origin, data: JSON.stringify(message) });
	return { window, edits, frame, say, views, pointers, selections, looks: () => looks };
}

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

/** Whether a promise settles within a short, bounded wait. */
const settles = (promise: Promise<unknown>, ms = 50) =>
	Promise.race([
		promise.then(() => true),
		new Promise<boolean>((resolve) => setTimeout(() => resolve(false), ms))
	]);

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
			scroll: { left: 300, top: 100 },
			currentPage: 2,
			pageId: 'page-3'
		});

		expect(await view).toEqual({ scale: 2, x: 140, y: 30, page: 'page-3' });
	});

	test('the view names no page when PostConfig.js gave no page id', () => {
		const answer = { scale: 1, translate: { x: 0, y: 0 }, scroll: { left: 0, top: 0 } };

		for (const pageId of [undefined, null, '', 7, { id: 'p' }]) {
			expect(viewOf({ ...answer, currentPage: 0, pageId })).toEqual({
				scale: 1,
				x: 0,
				y: 0,
				page: null
			});
		}
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

		void frame.load('<m/>', false, { scale: 1.5, x: 40, y: 60, page: 'page-3' });

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

	test('a load with a view first tells PostConfig.js the page and view to come back to', () => {
		const { window, frame, say } = setUp();
		say({ event: 'init' });
		const view = { scale: 0.5, x: -10, y: 300, page: 'page-3' };

		void frame.load('<m/>', false, view);

		expect(window.objects).toEqual([{ segl: 'keep', view }]);
		expect(window.order).toEqual(['segl:keep', 'load']);
		expect(window.origins).toEqual([ORIGIN, ORIGIN]);
	});

	test('a load without a view, as at a join, keeps nothing', () => {
		const { window, frame, say } = setUp();
		say({ event: 'init' });

		void frame.load('<m/>', true);

		expect(window.objects).toEqual([]);
		expect(window.order).toEqual(['load']);
	});

	test('the view to come back to goes just before its load, not when the load is asked', async () => {
		const { window, frame, say } = setUp();
		say({ event: 'init' });
		const view = { scale: 1, x: 0, y: 0, page: 'p' };

		const patched = frame.patch({ a: 1 }, null);
		void frame.load('<m/>', false, view);
		expect(window.order).toEqual(['patch']);

		say({ event: 'patch' });
		expect(await settles(patched)).toBe(true);
		expect(window.order).toEqual(['patch', 'segl:keep', 'load']);
	});
});

describe('a press in the frame (T19)', () => {
	test('idle waits while a press is held, and settles at its end', async () => {
		const { frame, say } = setUp();
		let idle = false;

		say({ event: 'press', pressed: true });
		void frame.idle().then(() => (idle = true));
		await flush();
		expect(idle).toBe(false);

		say({ event: 'press', pressed: false });
		await flush();
		expect(idle).toBe(true);
	});

	test('idle waits for both a press and a label editor to end', async () => {
		const { frame, say } = setUp();
		let idle = false;
		say({ event: 'editing', editing: true });
		say({ event: 'press', pressed: true });
		void frame.idle().then(() => (idle = true));

		say({ event: 'press', pressed: false });
		await flush();
		expect(idle).toBe(false);

		say({ event: 'press', pressed: true });
		say({ event: 'editing', editing: false });
		await flush();
		expect(idle).toBe(false);

		say({ event: 'press', pressed: false });
		await flush();
		expect(idle).toBe(true);
	});

	test('a press report that is not true is no press', async () => {
		const { frame, say } = setUp();

		say({ event: 'press', pressed: true });
		say({ event: 'press', pressed: 'yes' });

		expect(await settles(frame.idle())).toBe(true);
	});

	test('a press from another window holds nothing', async () => {
		const { frame, say } = setUp();

		say({ event: 'press', pressed: true }, {});
		say({ event: 'editing', editing: true }, {}, ORIGIN);

		expect(await settles(frame.idle())).toBe(true);
	});

	test('a load waits for a press to end, and what comes after it waits too', async () => {
		const { window, frame, say } = setUp();
		say({ event: 'init' });
		say({ event: 'press', pressed: true });

		const loaded = frame.load('<m/>', false, { scale: 1, x: 0, y: 0, page: 'p' });
		const patched = frame.patch({ a: 1 }, null);
		await flush();
		expect(window.order).toEqual([]);

		say({ event: 'press', pressed: false });
		expect(window.order).toEqual(['segl:keep', 'load']);
		say({ event: 'load' });
		expect(await settles(loaded)).toBe(true);
		expect(window.order).toEqual(['segl:keep', 'load', 'patch']);
		say({ event: 'patch' });
		expect(await settles(patched)).toBe(true);
	});

	test('a load waits for a label editor to close, even without a view', async () => {
		const { window, frame, say } = setUp();
		say({ event: 'init' });
		say({ event: 'editing', editing: true });

		const loaded = frame.load('<m/>', false);
		await flush();
		expect(window.order).toEqual([]);

		say({ event: 'editing', editing: false });
		expect(window.order).toEqual(['load']);
		say({ event: 'load' });
		expect(await settles(loaded)).toBe(true);
	});

	test('a patch or an export is not held by a press', async () => {
		const { window, frame, say } = setUp();
		say({ event: 'init' });
		say({ event: 'press', pressed: true });
		say({ event: 'editing', editing: true });

		const patched = frame.patch({ a: 1 }, null);
		expect(window.order).toEqual(['patch']);
		say({ event: 'patch' });
		expect(await settles(patched)).toBe(true);
		void frame.xml();
		expect(window.order).toEqual(['patch', 'export']);
	});
});

describe('selections (T19)', () => {
	test('this browser’s selection reaches the page as PostConfig.js reports it', () => {
		const { say, selections } = setUp();

		say({ event: 'selection', selection: { page: 'page-3', cells: ['a', 'b'] } });
		say({ event: 'selection', selection: null });

		expect(selections).toEqual([{ page: 'page-3', cells: ['a', 'b'] }, null]);
	});

	test('a report that is not one, or from another window, is dropped', () => {
		const { say, selections } = setUp();

		say({ event: 'selection' });
		say({ event: 'selection', selection: 'a' });
		say({ event: 'selection', selection: ['a'] });
		say({ event: 'selection', selection: { page: 'p' } });
		say({ event: 'selection', selection: { page: 'p', cells: 'a' } });
		say({ event: 'selection', selection: { page: 'p', cells: ['a'] } }, {});
		say({ event: 'selection', selection: null }, undefined, 'https://other.example.net');

		expect(selections).toEqual([]);
	});

	test('none, or more than 50 cells, is null', () => {
		const many = Array.from({ length: SELECTION_LIMIT + 1 }, (_, i) => `c${i}`);

		expect(SELECTION_LIMIT).toBe(50);
		expect(parseSelection(null)).toBeNull();
		expect(parseSelection({ page: 'p', cells: [] })).toBeNull();
		expect(parseSelection({ page: 'p', cells: many })).toBeNull();
		expect(parseSelection({ page: 'p', cells: many.slice(0, 50) })?.cells).toHaveLength(50);
	});

	test('an id the server would refuse is left out, and a page id becomes null', () => {
		const long = 'x'.repeat(129);
		const longest = 'y'.repeat(128);

		expect(
			parseSelection({ page: longest, cells: ['a', '', long, 7, null, longest, 'a'] })
		).toEqual({ page: longest, cells: ['a', longest] });
		for (const page of [long, '', 7, undefined, null]) {
			expect(parseSelection({ page, cells: ['a'] })).toEqual({ page: null, cells: ['a'] });
		}
		expect(parseSelection({ page: 'p', cells: [long, '', 3] })).toBeNull();
		for (const value of [undefined, 'a', 7, ['a'], {}, { cells: { 0: 'a' } }]) {
			expect(parseSelection(value)).toBeUndefined();
		}
	});

	test('the others’ selections go to the frame as segl’s own object', async () => {
		const { window, frame, say } = setUp();
		const shown: FrameSelection[] = [
			{ id: 'b', color: 'hsl(0, 100%, 83%)', page: 'page-3', cells: ['c1', 'c2'] }
		];
		say({ event: 'init' });
		await flush();

		frame.showSelections(shown);
		frame.showSelections([]);

		expect(window.objects).toEqual([
			{ segl: 'selections', selections: shown },
			{ segl: 'selections', selections: [] }
		]);
		expect(window.origins).toEqual([ORIGIN, ORIGIN]);
		// None of drawio's actions was posted for them.
		expect(window.take()).toEqual([]);
	});

	test('a list given before drawio is ready goes once it is', async () => {
		const { window, frame, say } = setUp();
		const first: FrameSelection[] = [{ id: 'b', color: 'red', page: null, cells: ['c1'] }];
		const last: FrameSelection[] = [{ id: 'c', color: 'blue', page: 'p', cells: ['c2'] }];

		frame.showSelections(first);
		frame.showSelections(last);
		expect(window.objects).toEqual([]);

		say({ event: 'init' });
		await flush();
		expect(window.objects).toEqual([{ segl: 'selections', selections: last }]);
	});
});

describe('follow mode and cursors (T18)', () => {
	const AREA = { x: -5, y: 10, width: 640, height: 480, page: 'segl-page-1' };

	test('the view, the pointer, and a look of the person’s own reach the page', () => {
		const { say, views, pointers, looks } = setUp();

		say({ event: 'view', view: AREA });
		say({ event: 'pointer', x: 12.5, y: -3, page: 'segl-page-1' });
		say({ event: 'pointer', x: 1, y: 2, page: null });
		say({ event: 'looked' });

		expect(views).toEqual([AREA]);
		expect(pointers).toEqual([
			{ x: 12.5, y: -3, page: 'segl-page-1' },
			{ x: 1, y: 2, page: null }
		]);
		expect(looks()).toBe(1);
	});

	test('a report that is not one, or from another window, is dropped', () => {
		const { say, views, pointers, looks } = setUp();

		say({ event: 'view', view: { ...AREA, width: 0 } });
		say({ event: 'view' });
		say({ event: 'pointer', x: 'left', y: 2 });
		say({ event: 'view', view: AREA }, {});
		say({ event: 'looked' }, {}, ORIGIN);
		say({ event: 'pointer', x: 1, y: 2 }, undefined, 'https://other.example.net');

		expect(views).toEqual([]);
		expect(pointers).toEqual([]);
		expect(looks()).toBe(0);
	});

	test('a view to show and the cursors to draw go to the frame as segl’s own objects', async () => {
		const { window, frame, say } = setUp();
		const cursor = { id: 'b', name: 'Bea', color: 'hsl(0, 100%, 83%)', x: 1, y: 2, page: null };

		// Not before drawio is ready: nothing in the frame would take them.
		frame.showView(AREA);
		expect(window.objects).toEqual([]);
		say({ event: 'init' });
		await flush();

		frame.showView(AREA);
		frame.showCursors([cursor]);

		expect(window.objects).toEqual([
			{ segl: 'view', view: AREA },
			{ segl: 'cursors', cursors: [cursor] }
		]);
		expect(window.origins.at(-1)).toBe(ORIGIN);
		// None of drawio's actions was posted for them.
		expect(window.take()).toEqual([]);
	});
});
