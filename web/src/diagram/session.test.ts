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

import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import type { View } from '../collab/protocol.ts';
import { CURSOR_INTERVAL_MS, RETRY_DELAYS_MS, type SocketLike } from '../collab/session.ts';
import { cursorColor, type FrameCursor } from './cursors.ts';
import type { DiagramFrameLike, DiagramView, PatchResult } from './frame.ts';
import type { DrawioPatch, NumberedPatch } from './protocol.ts';
import { DiagramSession, type DiagramState } from './session.ts';

const URL = 'wss://dev.example.com/board/collab?slot=9';
const HEAD = '<mxfile>head</mxfile>';

class FakeSocket implements SocketLike {
	onopen: SocketLike['onopen'] = null;
	onmessage: SocketLike['onmessage'] = null;
	onclose: SocketLike['onclose'] = null;
	readonly sent: Record<string, unknown>[] = [];
	closed = false;

	send(text: string): void {
		this.sent.push(JSON.parse(text) as Record<string, unknown>);
	}

	close(): void {
		this.closed = true;
	}

	open(): void {
		this.onopen?.({});
	}

	receive(message: unknown): void {
		this.onmessage?.({ data: JSON.stringify(message) });
	}

	drop(): void {
		this.onclose?.({});
	}

	/** What was sent since the last call, without the hello. */
	take(): Record<string, unknown>[] {
		return this.sent.splice(0).filter((message) => message['type'] !== 'hello');
	}
}

/** drawio's frame: what was loaded and patched, in order. */
class FakeFrame implements DiagramFrameLike {
	readonly ready = Promise.resolve();
	readonly calls: string[] = [];
	readOnly: boolean | null = null;
	diagram = HEAD;
	/** What the next patch says. */
	results: PatchResult[] = [];
	readonly checksums: (number | null)[] = [];

	/** While a label is being edited: what ends the editing. */
	endEditing: (() => void) | null = null;
	views: (DiagramView | null)[] = [];

	async load(xml: string, readOnly: boolean, view: DiagramView | null = null): Promise<void> {
		this.calls.push(`load ${xml}${readOnly ? ' read-only' : ''}`);
		this.views.push(view);
		this.diagram = xml;
	}

	async view(): Promise<DiagramView | null> {
		return { scale: 1.5, x: 40, y: 60 };
	}

	editing: Promise<void> | null = null;

	idle(): Promise<void> {
		return this.editing ?? Promise.resolve();
	}

	/** A person starts typing a label. */
	type(): void {
		this.editing = new Promise((resolve) => {
			this.endEditing = () => {
				this.editing = null;
				resolve();
			};
		});
	}

	async patch(patch: DrawioPatch, checksum: number | null): Promise<PatchResult> {
		this.calls.push(`patch ${String(patch['label'])}`);
		this.checksums.push(checksum);
		return this.results.shift() ?? { mismatch: false, error: null };
	}

	async xml(): Promise<string> {
		return this.diagram;
	}

	setReadOnly(value: boolean): void {
		this.readOnly = value;
	}

	/** The views shown, and the cursors drawn each time, in order. */
	readonly shown: (View | null)[] = [];
	readonly drawn: FrameCursor[][] = [];

	showView(view: View | null): void {
		this.shown.push(view);
	}

	showCursors(cursors: readonly FrameCursor[]): void {
		this.drawn.push([...cursors]);
	}
}

function patchOf(label: string): DrawioPatch {
	return { label };
}

function numbered(
	n: number,
	pid: string,
	exact = true,
	checksum: number | null = 7
): NumberedPatch {
	return { n, pid, patch: patchOf(pid), checksum, exact };
}

function welcome(connectionId = 'me', more: Record<string, unknown> = {}) {
	return {
		type: 'welcome',
		slot: 9,
		title: 'Workspace 9',
		epoch: 1,
		viewOnly: false,
		editEndsIn: null,
		connectionId,
		participants: [{ connectionId, displayName: 'Alpha1' }],
		pen: null,
		...more
	};
}

function since(count: number, patches: NumberedPatch[] = []) {
	return { type: 'diagram', epoch: 1, whole: false, mark: `s.1.${count}`, count, patches };
}

function whole(xml: string, count: number, patches: NumberedPatch[] = []) {
	return { type: 'diagram', epoch: 1, whole: true, mark: `s.1.${count}`, count, xml, patches };
}

