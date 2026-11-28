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
import { REFUSED_FOLLOW_MS } from '../collab/follow.ts';
import { CURSOR_INTERVAL_MS, RETRY_DELAYS_MS, type SocketLike } from '../collab/session.ts';
import { cursorColor, type FrameCursor } from './cursors.ts';
import type { DiagramFrameLike, DiagramView, FrameSelection, PatchResult } from './frame.ts';
import type { DrawioPatch, NumberedPatch } from './protocol.ts';
import { DiagramSession, SELECTION_INTERVAL_MS, type DiagramState } from './session.ts';

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

	/** What the person does while drawio loads the next diagram. */
	duringLoad: (() => void) | null = null;

	async load(xml: string, readOnly: boolean, view: DiagramView | null = null): Promise<void> {
		this.calls.push(`load ${xml}${readOnly ? ' read-only' : ''}`);
		this.views.push(view);
		this.diagram = xml;
		const during = this.duringLoad;
		this.duringLoad = null;
		during?.();
	}

	async view(): Promise<DiagramView | null> {
		return { scale: 1.5, x: 40, y: 60, page: 'page-3' };
	}

	editing: Promise<void> | null = null;
	/** While a press is held in the frame: what lets it go. */
	pressing: Promise<void> | null = null;
	release: (() => void) | null = null;

	idle(): Promise<void> {
		return Promise.all([this.editing, this.pressing]).then(() => undefined);
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

	/** A person presses the mouse button in the frame, to drag. */
	press(): void {
		this.pressing = new Promise((resolve) => {
			this.release = () => {
				this.pressing = null;
				resolve();
			};
		});
	}

	/** What the person does while drawio applies the patch of this label. */
	readonly during = new Map<string, () => void>();

	async patch(patch: DrawioPatch, checksum: number | null): Promise<PatchResult> {
		this.calls.push(`patch ${String(patch['label'])}`);
		this.checksums.push(checksum);
		this.during.get(String(patch['label']))?.();
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

	/** The others' selections outlined each time, in order. */
	readonly outlined: FrameSelection[][] = [];

	showSelections(selections: readonly FrameSelection[]): void {
		this.outlined.push([...selections]);
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

	test('a join’s whole diagram loads without a view', async () => {
		const socket = start();
		await settle();
		socket.receive(welcome());
		socket.receive(whole('<mxfile>copy</mxfile>', 5));
		await settle();

		expect(frame.calls.slice(1)).toEqual(['load <mxfile>copy</mxfile>']);
		expect(frame.views.at(-1)).toBeNull();
	});

	test('an edit that reaches the page while a join loads is applied again after it, and sent', async () => {
		const socket = start();
		await settle();
		socket.receive(welcome());
		frame.duringLoad = () => edit('typed', '<mxfile>typed</mxfile>');
		socket.receive(whole('<mxfile>copy</mxfile>', 5));
		await settle();

		expect(frame.calls.slice(1)).toEqual(['load <mxfile>copy</mxfile>', 'patch typed']);
		expect(socket.take()).toMatchObject([{ type: 'patch', pid: 'mine-1', base: 5 }]);
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
		// The person keeps looking where they were, on their page.
		expect(frame.views.at(-1)).toEqual({ scale: 1.5, x: 40, y: 60, page: 'page-3' });
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

/** The whole diagram of another epoch, as every browser gets it after a restore. */
function restored(xml: string, epoch: number, count = 0, patches: NumberedPatch[] = []) {
	return { type: 'diagram', epoch, whole: true, mark: `s.${epoch}.${count}`, count, xml, patches };
}

describe('loads and restores (T19)', () => {
	async function joined(): Promise<FakeSocket> {
		const socket = start();
		socket.receive(welcome());
		socket.receive(since(0));
		await settle();
		socket.take();
		frame.calls.length = 0;
		return socket;
	}

	test('a repair waits for a press to end, as for a label, and loads with the view and its page', async () => {
		const socket = await joined();
		frame.results = [{ mismatch: true, error: null }];
		frame.press();

		socket.receive(live(numbered(1, 'b1')));
		await settle();
		expect(socket.take()).toEqual([]);

		frame.release?.();
		await settle();
		expect(socket.take()).toEqual([{ type: 'reload' }]);
		socket.receive(whole('<mxfile>copy</mxfile>', 1));
		await settle();

		expect(frame.calls).toEqual(['patch b1', 'load <mxfile>copy</mxfile>']);
		expect(frame.views.at(-1)).toEqual({ scale: 1.5, x: 40, y: 60, page: 'page-3' });
	});

	test('a whole diagram that comes during a press is loaded after the release, and the patches after it wait', async () => {
		const socket = await joined();
		frame.press();

		socket.receive(restored('<mxfile>restored</mxfile>', 2));
		socket.receive({ ...live(numbered(1, 'b1')), epoch: 2 });
		await settle();
		expect(frame.calls).toEqual([]);

		frame.release?.();
		await settle();
		expect(frame.calls).toEqual(['load <mxfile>restored</mxfile>', 'patch b1']);
	});

	test('a restore by anyone loads the new epoch with the view and the page, and the epoch follows', async () => {
		const socket = await joined();

		socket.receive(restored('<mxfile>restored</mxfile>', 2, 4));
		await settle();
		expect(frame.calls).toEqual(['load <mxfile>restored</mxfile>']);
		expect(frame.views.at(-1)).toEqual({ scale: 1.5, x: 40, y: 60, page: 'page-3' });
		expect(states.at(-1)?.epoch).toBe(2);

		// A patch of the diagram that went is not applied. One of the new epoch is.
		socket.receive(live(numbered(5, 'old')));
		socket.receive({ ...live(numbered(5, 'new')), epoch: 2 });
		await settle();
		expect(frame.calls.slice(1)).toEqual(['patch new']);
		edit('next');
		expect(socket.take()).toMatchObject([{ type: 'patch', epoch: 2, base: 5, pid: 'mine-1' }]);
	});

	test('a restore drops what this page made of the diagram that went, and nothing waits to be saved', async () => {
		const socket = await joined();
		socket.receive({ type: 'saved', epoch: 1, savedAt: '2026-11-27T10:00:00.000Z', seq: 0 });
		edit('lost');
		expect(states.at(-1)?.status).toBe('saving');
		socket.take();

		socket.receive(restored('<mxfile>restored</mxfile>', 2));
		await settle();
		expect(states.at(-1)?.status).toBe('saved');
		expect(frame.calls).toEqual(['load <mxfile>restored</mxfile>']);

		// Its number comes back from the old epoch: still not applied, and not sent again.
		socket.receive(live(numbered(1, 'mine-1')));
		await settle();
		expect(frame.calls).toEqual(['load <mxfile>restored</mxfile>']);
		expect(socket.take()).toEqual([]);
	});

	test('a restore seen at a join drops what this page made offline', async () => {
		vi.useFakeTimers();
		const first = await joined();
		edit('offline');
		first.drop();

		vi.advanceTimersByTime(RETRY_DELAYS_MS[0]!);
		const second = sockets.at(-1)!;
		second.open();
		second.receive(welcome('me-2', { epoch: 3 }));
		second.receive(restored('<mxfile>restored</mxfile>', 3));
		await settle();

		expect(frame.calls.slice(-1)).toEqual(['load <mxfile>restored</mxfile>']);
		expect(second.take()).toEqual([]);
		expect(states.at(-1)?.epoch).toBe(3);
	});

	test('an edit made before a repair’s load, which the server numbers after it, is applied again', async () => {
		const socket = await joined();
		frame.results = [{ mismatch: true, error: null }];
		socket.receive(live(numbered(1, 'b1')));
		await settle();
		expect(socket.take()).toEqual([{ type: 'reload' }]);

		// The drag ends after the question went: the whole diagram does not hold it.
		edit('drag');
		socket.receive(whole('<mxfile>copy</mxfile>', 1));
		await settle();
		expect(frame.calls).toEqual(['patch b1', 'load <mxfile>copy</mxfile>', 'patch drag']);

		// Its number comes back after the load: it is this page's own, and not applied twice.
		socket.receive(live(numbered(2, 'mine-1')));
		await settle();
		expect(frame.calls.slice(3)).toEqual([]);
	});

	test('a drag that ends while a repair’s diagram waits for the release is applied again after the load', async () => {
		const socket = await joined();
		frame.results = [{ mismatch: true, error: null }];
		socket.receive(live(numbered(1, 'b1')));
		await settle();
		expect(socket.take()).toEqual([{ type: 'reload' }]);

		// The person presses before the whole diagram comes, and lets go after.
		frame.press();
		socket.receive(whole('<mxfile>copy</mxfile>', 1));
		await settle();
		expect(frame.calls).toEqual(['patch b1']);
		frame.release?.();
		edit('drag');
		await settle();

		expect(frame.calls).toEqual(['patch b1', 'load <mxfile>copy</mxfile>', 'patch drag']);
	});

	test('a restore while a copy waits for a repair sends no copy', async () => {
		const socket = await joined();
		edit('a');
		socket.take();
		frame.results = [{ mismatch: false, error: 'no such cell' }];
		socket.receive(live(numbered(1, 'b1')));
		await settle();
		expect(socket.take()).toEqual([{ type: 'reload' }]);
		// Its own patch comes back, not exact: a copy would follow the repair's load.
		socket.receive(live(numbered(2, 'mine-1', false)));

		socket.receive(restored('<mxfile>restored</mxfile>', 2));
		await settle();

		expect(socket.take()).toEqual([]);
	});

	test('an edit made after a repair’s load is not applied again', async () => {
		const socket = await joined();
		frame.results = [{ mismatch: true, error: null }];
		socket.receive(live(numbered(1, 'b1')));
		await settle();
		socket.take();

		// The person draws on the loaded diagram while drawio applies the patch after the copy.
		frame.during.set('b2', () => edit('after'));
		socket.receive(whole('<mxfile>copy</mxfile>', 1, [numbered(2, 'b2')]));
		await settle();

		expect(frame.calls).toEqual(['patch b1', 'load <mxfile>copy</mxfile>', 'patch b2']);
	});

	test('the handle’s repair asks for the whole diagram once, as after a drift', async () => {
		const socket = await joined();

		session.repair();
		session.repair();
		await settle();
		expect(socket.take()).toEqual([{ type: 'reload' }]);
		socket.receive(whole('<mxfile>copy</mxfile>', 0));
		await settle();

		expect(frame.calls).toEqual(['load <mxfile>copy</mxfile>']);
		expect(JSON.parse(JSON.stringify(session.counts))).toEqual({ mismatches: 0, reloads: 1 });
	});
});

describe('selections (T19)', () => {
	const ON = { page: 'page-3', cells: ['a', 'b'] };
	const OTHER = { connectionId: 'other', displayName: 'Bravo2' };
	const THIRD = { connectionId: 'third', displayName: null };

	test('this browser’s selection goes at once, then at most once every 200 ms, the newest winning', () => {
		vi.useFakeTimers();
		const socket = start();
		socket.receive(welcome());
		socket.take();

		session.selectionChanged(ON);
		session.selectionChanged({ page: 'page-3', cells: ['c'] });
		session.selectionChanged(null);
		expect(socket.take()).toEqual([{ type: 'selection', selection: ON }]);
		vi.advanceTimersByTime(SELECTION_INTERVAL_MS - 1);
		expect(socket.take()).toEqual([]);
		vi.advanceTimersByTime(1);
		expect(socket.take()).toEqual([{ type: 'selection', selection: null }]);
		expect(SELECTION_INTERVAL_MS).toBe(200);
	});

	test('a viewer’s selection goes too', () => {
		const socket = start();
		socket.receive(welcome('me', { viewOnly: true }));
		socket.take();

		session.selectionChanged(ON);

		expect(socket.take()).toEqual([{ type: 'selection', selection: ON }]);
	});

	test('a selection made while the socket is down goes once it is live, and again on the next connection', () => {
		vi.useFakeTimers();
		const first = start();
		session.selectionChanged(ON);
		expect(first.take()).toEqual([]);
		expect(session.selection()).toEqual(ON);

		first.receive(welcome());
		expect(first.take()).toEqual([{ type: 'selection', selection: ON }]);
		first.drop();
		vi.advanceTimersByTime(RETRY_DELAYS_MS[0]!);
		const second = sockets.at(-1)!;
		second.open();
		second.receive(welcome('me-2'));

		expect(second.take()).toEqual([{ type: 'selection', selection: ON }]);
	});

	test('after a reconnect for a new name or pass, the selection goes at once', () => {
		vi.useFakeTimers();
		const first = start();
		first.receive(welcome());
		session.selectionChanged(ON);
		expect(first.take()).toEqual([{ type: 'selection', selection: ON }]);

		session.reconnect();
		const second = sockets.at(-1)!;
		second.open();
		second.receive(welcome('me-2'));

		expect(second.take()).toEqual([{ type: 'selection', selection: ON }]);
	});

	test('nothing selected is not said again on a new connection', () => {
		const socket = start();
		session.selectionChanged(null);
		socket.receive(welcome());

		expect(socket.take()).toEqual([]);
		expect(session.selection()).toBeNull();
	});

	test('the others’ selections reach the frame in their cursor colors, and go with them', () => {
		const socket = start();
		socket.receive(
			welcome('me', { participants: [{ connectionId: 'me', displayName: 'Alpha1' }, OTHER, THIRD] })
		);

		socket.receive({ type: 'selection', connectionId: 'other', selection: ON });
		socket.receive({
			type: 'selection',
			connectionId: 'third',
			selection: { page: null, cells: ['z'] }
		});
		expect(frame.outlined.at(-1)).toEqual([
			{ id: 'other', color: cursorColor('other'), page: 'page-3', cells: ['a', 'b'] },
			{ id: 'third', color: cursorColor('third'), page: null, cells: ['z'] }
		]);

		// Another selection takes the place of the first. Nothing selected takes it away.
		socket.receive({
			type: 'selection',
			connectionId: 'other',
			selection: { page: 'page-1', cells: ['q'] }
		});
		socket.receive({ type: 'selection', connectionId: 'third', selection: null });
		expect(frame.outlined.at(-1)).toEqual([
			{ id: 'other', color: cursorColor('other'), page: 'page-1', cells: ['q'] }
		]);

		socket.receive({ type: 'presence-end', connectionId: 'other' });
		expect(frame.outlined.at(-1)).toEqual([]);
	});

	test('the others’ selections go with a dropped socket', () => {
		const socket = start();
		socket.receive(welcome());
		socket.receive({ type: 'selection', connectionId: 'other', selection: ON });
		expect(frame.outlined.at(-1)).toHaveLength(1);

		socket.drop();

		expect(frame.outlined.at(-1)).toEqual([]);
	});

	test('a selection that came before the frame could draw is drawn after its first load', async () => {
		const socket = start();
		socket.receive(welcome());
		socket.receive({ type: 'selection', connectionId: 'other', selection: ON });
		const before = frame.outlined.length;
		await settle();

		expect(frame.outlined.length).toBe(before + 1);
		expect(frame.outlined.at(-1)).toEqual([
			{ id: 'other', color: cursorColor('other'), page: 'page-3', cells: ['a', 'b'] }
		]);
	});
});

describe('the bar’s notices (T19)', () => {
	const ME = { connectionId: 'me', displayName: 'Alpha1' };
	const OTHER = { connectionId: 'other', displayName: 'Bravo2' };

	test('welcome’s version is in the state, and none is null', () => {
		const socket = start();
		expect(states.at(-1)?.version ?? null).toBeNull();

		socket.receive(welcome('me', { version: '0.9.0' }));
		expect(states.at(-1)?.version).toBe('0.9.0');
		socket.receive(welcome('me', { version: undefined }));
		expect(states.at(-1)?.version).toBeNull();
	});

	test('a refused follow is said for five seconds', () => {
		vi.useFakeTimers();
		const socket = start();
		socket.receive(welcome('me', { participants: [ME, OTHER] }));
		session.follow('other');

		socket.receive({ type: 'error', error: 'cannot_follow', message: 'No.' });
		expect(states.at(-1)?.followRefused).toBe(true);
		vi.advanceTimersByTime(REFUSED_FOLLOW_MS - 1);
		expect(states.at(-1)?.followRefused).toBe(true);
		vi.advanceTimersByTime(1);

		expect(states.at(-1)?.followRefused).toBe(false);
	});

	test('a refusal of a follow that already ended says nothing', () => {
		const socket = start();
		socket.receive(welcome('me', { participants: [ME, OTHER] }));
		session.follow('other');
		socket.receive({ type: 'presence-end', connectionId: 'other' });

		socket.receive({ type: 'error', error: 'cannot_follow', message: 'No.' });

		expect(states.some((state) => state.followRefused)).toBe(false);
	});

	test('a stopped session says nothing more of a refused follow', () => {
		vi.useFakeTimers();
		const socket = start();
		socket.receive(welcome('me', { participants: [ME, OTHER] }));
		session.follow('other');
		socket.receive({ type: 'error', error: 'cannot_follow', message: 'No.' });
		const said = states.length;

		session.stop();
		vi.advanceTimersByTime(REFUSED_FOLLOW_MS);

		expect(states.length).toBe(said);
	});
});