function live(entry: NumberedPatch) {
	return { type: 'patch', epoch: 1, mark: `s.1.${entry.n}`, ...entry };
}

let sockets: FakeSocket[];
let frame: FakeFrame;
let states: DiagramState[];
let session: DiagramSession;
let ids: number;

function start(options: { editRequired?: boolean } = {}): FakeSocket {
	session = new DiagramSession({
		url: URL,
		epoch: 1,
		xml: HEAD,
		mark: 's.1.0',
		frame,
		editRequired: options.editRequired ?? false,
		hello: () => ({ clientId: 'c', displayName: 'Alpha1', editToken: '' }),
		onState: (state) => states.push(state),
		createSocket: () => {
			const socket = new FakeSocket();
			sockets.push(socket);
			return socket;
		},
		newId: () => `mine-${(ids += 1)}`
	});
	session.start();
	const socket = sockets.at(-1)!;
	socket.open();
	return socket;
}

/** Let the session's queue of work on the frame run. */
async function settle(): Promise<void> {
	for (let i = 0; i < 20; i += 1) await Promise.resolve();
}

function edit(label: string, xml = `<mxfile>${label}</mxfile>`) {
	frame.diagram = xml;
	session.edit({ patch: patchOf(label), checksum: 11, xml });
}

beforeEach(() => {
	sockets = [];
	frame = new FakeFrame();
	states = [];
	ids = 0;
});

afterEach(() => {
	session.stop();
	vi.useRealTimers();
});

describe('joining', () => {
	test('the frame is loaded with the page’s head, and hello hands back its mark', async () => {
		const socket = start();
		await settle();

		expect(frame.calls).toEqual([`load ${HEAD}`]);
		expect(socket.sent[0]).toMatchObject({ type: 'hello', mark: 's.1.0' });
	});

	test('the patches since the mark are applied in order, and its own are not', async () => {
		const socket = start();
		socket.receive(welcome());
		session.edit({ patch: patchOf('mine-1'), checksum: 1, xml: '<mxfile/>' });
		socket.receive(since(0, [numbered(1, 'b1'), numbered(2, 'mine-1'), numbered(3, 'c1')]));
		await settle();

		expect(frame.calls.slice(1)).toEqual(['patch b1', 'patch c1']);
		edit('next');
		expect(socket.take()).toMatchObject([{ type: 'patch', base: 3, pid: 'mine-2' }]);
	});

	test('an edit made before this connection is in step waits for it', async () => {
		const socket = start();
		await settle();
		edit('early');
		socket.receive(welcome());
		expect(socket.take()).toEqual([]);

		socket.receive(since(4));
		await settle();

		expect(socket.take()).toMatchObject([
			{ type: 'patch', epoch: 1, base: 4, pid: 'mine-1', xml: '<mxfile>early</mxfile>', seq: 1 }
		]);
	});

	test('an edit made while the join is worked through is sent once', async () => {
		const socket = start();
		await settle();
		socket.receive(welcome());
		socket.receive(since(0, [numbered(1, 'b1')]));
		// The join's patches are still being applied when the person draws.
		edit('during');
		await settle();
		edit('after');

		expect(socket.take().map((m) => [m['pid'], m['base']])).toEqual([
			['mine-1', 1],
			['mine-2', 1]
		]);
	});

	test('a whole diagram replaces the frame’s, with every patch after it', async () => {
		const socket = start();
		socket.receive(welcome());
		socket.receive(whole('<mxfile>copy</mxfile>', 5, [numbered(6, 'b6')]));
		await settle();

		expect(frame.calls.slice(1)).toEqual(['load <mxfile>copy</mxfile>', 'patch b6']);
	});
});

describe('patches as they come', () => {
	async function joined(): Promise<FakeSocket> {
		const socket = start();
		socket.receive(welcome());
		socket.receive(since(0));
		await settle();
		socket.take();
		frame.calls.length = 0;
		return socket;
	}

	test('another browser’s patches are applied in the order the server numbered them', async () => {
		const socket = await joined();

		socket.receive(live(numbered(1, 'b1')));
		socket.receive(live(numbered(2, 'c1')));
		socket.receive(live(numbered(2, 'c1')));
		await settle();

		expect(frame.calls).toEqual(['patch b1', 'patch c1']);
	});

	test('a page’s own patch is not applied again when it comes back', async () => {
		const socket = await joined();
		edit('a');
		socket.receive(live(numbered(1, 'mine-1')));
		await settle();

		expect(frame.calls).toEqual([]);
		edit('b');
		expect(socket.take()).toMatchObject([
			{ pid: 'mine-1', base: 0 },
			{ pid: 'mine-2', base: 1 }
		]);
	});

	test('its own patch that was not exact is followed by a copy', async () => {
		const socket = await joined();
		edit('a');
		socket.take();

		socket.receive(live(numbered(1, 'b1')));
		socket.receive(live(numbered(2, 'mine-1', false)));
		await settle();

		expect(socket.take()).toEqual([{ type: 'copy', epoch: 1, base: 2, xml: '<mxfile>a</mxfile>' }]);
	});

	test('the checksum is compared only when it can be the whole diagram’s', async () => {
		const socket = await joined();

		socket.receive(live(numbered(1, 'b1', true, 21)));
		socket.receive(live(numbered(2, 'b2', false, 22)));
		socket.receive(live(numbered(3, 'b3', true, null)));
		await settle();
		edit('a');
		socket.receive(live(numbered(4, 'b4', true, 24)));
		await settle();

		expect(frame.checksums).toEqual([21, null, null, null]);
	});

	test('a checksum that does not match asks for the whole diagram, and loads it', async () => {
		const socket = await joined();
		frame.results = [{ mismatch: true, error: null }];

		socket.receive(live(numbered(1, 'b1')));
		await settle();
		expect(socket.take()).toEqual([{ type: 'reload' }]);

		// What comes before the whole diagram is in it.
		socket.receive(live(numbered(2, 'b2')));
		socket.receive(whole('<mxfile>copy</mxfile>', 1, [numbered(2, 'b2')]));
		await settle();

		expect(frame.calls).toEqual(['patch b1', 'load <mxfile>copy</mxfile>', 'patch b2']);
		expect(JSON.parse(JSON.stringify(session.counts))).toEqual({ mismatches: 1, reloads: 1 });
		// The person keeps looking where they were.
		expect(frame.views.at(-1)).toEqual({ scale: 1.5, x: 40, y: 60 });
	});

	test('the whole diagram is asked for only once no label is being edited', async () => {
		const socket = await joined();
		frame.results = [{ mismatch: true, error: null }];
		frame.type();

		socket.receive(live(numbered(1, 'b1')));
		await settle();
		expect(socket.take()).toEqual([]);

		frame.endEditing?.();
		await settle();
		expect(socket.take()).toEqual([{ type: 'reload' }]);
	});

	test('its own patch that comes back while it waits for the whole diagram is not lost', async () => {
		const socket = await joined();
		edit('a');
		socket.take();
		frame.results = [{ mismatch: false, error: 'no such cell' }];
		socket.receive(live(numbered(1, 'b1')));
		await settle();
		expect(socket.take()).toEqual([{ type: 'reload' }]);

		// Taken, not exact, and then held in the copy the whole diagram brings.
		socket.receive(live(numbered(2, 'mine-1', false)));
		socket.receive(whole('<mxfile>copy</mxfile>', 2));
		await settle();

		expect(frame.calls.slice(-1)).toEqual(['load <mxfile>copy</mxfile>']);
		expect(socket.take()).toEqual([
			{ type: 'copy', epoch: 1, base: 2, xml: '<mxfile>copy</mxfile>' }
		]);
		socket.receive({ type: 'saved', epoch: 1, savedAt: '2026-11-27T10:00:00.000Z', seq: 1 });
		expect(states.at(-1)?.status).toBe('saved');
	});

	test('a patch drawio could not apply asks for the whole diagram', async () => {
		const socket = await joined();
		frame.results = [{ mismatch: false, error: 'no such cell' }];

		socket.receive(live(numbered(1, 'b1', false)));
		await settle();

		expect(socket.take()).toEqual([{ type: 'reload' }]);
	});
});

describe('the pen', () => {
	test('the frame is read-only while someone else holds the pen, and back after', async () => {
		const socket = start();
		socket.receive(welcome('me', { pen: 'other' }));
		expect(frame.readOnly).toBe(true);

		socket.receive({ type: 'pen', holder: null });
		expect(frame.readOnly).toBe(false);
		socket.receive({ type: 'pen', holder: 'me' });
		expect(frame.readOnly).toBe(false);
		socket.receive({ type: 'pen', holder: 'other' });
		expect(frame.readOnly).toBe(true);
		expect(states.at(-1)?.pen).toBe('other');
	});

	test('a viewer’s frame is read-only whoever holds the pen', () => {
		const socket = start();
		socket.receive(welcome('me', { viewOnly: true }));

		expect(frame.readOnly).toBe(true);
	});

	test('before the server says, the frame is read-only when editing needs a code', async () => {
		start({ editRequired: true });
		await settle();

		expect(frame.calls).toEqual([`load ${HEAD} read-only`]);
	});

	test('taking the pen and giving it back are messages', () => {
		const socket = start();
		socket.receive(welcome());

		session.pen(true);
		session.pen(false);

		expect(socket.take()).toEqual([
			{ type: 'pen', take: true },
			{ type: 'pen', take: false }
		]);
	});

	test('a patch refused because the pen is held is not sent again', async () => {
		const socket = start();
		socket.receive(welcome());
		socket.receive(since(0));
		await settle();
		edit('a');
		socket.take();

		socket.receive({ type: 'error', error: 'pen_held', message: 'Someone else holds the pen.' });
		await settle();
		expect(socket.take()).toEqual([{ type: 'reload' }]);
		expect(states.at(-1)?.status).toBe('live');

		socket.receive(whole('<mxfile>copy</mxfile>', 0));
		await settle();
		expect(socket.take()).toEqual([]);
	});

	test('a view_only refusal makes the page a viewer', () => {
		const socket = start();
		socket.receive(welcome());

		socket.receive({ type: 'error', error: 'view_only', message: 'Editing needs an access code.' });

		expect(states.at(-1)?.viewOnly).toBe(true);
		expect(frame.readOnly).toBe(true);
	});
});

describe('reconnects', () => {
	beforeEach(() => {
		vi.useFakeTimers();
	});

	test('a patch the server never took is sent again on the next connection', async () => {
		const first = start();
		first.receive(welcome());
		first.receive(since(0));
		await settle();
		edit('a');
		edit('b');
		first.receive(live(numbered(1, 'mine-1')));
		await settle();
		first.drop();

		vi.advanceTimersByTime(RETRY_DELAYS_MS[0]!);
		const second = sockets.at(-1)!;
		second.open();
		expect(second.sent[0]).toMatchObject({ type: 'hello', mark: 's.1.1' });
		second.receive(welcome('me-2'));
		second.receive(since(1, [numbered(2, 'c2')]));
		await settle();

		expect(second.take()).toMatchObject([
			{ type: 'patch', pid: 'mine-2', base: 2, checksum: null, xml: '<mxfile>b</mxfile>' }
		]);
	});

	test('a whole diagram that holds a patch this page sent is applied, and the patch not sent again', async () => {
		const first = start();
		first.receive(welcome());
		first.receive(since(0));
		await settle();
		edit('a');
		// The server took it, and the socket went before its number came back.
		first.drop();

		vi.advanceTimersByTime(RETRY_DELAYS_MS[0]!);
		const second = sockets.at(-1)!;
		second.open();
		second.receive(welcome('me-2'));
		const mine = { ...numbered(1, 'mine-1'), patch: patchOf('a') };
		second.receive(whole('<mxfile>copy</mxfile>', 0, [mine, numbered(2, 'b2')]));
		await settle();

		expect(frame.calls.slice(-3)).toEqual(['load <mxfile>copy</mxfile>', 'patch a', 'patch b2']);
		expect(second.take()).toEqual([]);
	});

	test('after a whole diagram, what was never taken is applied to it and sent', async () => {
		const first = start();
		first.receive(welcome());
		first.receive(since(0));
		await settle();
		edit('a');
		first.drop();

		vi.advanceTimersByTime(RETRY_DELAYS_MS[0]!);
		const second = sockets.at(-1)!;
		second.open();
		second.receive(welcome('me-2'));
		second.receive(whole('<mxfile>restarted</mxfile>', 0));
		await settle();

		expect(frame.calls.slice(-2)).toEqual(['load <mxfile>restarted</mxfile>', 'patch a']);
		expect(second.take()).toMatchObject([{ type: 'patch', pid: 'mine-1', base: 0 }]);
	});
});

describe('the status', () => {
	test('saving until the server says saved', async () => {
		const socket = start();
		socket.receive(welcome());
		socket.receive(since(0));
		await settle();

		edit('a');
		expect(states.at(-1)?.status).toBe('saving');
		socket.receive(live(numbered(1, 'mine-1')));
		await settle();
		expect(states.at(-1)?.status).toBe('saving');
		socket.receive({ type: 'saved', epoch: 1, savedAt: '2026-11-27T10:00:00.000Z', seq: 1 });

		expect(states.at(-1)?.status).toBe('saved');
	});

	test('who is here follows presence, without cursors', () => {
		const socket = start();
		socket.receive(welcome());

		socket.receive({ type: 'presence', connectionId: 'b', displayName: 'Bravo2', cursor: null });
		socket.receive({ type: 'presence', connectionId: 'me', displayName: 'Ann', cursor: null });
		socket.receive({ type: 'presence-end', connectionId: 'b' });

		expect(states.at(-1)?.participants).toEqual([{ connectionId: 'me', displayName: 'Ann' }]);
	});
});

describe('follow mode and cursors (T18)', () => {
	const ME = { connectionId: 'me', displayName: 'Alpha1' };
	const OTHER = { connectionId: 'other', displayName: 'Bravo2' };
	const THIRD = { connectionId: 'third', displayName: null };
	const AREA = { x: 10, y: 20, width: 800, height: 600, page: 'segl-page-1' };

	/** Live on slot 9 with the others, and the pen where `pen` says. */
	function together(pen: string | null = null): FakeSocket {
		const socket = start();
		socket.receive(welcome('me', { participants: [ME, OTHER, THIRD], pen }));
		return socket;
	}

	test('the others’ cursors are drawn on their page, and go when they leave', () => {
		const socket = together();
		socket.take();

		socket.receive({ type: 'presence', ...OTHER, cursor: { x: 5, y: 6, page: 'segl-page-1' } });
		socket.receive({ type: 'presence', ...THIRD, cursor: { x: 7, y: 8, page: null } });
		// This browser's own presence, after a rename, draws no cursor.
		socket.receive({ type: 'presence', ...ME, cursor: null });

		expect(frame.drawn.at(-1)).toEqual([
			{ id: 'other', name: 'Bravo2', color: cursorColor('other'), x: 5, y: 6, page: 'segl-page-1' },
			{ id: 'third', name: 'Unnamed', color: cursorColor('third'), x: 7, y: 8, page: null }
		]);

		socket.receive({ type: 'presence-end', connectionId: 'other' });
		expect(frame.drawn.at(-1)?.map((cursor) => cursor.id)).toEqual(['third']);
		socket.drop();
		expect(frame.drawn.at(-1)).toEqual([]);
	});

	test('this browser’s pointer goes as presence, at most once every 50 ms', () => {
		vi.useFakeTimers();
		const socket = together();
		socket.take();

		session.pointer({ x: 1, y: 1, page: 'segl-page-1' });
		session.pointer({ x: 2, y: 2, page: 'segl-page-1' });
		session.pointer({ x: 3, y: 3, page: 'segl-page-1' });
		expect(socket.take()).toEqual([
			{ type: 'presence', cursor: { x: 1, y: 1, page: 'segl-page-1' } }
		]);
		vi.advanceTimersByTime(CURSOR_INTERVAL_MS);
		expect(socket.take()).toEqual([
			{ type: 'presence', cursor: { x: 3, y: 3, page: 'segl-page-1' } }
		]);
	});

	test('a take of the pen by someone else starts a follow of the holder, once', () => {
		const socket = together();
		socket.take();

		socket.receive({ type: 'pen', holder: 'other' });
		socket.receive({ type: 'pen', holder: 'other' });

		expect(socket.take()).toEqual([{ type: 'follow', connectionId: 'other' }]);
		expect(states.at(-1)?.following).toBe('other');
	});

	test('one who looks away stays away until they press the name, or the pen moves', () => {
		const socket = together();
		socket.receive({ type: 'pen', holder: 'other' });
		socket.take();

		session.looked();
		expect(socket.take()).toEqual([{ type: 'follow', connectionId: null }]);
		session.looked();
		expect(socket.take()).toEqual([]);

		session.follow('other');
		expect(socket.take()).toEqual([{ type: 'follow', connectionId: 'other' }]);
		session.looked();
		socket.receive({ type: 'pen', holder: 'third' });
		expect(socket.take()).toEqual([
			{ type: 'follow', connectionId: null },
			{ type: 'follow', connectionId: 'third' }
		]);
	});

	test('one who looked away stays away after a reconnect, while the same person holds the pen', () => {
		vi.useFakeTimers();
		const socket = together('other');
		session.looked();
		socket.take();

		socket.drop();
		vi.advanceTimersByTime(RETRY_DELAYS_MS[0]!);
		const next = sockets.at(-1)!;
		expect(next).not.toBe(socket);
		next.open();
		next.receive(welcome('me', { participants: [ME, OTHER, THIRD], pen: 'other' }));

		expect(next.take()).toEqual([]);
		expect(states.at(-1)?.following).toBeNull();
	});

	test('when the pen comes back, the follow it started ends', () => {
		const socket = together();
		socket.receive({ type: 'pen', holder: 'other' });
		socket.receive({ type: 'pen', holder: null });

		expect(socket.take()).toEqual([
			{ type: 'follow', connectionId: 'other' },
			{ type: 'follow', connectionId: null }
		]);
		expect(states.at(-1)?.following).toBeNull();
	});

	test('a follow the person chose stays when the pen comes back', () => {
		const socket = together();
		session.follow('third');
		socket.receive({ type: 'pen', holder: 'other' });
		session.follow('third');
		socket.receive({ type: 'pen', holder: null });

		expect(socket.take()).toEqual([
			{ type: 'follow', connectionId: 'third' },
			{ type: 'follow', connectionId: 'other' },
			{ type: 'follow', connectionId: 'third' }
		]);
	});

	test('the one who takes the pen follows nobody: their own follow ends first', () => {
		const socket = together();
		session.follow('other');

		session.pen(true);
		socket.receive({ type: 'pen', holder: 'me' });

		expect(socket.take()).toEqual([
			{ type: 'follow', connectionId: 'other' },
			{ type: 'follow', connectionId: null },
			{ type: 'pen', take: true }
		]);
	});

	test('a browser that comes while someone holds the pen follows the holder', () => {
		const socket = together('other');
		expect(socket.take()).toEqual([{ type: 'follow', connectionId: 'other' }]);
	});

	test('the view of the one followed is shown, and again after a whole diagram loads', async () => {
		const socket = together();
		socket.receive(since(0));
		await settle();
		session.follow('other');

		socket.receive({ type: 'view', connectionId: 'third', view: AREA });
		socket.receive({ type: 'view', connectionId: 'other', view: AREA });
		expect(frame.shown).toEqual([AREA]);

		// A repair puts the person's own view back with the diagram.
		socket.receive(whole('<mxfile>again</mxfile>', 0));
		await settle();
		expect(frame.shown).toEqual([AREA, AREA]);
	});

	test('the view goes out only while someone follows this browser', () => {
		vi.useFakeTimers();
		const socket = together();
		socket.take();

		session.viewChanged(AREA);
		expect(socket.take()).toEqual([]);
		socket.receive({ type: 'followers', count: 1 });
		expect(socket.take()).toEqual([{ type: 'view', view: AREA }]);
	});

	test('a refused follow ends here and at the server', () => {
		const socket = together();
		session.follow('other');
		socket.take();

		socket.receive({ type: 'error', error: 'cannot_follow', message: 'No.' });

		expect(socket.take()).toEqual([{ type: 'follow', connectionId: null }]);
		expect(states.at(-1)?.following).toBeNull();
		// The frame forgets the view it was to show: a page that comes later is not turned to.
		expect(frame.shown).toEqual([null]);
	});

	test('this browser never follows itself, even after its own presence', () => {
		const socket = together();
		socket.receive({ type: 'presence', ...ME, cursor: { x: 1, y: 2, page: null } });
		socket.take();

		session.follow('me');
		socket.receive({ type: 'pen', holder: 'me' });

		expect(socket.take()).toEqual([]);
		expect(frame.drawn.at(-1)).toEqual([]);
	});

	test('the follow ends when the one followed leaves, and with a dropped socket', () => {
		const socket = together();
		session.follow('other');
		socket.receive({ type: 'presence-end', connectionId: 'other' });
		expect(states.at(-1)?.following).toBeNull();

		session.follow('third');
		socket.drop();
		expect(states.at(-1)?.following).toBeNull();
	});
});
