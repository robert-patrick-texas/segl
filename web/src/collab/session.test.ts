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
import { beats, type WireElement } from './elements.ts';
import { RETRY_MS, type CanvasFile, type FileRef, type FileTransport } from './files.ts';
import {
	CollabSession,
	CURSOR_INTERVAL_MS,
	INITIAL_STATE,
	LOCK_EARLY_MS,
	MAX_TIMER_MS,
	RETRY_DELAYS_MS,
	SEND_INTERVAL_MS,
	type Hello,
	type Peer,
	type SceneEditor,
	type SessionState,
	type SocketLike
} from './session.ts';

const URL = 'wss://dev.example.com/board/collab?slot=3';

function element(id: string, version: number, versionNonce = 1): WireElement {
	return { id, version, versionNonce };
}

/** The far end of a socket: what the session sent, and a way to answer. */
class FakeSocket implements SocketLike {
	onopen: SocketLike['onopen'] = null;
	onmessage: SocketLike['onmessage'] = null;
	onclose: SocketLike['onclose'] = null;
	readonly url: string;
	readonly sent: Record<string, unknown>[] = [];
	closed = false;

	constructor(url: string) {
		this.url = url;
	}

	send(text: string): void {
		this.sent.push(JSON.parse(text) as Record<string, unknown>);
	}

	close(): void {
		this.closed = true;
	}

	/** The handshake finished. */
	open(): void {
		this.onopen?.({});
	}

	/** The server sent a message. */
	receive(message: unknown): void {
		this.onmessage?.({ data: JSON.stringify(message) });
	}

	/** The socket closed, from either end. */
	drop(): void {
		this.onclose?.({});
	}

	/** What was sent since the last call, without the hello. */
	take(): Record<string, unknown>[] {
		return this.sent.splice(0).filter((message) => message['type'] !== 'hello');
	}
}

/** A canvas: it holds elements, and keeps the winning copy of each, as the editor does. */
class FakeEditor implements SceneEditor {
	held: WireElement[] = [];
	peers: Peer[] = [];
	calls: string[] = [];
	/** The files the canvas holds, by file id. */
	files = new Map<string, CanvasFile>();

	/** Every element with a `fileId` that is not deleted is an image. */
	images(): ReadonlyMap<string, CanvasFile | null> {
		const named = new Map<string, CanvasFile | null>();
		for (const each of this.held) {
			const id = each['fileId'];
			if (typeof id === 'string' && each['isDeleted'] !== true) {
				named.set(id, this.files.get(id) ?? null);
			}
		}
		return named;
	}

	addFiles(files: readonly CanvasFile[]): void {
		for (const file of files) {
			if (!this.files.has(file.id)) this.files.set(file.id, file);
		}
	}

	/** The person placed an image: its element, and its file. */
	place(element: WireElement, file: CanvasFile): void {
		this.files.set(file.id, file);
		this.draw(element);
	}

	elements(): readonly WireElement[] {
		return this.held;
	}

	reconcile(remote: readonly WireElement[]): void {
		this.calls.push('reconcile');
		const merged = new Map(this.held.map((each) => [each.id, each]));
		for (const each of remote) {
			if (beats(each, merged.get(each.id))) merged.set(each.id, each);
		}
		this.held = [...merged.values()];
	}

	replace(elements: readonly WireElement[]): void {
		this.calls.push('replace');
		this.held = [...elements];
	}

	showPeers(peers: readonly Peer[]): void {
		this.peers = [...peers];
	}

	/** The person drew or changed these. */
	draw(...elements: WireElement[]): void {
		const merged = new Map(this.held.map((each) => [each.id, each]));
		for (const each of elements) merged.set(each.id, each);
		this.held = [...merged.values()];
	}
}

/** A server for files: it keeps what is uploaded, and can be made to fail. */
class FakeTransport implements FileTransport {
	uploads: CanvasFile[] = [];
	downloads: FileRef[] = [];
	/** What the next transfers reject with, one each. */
	failures: unknown[] = [];

	async upload(file: CanvasFile): Promise<string> {
		this.uploads.push(file);
		if (this.failures.length > 0) throw this.failures.shift();
		return hashOf(file.id);
	}

	async download(ref: FileRef): Promise<string> {
		this.downloads.push(ref);
		if (this.failures.length > 0) throw this.failures.shift();
		return `data:${ref.mimeType};base64,${ref.hash.slice(0, 8)}`;
	}
}

/** The hash the fake server gives a file: made from its id, 64 hex digits. */
function hashOf(id: string): string {
	return id
		.replace(/[^0-9a-f]/g, '0')
		.padEnd(64, 'a')
		.slice(0, 64);
}

interface Harness {
	session: CollabSession;
	editor: FakeEditor;
	transport: FakeTransport;
	sockets: FakeSocket[];
	states: SessionState[];
	hello: Hello;
	/** The newest socket. */
	socket(): FakeSocket;
	state(): SessionState;
}

/**
 * A session over a canvas that was loaded with `loaded`: the elements the
 * scene route returned, which the canvas holds from the start. `early` is
 * what the person drew before the session began.
 */
function start(
	epoch = 1,
	files: FileRef[] = [],
	loaded: WireElement[] = [],
	early: WireElement[] = []
): Harness {
	const editor = new FakeEditor();
	editor.draw(...loaded, ...early);
	const transport = new FakeTransport();
	const sockets: FakeSocket[] = [];
	const states: SessionState[] = [];
	const hello: Hello = { clientId: 'client-1', displayName: 'Guest1', editToken: '' };
	const session = new CollabSession({
		url: URL,
		epoch,
		elements: loaded,
		editor,
		transport,
		files,
		hello: () => ({ ...hello }),
		onState: (state) => states.push(state),
		createSocket: (url) => {
			const socket = new FakeSocket(url);
			sockets.push(socket);
			return socket;
		}
	});
	session.start();
	return {
		session,
		editor,
		transport,
		sockets,
		states,
		hello,
		socket: () => sockets[sockets.length - 1]!,
		state: () => states[states.length - 1] ?? INITIAL_STATE
	};
}

const ME = { connectionId: 'me', displayName: 'Guest1' };
const OTHER = { connectionId: 'other', displayName: 'Staff2' };

function welcome(
	socket: FakeSocket,
	options: {
		viewOnly?: boolean;
		participants?: unknown[];
		epoch?: number;
		editEndsIn?: number | null;
	} = {}
): void {
	socket.receive({
		type: 'welcome',
		slot: 3,
		title: 'Workspace 3',
		epoch: options.epoch ?? 1,
		viewOnly: options.viewOnly ?? false,
		editEndsIn: options.editEndsIn ?? null,
		connectionId: 'me',
		participants: options.participants ?? [ME]
	});
}

/** Open the socket and take it to live, with `scene` as what the server holds. */
function goLive(harness: Harness, scene: WireElement[] = [], viewOnly = false): FakeSocket {
	const socket = harness.socket();
	socket.open();
	welcome(socket, { viewOnly });
	socket.receive({ type: 'scene', epoch: 1, elements: scene, files: [] });
	return socket;
}

beforeEach(() => {
	vi.useFakeTimers();
});

afterEach(() => {
	vi.useRealTimers();
	vi.restoreAllMocks();
});

describe('joining', () => {
	test('the socket is opened at the URL, and hello is sent once it is open', () => {
		const harness = start();
		const socket = harness.socket();

		expect(socket.url).toBe(URL);
		expect(socket.sent).toEqual([]);

		socket.open();

		expect(socket.sent).toEqual([
			{ type: 'hello', clientId: 'client-1', displayName: 'Guest1', editToken: '' }
		]);
	});

	test('hello carries the label and the pass of the moment the socket opens', () => {
		const harness = start();
		harness.hello.displayName = 'McKinley7';
		harness.hello.editToken = 'correct-horse';

		harness.socket().open();

		expect(harness.socket().sent[0]).toMatchObject({
			displayName: 'McKinley7',
			editToken: 'correct-horse'
		});
	});

	test('the page is live once welcome arrives, not when the socket opens', () => {
		const harness = start();
		harness.socket().open();
		expect(harness.states).toEqual([]);

		welcome(harness.socket(), { participants: [OTHER, ME] });

		expect(harness.state()).toEqual({
			status: 'live',
			connectionId: 'me',
			viewOnly: false,
			title: 'Workspace 3',
			// Not until the scene has come: the canvas is still the page's own load.
			epoch: null,
			participants: [OTHER, ME]
		});
	});

	test('the scene of the same epoch is merged in, and nothing is sent back', () => {
		const harness = start();
		harness.editor.draw(element('a', 1));

		const socket = goLive(harness, [element('a', 1), element('b', 4)]);

		expect(harness.editor.calls).toEqual(['reconcile']);
		expect(harness.editor.held).toEqual([element('a', 1), element('b', 4)]);
		expect(socket.take()).toEqual([]);
	});
});

describe('the scene the canvas was loaded with', () => {
	const LOADED = [element('a', 1), element('b', 4)];

	/** Open the socket and take it to `welcome`. The server's `scene` is still to come. */
	function welcomed(harness: Harness): FakeSocket {
		const socket = harness.socket();
		socket.open();
		welcome(socket);
		socket.take();
		return socket;
	}

	test('is not sent back when the canvas reports a change before the scene arrives', () => {
		const harness = start(1, [], LOADED);
		const socket = welcomed(harness);

		// The canvas reports a change: it drew the people `welcome` named.
		harness.session.localChange();
		vi.advanceTimersByTime(1000);
		expect(socket.take()).toEqual([]);

		socket.receive({ type: 'scene', epoch: 1, elements: LOADED, files: [] });
		harness.session.localChange();
		vi.advanceTimersByTime(1000);
		expect(socket.take()).toEqual([]);
		// Nothing was sent, so the bar never said `saving`, and has nothing to call saved.
		expect(harness.states.map((state) => state.status)).not.toContain('saving');
		expect(harness.state().status).toBe('live');
	});

	test('what the person draws before the scene arrives goes at once, alone', () => {
		const harness = start(1, [], LOADED);
		const socket = welcomed(harness);

		harness.editor.draw(element('new', 1));
		harness.session.localChange();
		expect(harness.state().status).toBe('saving');
		vi.advanceTimersByTime(SEND_INTERVAL_MS);

		expect(socket.take()).toEqual([
			{ type: 'elements', epoch: 1, elements: [element('new', 1)], seq: 1 }
		]);
	});

	test('a loaded element the person changed before the scene arrives is sent, and the rest is not', () => {
		const harness = start(1, [], LOADED);
		const socket = welcomed(harness);

		harness.editor.draw(element('b', 5));
		harness.session.localChange();
		vi.advanceTimersByTime(SEND_INTERVAL_MS);

		expect(socket.take()).toEqual([
			{ type: 'elements', epoch: 1, elements: [element('b', 5)], seq: 1 }
		]);
	});

	test('what was drawn before the session began is not taken for the loaded scene', () => {
		const harness = start(1, [], LOADED, [element('early', 1), element('b', 5)]);
		const socket = welcomed(harness);

		// It goes with the first change the canvas reports, before the scene arrives.
		harness.session.localChange();
		vi.advanceTimersByTime(SEND_INTERVAL_MS);

		expect(socket.take()).toEqual([
			{ type: 'elements', epoch: 1, elements: [element('b', 5), element('early', 1)], seq: 1 }
		]);
	});

	test('a newer copy the room holds is taken, and nothing is sent for it', () => {
		const harness = start(1, [], LOADED);
		const socket = welcomed(harness);
		harness.session.localChange();

		// The stored scene the page loaded was a flush behind the room.
		const room = [element('a', 2), element('b', 4), element('c', 1)];
		socket.receive({ type: 'scene', epoch: 1, elements: room, files: [] });
		vi.advanceTimersByTime(1000);

		expect(harness.editor.held).toEqual(room);
		expect(socket.take()).toEqual([]);
	});

	test('the scene is what the server holds from then on: a loaded element the room lacks is sent', () => {
		// A server that came back without something it had served.
		const harness = start(1, [], LOADED);
		const socket = welcomed(harness);

		socket.receive({ type: 'scene', epoch: 1, elements: [element('a', 1)], files: [] });

		expect(socket.take()).toEqual([
			{ type: 'elements', epoch: 1, elements: [element('b', 4)], seq: 1 }
		]);
	});
});

describe('editing', () => {
	test('a change is sent shortly, with the epoch', () => {
		const harness = start();
		const socket = goLive(harness);

		harness.editor.draw(element('a', 1));
		harness.session.localChange();
		expect(socket.take()).toEqual([]);
		vi.advanceTimersByTime(SEND_INTERVAL_MS);

		expect(socket.take()).toEqual([
			{ type: 'elements', epoch: 1, elements: [element('a', 1)], seq: 1 }
		]);
	});

	test('changes close together go as one message, with the newest copy of each', () => {
		const harness = start();
		const socket = goLive(harness);

		for (const version of [1, 2, 3]) {
			harness.editor.draw(element('a', version));
			harness.session.localChange();
		}
		harness.editor.draw(element('b', 1));
		harness.session.localChange();
		vi.advanceTimersByTime(SEND_INTERVAL_MS);

		expect(socket.take()).toEqual([
			{ type: 'elements', epoch: 1, elements: [element('a', 3), element('b', 1)], seq: 1 }
		]);
	});

	test('what was sent is not sent again, and only the changed element goes next', () => {
		const harness = start();
		const socket = goLive(harness);
		harness.editor.draw(element('a', 1), element('b', 1));
		harness.session.localChange();
		vi.advanceTimersByTime(SEND_INTERVAL_MS);
		socket.take();

		harness.session.localChange();
		vi.advanceTimersByTime(SEND_INTERVAL_MS);
		expect(socket.take()).toEqual([]);

		harness.editor.draw(element('b', 2));
		harness.session.localChange();
		vi.advanceTimersByTime(SEND_INTERVAL_MS);
		// Numbered on from the first message.
		expect(socket.take()).toEqual([
			{ type: 'elements', epoch: 1, elements: [element('b', 2)], seq: 2 }
		]);
	});

	test("another person's elements are merged in and not echoed", () => {
		const harness = start();
		const socket = goLive(harness);

		socket.receive({ type: 'elements', epoch: 1, elements: [element('a', 1)] });
		// The canvas reports the change the merge itself made.
		harness.session.localChange();
		vi.advanceTimersByTime(SEND_INTERVAL_MS);

		expect(harness.editor.held).toEqual([element('a', 1)]);
		expect(socket.take()).toEqual([]);
	});

	test('where this browser holds the newer copy, it is sent after the merge', () => {
		const harness = start();
		const socket = goLive(harness, [element('a', 1)]);
		harness.editor.draw(element('a', 3));

		// An older edit by someone else arrives before this browser's was sent.
		socket.receive({ type: 'elements', epoch: 1, elements: [element('a', 2)] });
		vi.advanceTimersByTime(SEND_INTERVAL_MS);

		expect(harness.editor.held).toEqual([element('a', 3)]);
		expect(socket.take()).toEqual([
			{ type: 'elements', epoch: 1, elements: [element('a', 3)], seq: 1 }
		]);
	});

	test('nothing is sent before welcome, and what was drawn meanwhile goes after the scene', () => {
		const harness = start();
		const socket = harness.socket();
		harness.editor.draw(element('early', 1));
		harness.session.localChange();
		socket.open();
		harness.session.localChange();
		vi.advanceTimersByTime(1000);
		expect(socket.take()).toEqual([]);

		welcome(socket);
		socket.receive({ type: 'scene', epoch: 1, elements: [], files: [] });

		expect(socket.take()).toEqual([
			{ type: 'elements', epoch: 1, elements: [element('early', 1)], seq: 1 }
		]);
	});

	test('a viewer sends no elements', () => {
		const harness = start();
		const socket = goLive(harness, [], true);

		harness.editor.draw(element('a', 1));
		harness.session.localChange();
		vi.advanceTimersByTime(1000);

		expect(harness.state().viewOnly).toBe(true);
		expect(socket.take()).toEqual([]);
	});

	test('a browser the server refuses to take an edit from becomes a viewer', () => {
		const harness = start();
		const socket = goLive(harness);

		socket.receive({ type: 'error', error: 'view_only', message: 'Editing needs an access code.' });
		harness.editor.draw(element('a', 1));
		harness.session.localChange();
		vi.advanceTimersByTime(1000);

		expect(harness.state().viewOnly).toBe(true);
		expect(socket.take()).toEqual([]);
	});

	test('any other error is logged and changes nothing', () => {
		const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
		const harness = start();
		const socket = goLive(harness);
		const before = harness.state();

		socket.receive({ type: 'error', error: 'bad_message', message: 'An element has a text id.' });

		expect(warn).toHaveBeenCalledWith('segl: bad_message: An element has a text id.');
		expect(harness.state()).toBe(before);
	});
});

describe('a new epoch', () => {
	test('a scene of another epoch replaces the canvas, and nothing of the old one is sent', () => {
		const harness = start();
		const socket = goLive(harness);
		harness.editor.draw(element('mine', 9));

		socket.receive({ type: 'scene', epoch: 2, elements: [element('restored', 1)], files: [] });
		vi.advanceTimersByTime(1000);

		expect(harness.editor.calls).toEqual(['reconcile', 'replace']);
		expect(harness.editor.held).toEqual([element('restored', 1)]);
		expect(socket.take()).toEqual([]);
	});

	test('edits after it carry the new epoch', () => {
		const harness = start();
		const socket = goLive(harness);
		socket.receive({ type: 'scene', epoch: 2, elements: [], files: [] });

		harness.editor.draw(element('a', 1));
		harness.session.localChange();
		vi.advanceTimersByTime(SEND_INTERVAL_MS);

		expect(socket.take()).toEqual([
			{ type: 'elements', epoch: 2, elements: [element('a', 1)], seq: 1 }
		]);
	});

	test('elements of another epoch are left alone', () => {
		const harness = start();
		const socket = goLive(harness);

		socket.receive({ type: 'elements', epoch: 2, elements: [element('a', 1)] });

		expect(harness.editor.held).toEqual([]);
	});

	test('a browser that joins a slot restored since its page loaded takes the new scene', () => {
		// The page loaded epoch 1 over HTTP, and the room is at epoch 2.
		const harness = start(1);
		const socket = harness.socket();
		harness.editor.draw(element('loaded', 3));
		socket.open();
		welcome(socket, { epoch: 2 });

		socket.receive({ type: 'scene', epoch: 2, elements: [element('restored', 1)], files: [] });

		expect(harness.editor.held).toEqual([element('restored', 1)]);
		expect(socket.take()).toEqual([]);
		expect(harness.state().epoch).toBe(2);
	});

	test('the page is told the epoch of the scene on its canvas', () => {
		const harness = start();
		const socket = harness.socket();
		socket.open();
		welcome(socket, { epoch: 4 });
		// The room is at epoch 4. The canvas is not, until the scene is here.
		expect(harness.state().epoch).toBeNull();

		socket.receive({ type: 'scene', epoch: 4, elements: [], files: [] });

		expect(harness.state().epoch).toBe(4);
	});

	test('a restore moves the epoch on, and the page hears of it once', () => {
		const harness = start();
		const socket = goLive(harness);
		const told = harness.states.length;

		socket.receive({ type: 'scene', epoch: 2, elements: [element('restored', 1)], files: [] });

		expect(harness.state().epoch).toBe(2);
		expect(harness.states).toHaveLength(told + 1);
		// The same scene again, as a stale edit is answered, is no news.
		socket.receive({ type: 'scene', epoch: 2, elements: [element('restored', 1)], files: [] });
		expect(harness.states).toHaveLength(told + 1);
		expect(harness.editor.calls).toEqual(['reconcile', 'replace', 'reconcile']);
	});

	test('the epoch stays while the socket is down: the canvas still holds that scene', () => {
		const harness = start();
		const socket = goLive(harness);
		socket.receive({ type: 'scene', epoch: 2, elements: [], files: [] });

		socket.drop();

		expect(harness.state()).toMatchObject({ status: 'disconnected', epoch: 2 });
	});

	test('a browser that was away over a restore drops what it drew for the old scene', () => {
		const harness = start();
		const socket = goLive(harness, [element('a', 1)]);
		socket.drop();
		// Drawn while the socket was down, on the scene of epoch 1.
		harness.editor.draw(element('offline', 1));
		harness.session.localChange();
		vi.advanceTimersByTime(RETRY_DELAYS_MS[0]!);
		const next = harness.socket();
		next.open();
		welcome(next, { epoch: 2 });

		next.receive({ type: 'scene', epoch: 2, elements: [element('restored', 1)], files: [] });
		vi.advanceTimersByTime(1000);

		expect(harness.editor.held).toEqual([element('restored', 1)]);
		// Nothing of the old scene is sent to the new one.
		expect(next.take()).toEqual([]);
		expect(harness.state()).toMatchObject({ status: 'live', epoch: 2 });
	});
});

describe('a dropped socket', () => {
	test('the page says disconnected, and nobody is here', () => {
		const harness = start();
		const socket = harness.socket();
		socket.open();
		welcome(socket, { participants: [ME, OTHER] });
		socket.receive({ type: 'presence', ...OTHER, cursor: { x: 1, y: 2 } });
		expect(harness.editor.peers).toHaveLength(1);

		socket.drop();

		expect(harness.state()).toMatchObject({
			status: 'disconnected',
			connectionId: null,
			participants: []
		});
		expect(harness.editor.peers).toEqual([]);
		// What the server last said about editing and the title still holds.
		expect(harness.state()).toMatchObject({ viewOnly: false, title: 'Workspace 3' });
	});

	test('a first socket that never opens is disconnected too', () => {
		const harness = start();

		harness.socket().drop();

		expect(harness.state().status).toBe('disconnected');
	});

	test('it is tried again after longer and longer waits, up to the longest', () => {
		const harness = start();

		for (const delay of [...RETRY_DELAYS_MS, 5000, 5000]) {
			const tried = harness.sockets.length;
			harness.socket().drop();
			vi.advanceTimersByTime(delay - 1);
			expect(harness.sockets).toHaveLength(tried);
			vi.advanceTimersByTime(1);
			expect(harness.sockets).toHaveLength(tried + 1);
		}
		expect(RETRY_DELAYS_MS).toEqual([500, 1000, 2000, 5000]);
	});

	test('the page stays disconnected until the new socket is welcomed', () => {
		const harness = start();
		goLive(harness).drop();
		vi.advanceTimersByTime(RETRY_DELAYS_MS[0]!);
		const next = harness.socket();

		next.open();
		expect(harness.state().status).toBe('disconnected');
		welcome(next);

		expect(harness.state().status).toBe('live');
		expect(next.sent[0]).toMatchObject({ type: 'hello' });
	});

	test('after a welcome the waits start short again', () => {
		const harness = start();
		for (const delay of RETRY_DELAYS_MS.slice(0, 3)) {
			harness.socket().drop();
			vi.advanceTimersByTime(delay);
		}
		goLive(harness).drop();

		const tried = harness.sockets.length;
		vi.advanceTimersByTime(RETRY_DELAYS_MS[0]!);

		expect(harness.sockets).toHaveLength(tried + 1);
	});

	test('what was drawn while it was down is sent on return, and a newer server edit is kept', () => {
		// The reconnect half of T-004.
		const harness = start();
		goLive(harness, [element('shared', 1), element('theirs', 1)]).drop();

		// Offline: a new element, and an edit to one the others edit too.
		harness.editor.draw(element('offline', 1), element('shared', 2));
		harness.session.localChange();
		vi.advanceTimersByTime(RETRY_DELAYS_MS[0]!);
		const socket = harness.socket();
		socket.open();
		welcome(socket);
		expect(socket.take()).toEqual([]);

		// Meanwhile the others moved further on with both.
		socket.receive({
			type: 'scene',
			epoch: 1,
			elements: [element('shared', 5), element('theirs', 2)],
			files: []
		});

		// Not the whole scene, and not the edit the server has a newer copy of.
		expect(socket.take()).toEqual([
			{ type: 'elements', epoch: 1, elements: [element('offline', 1)], seq: 1 }
		]);
		expect(harness.editor.calls).not.toContain('replace');
		expect(harness.editor.held).toEqual([
			element('shared', 5),
			element('theirs', 2),
			element('offline', 1)
		]);
	});

	test('an edit sent just before the drop, which the server never got, is sent again', () => {
		const harness = start();
		const first = goLive(harness);
		harness.editor.draw(element('lost', 1));
		harness.session.localChange();
		vi.advanceTimersByTime(SEND_INTERVAL_MS);
		expect(first.take()).toHaveLength(1);
		first.drop();
		vi.advanceTimersByTime(RETRY_DELAYS_MS[0]!);

		const socket = goLive(harness, []);

		expect(socket.take()).toEqual([
			{ type: 'elements', epoch: 1, elements: [element('lost', 1)], seq: 2 }
		]);
	});

	test('an edit waiting to be sent when the socket drops is not sent on the dead socket', () => {
		const harness = start();
		const socket = goLive(harness);
		harness.editor.draw(element('a', 1));
		harness.session.localChange();

		socket.drop();
		vi.advanceTimersByTime(SEND_INTERVAL_MS);

		expect(socket.take()).toEqual([]);
	});
});

describe('presence', () => {
	test('someone who comes is listed, and drawn on the canvas', () => {
		const harness = start();
		const socket = goLive(harness);

		socket.receive({ type: 'presence', ...OTHER, cursor: null });

		expect(harness.state().participants).toEqual([ME, OTHER]);
		expect(harness.editor.peers).toEqual([{ ...OTHER, cursor: null }]);
	});

	test('this browser is listed, and is not one of the peers on its own canvas', () => {
		const harness = start();
		const socket = harness.socket();
		socket.open();

		welcome(socket, { participants: [OTHER, ME] });

		expect(harness.state().participants).toEqual([OTHER, ME]);
		expect(harness.editor.peers.map((peer) => peer.connectionId)).toEqual(['other']);
	});

	test('a cursor moves on the canvas without a new state for the bar', () => {
		const harness = start();
		const socket = harness.socket();
		socket.open();
		welcome(socket, { participants: [ME, OTHER] });
		const states = harness.states.length;

		socket.receive({ type: 'presence', ...OTHER, cursor: { x: 10, y: 20 } });

		expect(harness.states).toHaveLength(states);
		expect(harness.editor.peers).toEqual([{ ...OTHER, cursor: { x: 10, y: 20 } }]);
	});

	test('a rename is shown in the list', () => {
		const harness = start();
		const socket = harness.socket();
		socket.open();
		welcome(socket, { participants: [ME, OTHER] });

		socket.receive({ type: 'presence', ...OTHER, displayName: 'John Smith', cursor: null });
		socket.receive({ type: 'presence', ...ME, displayName: 'Ada', cursor: null });

		expect(harness.state().participants).toEqual([
			{ connectionId: 'me', displayName: 'Ada' },
			{ connectionId: 'other', displayName: 'John Smith' }
		]);
	});

	test('someone who leaves is taken off the list and the canvas', () => {
		const harness = start();
		const socket = harness.socket();
		socket.open();
		welcome(socket, { participants: [ME, OTHER] });

		socket.receive({ type: 'presence-end', connectionId: 'other' });

		expect(harness.state().participants).toEqual([ME]);
		expect(harness.editor.peers).toEqual([]);
	});

	test('a departure of someone unknown changes nothing', () => {
		const harness = start();
		const socket = goLive(harness);
		const states = harness.states.length;

		socket.receive({ type: 'presence-end', connectionId: 'nobody' });

		expect(harness.states).toHaveLength(states);
	});

	test('a new title is taken from a slot message', () => {
		const harness = start();
		const socket = goLive(harness);

		socket.receive({ type: 'slot', slot: 3, title: 'Core network' });

		expect(harness.state().title).toBe('Core network');
	});
});

describe("this browser's cursor", () => {
	test('the first move goes at once, and then the newest position once per interval', () => {
		const harness = start();
		const socket = goLive(harness);

		harness.session.cursor({ x: 1, y: 1 });
		harness.session.cursor({ x: 2, y: 2 });
		harness.session.cursor({ x: 3, y: 3 });
		expect(socket.take()).toEqual([{ type: 'presence', cursor: { x: 1, y: 1 } }]);

		vi.advanceTimersByTime(CURSOR_INTERVAL_MS);
		expect(socket.take()).toEqual([{ type: 'presence', cursor: { x: 3, y: 3 } }]);

		vi.advanceTimersByTime(CURSOR_INTERVAL_MS * 3);
		expect(socket.take()).toEqual([]);
	});

	test('a viewer has a cursor too', () => {
		const harness = start();
		const socket = goLive(harness, [], true);

		harness.session.cursor({ x: 5, y: 6 });

		expect(socket.take()).toEqual([{ type: 'presence', cursor: { x: 5, y: 6 } }]);
	});

	test('it is not sent while the socket is not live', () => {
		const harness = start();
		harness.socket().open();

		harness.session.cursor({ x: 1, y: 1 });
		vi.advanceTimersByTime(1000);

		expect(harness.socket().take()).toEqual([]);
	});
});

describe("this browser's name", () => {
	test('a typed name is sent as a rename', () => {
		const harness = start();
		const socket = goLive(harness);

		harness.session.rename('John Smith');

		expect(socket.take()).toEqual([{ type: 'rename', displayName: 'John Smith' }]);
	});

	test('a name typed between hello and welcome is sent once the socket is live', () => {
		const harness = start();
		const socket = harness.socket();
		// The hello on its way has the old name.
		socket.open();

		harness.session.rename('John Smith');
		expect(socket.take()).toEqual([]);
		welcome(socket);

		expect(socket.take()).toEqual([{ type: 'rename', displayName: 'John Smith' }]);
		// Once.
		socket.drop();
		vi.advanceTimersByTime(RETRY_DELAYS_MS[0]!);
		harness.socket().open();
		welcome(harness.socket());
		expect(harness.socket().take()).toEqual([]);
	});

	test('reconnect says hello again on a new socket, at once', () => {
		const harness = start();
		const first = goLive(harness);
		harness.hello.displayName = 'McKinley7';

		harness.session.reconnect();

		expect(first.closed).toBe(true);
		expect(harness.sockets).toHaveLength(2);
		expect(harness.state()).toMatchObject({ status: 'connecting', participants: [] });
		harness.socket().open();
		expect(harness.socket().sent).toEqual([
			{ type: 'hello', clientId: 'client-1', displayName: 'McKinley7', editToken: '' }
		]);
	});

	test('the socket that was let go is not listened to any more', () => {
		const harness = start();
		const first = goLive(harness);
		harness.session.reconnect();
		const states = harness.states.length;

		first.receive({ type: 'slot', slot: 3, title: 'From the old socket' });
		first.drop();
		vi.advanceTimersByTime(10_000);

		expect(harness.states).toHaveLength(states);
		expect(harness.sockets).toHaveLength(2);
	});

	test('reconnect does nothing while the session is waiting to try again', () => {
		const harness = start();
		goLive(harness).drop();

		harness.session.reconnect();

		expect(harness.sockets).toHaveLength(1);
		expect(harness.state().status).toBe('disconnected');
	});
});

describe('the edit gate', () => {
	const PASS = '1800000000.q0h3JYzXb1cR5tUv7wA9-_Bd';

	test('hello carries the pass, under the name the wire has for it', () => {
		const harness = start();
		harness.hello.editToken = PASS;

		harness.socket().open();

		expect(harness.socket().sent).toEqual([
			{ type: 'hello', clientId: 'client-1', displayName: 'Guest1', editToken: PASS }
		]);
	});

	test('welcome says whether this connection may edit', () => {
		const harness = start();
		harness.hello.editToken = PASS;
		harness.socket().open();
		// Not known until the server has said.
		expect(harness.state().viewOnly).toBeNull();

		welcome(harness.socket(), { viewOnly: false });

		expect(harness.state().viewOnly).toBe(false);
	});

	test('a browser without a pass is told that it may not', () => {
		const harness = start();

		goLive(harness, [], true);

		expect(harness.state().viewOnly).toBe(true);
	});

	test('after a new hello, the state still holds the last answer until welcome', () => {
		const harness = start();
		goLive(harness, [], true);
		// The access page stored a pass, and the page says hello with it.
		harness.hello.editToken = PASS;

		harness.session.reconnect();
		harness.socket().open();

		expect(harness.socket().sent[0]).toMatchObject({ type: 'hello', editToken: PASS });
		expect(harness.state().viewOnly).toBe(true);

		welcome(harness.socket(), { viewOnly: false });

		expect(harness.state().viewOnly).toBe(false);
	});

	test('a welcome on a socket that was let go is no answer', () => {
		const harness = start();
		const first = harness.socket();
		first.open();
		harness.hello.editToken = PASS;
		harness.session.reconnect();

		welcome(first, { viewOnly: true });

		expect(harness.state().viewOnly).toBeNull();
		harness.socket().open();
		welcome(harness.socket(), { viewOnly: false });
		expect(harness.state().viewOnly).toBe(false);
	});

	test('every welcome is an answer: after a drop the server is asked again', () => {
		const harness = start();
		harness.hello.editToken = PASS;
		goLive(harness).drop();
		vi.advanceTimersByTime(RETRY_DELAYS_MS[0]!);

		// The pass ended meanwhile, or the site ended it.
		goLive(harness, [], true);

		expect(harness.state().viewOnly).toBe(true);
	});

	test('a pass that ends while the socket is open: the server says so, and the page stops editing', () => {
		const harness = start();
		harness.hello.editToken = PASS;
		const socket = goLive(harness);
		expect(harness.state().viewOnly).toBe(false);
		harness.editor.draw(element('a', 1));
		harness.session.localChange();
		const sent = socket.sent.length;

		socket.receive({ type: 'error', error: 'view_only', message: 'Editing needs an access code.' });

		expect(harness.state().viewOnly).toBe(true);
		// Nothing more is sent for the canvas: the server would refuse it.
		harness.editor.draw(element('b', 1));
		harness.session.localChange();
		vi.advanceTimersByTime(5000);
		expect(socket.sent.slice(sent).filter((message) => message.type === 'elements')).toEqual([]);
		// And a viewer is never saving.
		expect(harness.state().status).toBe('live');
	});
});

describe('a pass that is about to end', () => {
	/** Open the socket and go live as an editor whose pass has `seconds` left. */
	function liveFor(harness: Harness, seconds: number | null): FakeSocket {
		const socket = harness.socket();
		socket.open();
		welcome(socket, { editEndsIn: seconds });
		socket.receive({ type: 'scene', epoch: 1, elements: [], files: [] });
		return socket;
	}

	test('the page stops taking edits a second before the server would refuse them', () => {
		expect(LOCK_EARLY_MS).toBe(1000);
		const harness = start();
		liveFor(harness, 14.4);
		expect(harness.state().viewOnly).toBe(false);

		vi.advanceTimersByTime(13_399);
		expect(harness.state().viewOnly).toBe(false);
		vi.advanceTimersByTime(1);

		expect(harness.state().viewOnly).toBe(true);
		// It still watches: the connection is as live as any viewer's.
		expect(harness.state().status).toBe('live');
		expect(harness.sockets).toHaveLength(1);
	});

	test('from then on nothing drawn is sent', () => {
		const harness = start();
		const socket = liveFor(harness, 5);
		vi.advanceTimersByTime(4000);
		socket.take();

		harness.editor.draw(element('late', 1));
		harness.session.localChange();
		vi.advanceTimersByTime(10_000);

		expect(socket.take().filter((message) => message['type'] === 'elements')).toEqual([]);
		expect(harness.state().status).toBe('live');
	});

	test('what was drawn and not yet sent goes out first, while the pass still stands', () => {
		const harness = start();
		// 1.01 seconds left: the lock is ten milliseconds away.
		const socket = liveFor(harness, 1.01);
		socket.take();
		harness.editor.draw(element('a', 1));
		harness.session.localChange();
		// The edit waits for the send interval, which is longer than that.
		expect(SEND_INTERVAL_MS).toBeGreaterThan(10);
		expect(socket.take()).toEqual([]);

		vi.advanceTimersByTime(10);

		expect(socket.take()).toEqual([
			{ type: 'elements', epoch: 1, elements: [element('a', 1)], seq: 1 }
		]);
		expect(harness.state().viewOnly).toBe(true);
		// And it is sent once: the timer it was waiting for sends nothing more.
		vi.advanceTimersByTime(1000);
		expect(socket.take()).toEqual([]);
	});

	test.each([1, 0.4, 0])('with %j seconds left, it stops at once', (seconds) => {
		const harness = start();

		liveFor(harness, seconds);

		expect(harness.state().viewOnly).toBe(true);
	});

	test('a pass without an end never stops the page', () => {
		const harness = start();
		liveFor(harness, null);

		vi.advanceTimersByTime(40 * 24 * 3600 * 1000);

		expect(harness.state().viewOnly).toBe(false);
	});

	test('a pass longer than a timer can wait ends when it ends, and not at once', () => {
		// 1,000 hours is more milliseconds than a browser's timer takes.
		const seconds = 1000 * 3600;
		expect(seconds * 1000).toBeGreaterThan(MAX_TIMER_MS);
		const harness = start();
		liveFor(harness, seconds);

		vi.advanceTimersByTime(MAX_TIMER_MS + 5);
		expect(harness.state().viewOnly).toBe(false);
		vi.advanceTimersByTime(seconds * 1000 - LOCK_EARLY_MS - MAX_TIMER_MS - 6);
		expect(harness.state().viewOnly).toBe(false);
		vi.advanceTimersByTime(1);

		expect(harness.state().viewOnly).toBe(true);
	});

	test('a viewer has nothing that ends, whatever the message says', () => {
		const harness = start();
		const socket = harness.socket();
		socket.open();
		welcome(socket, { viewOnly: true, editEndsIn: 5 });
		const states = harness.states.length;

		vi.advanceTimersByTime(60_000);

		expect(harness.state().viewOnly).toBe(true);
		expect(harness.states).toHaveLength(states);
	});

	test('the pass ends while the socket is down too', () => {
		const harness = start();
		const socket = liveFor(harness, 10);
		vi.advanceTimersByTime(2000);
		socket.drop();
		expect(harness.state().status).toBe('disconnected');
		// The next socket never opens.
		vi.advanceTimersByTime(6999);
		expect(harness.state().viewOnly).toBe(false);

		vi.advanceTimersByTime(1);

		expect(harness.state().viewOnly).toBe(true);
	});

	test('a new hello is answered with a new length, and the old one is let go', () => {
		const harness = start();
		liveFor(harness, 10);
		vi.advanceTimersByTime(5000);

		// A pass another tab stored: the page says hello again.
		harness.session.reconnect();
		// Until the server answers, the old pass's end does not stop the page.
		vi.advanceTimersByTime(20_000);
		expect(harness.state().viewOnly).toBe(false);
		liveFor(harness, 100);

		vi.advanceTimersByTime(98_999);
		expect(harness.state().viewOnly).toBe(false);
		vi.advanceTimersByTime(1);
		expect(harness.state().viewOnly).toBe(true);
	});

	test('a code entered again is answered with an editor again', () => {
		const harness = start();
		liveFor(harness, 3);
		vi.advanceTimersByTime(2000);
		expect(harness.state().viewOnly).toBe(true);

		harness.session.reconnect();
		liveFor(harness, 43_200);

		expect(harness.state().viewOnly).toBe(false);
		vi.advanceTimersByTime(60_000);
		expect(harness.state().viewOnly).toBe(false);
	});

	test('each welcome counts from its own moment', () => {
		const harness = start();
		liveFor(harness, 10).drop();
		vi.advanceTimersByTime(RETRY_DELAYS_MS[0]!);
		// Half a second on, the same pass has half a second less.
		liveFor(harness, 9.5);

		vi.advanceTimersByTime(8499);
		expect(harness.state().viewOnly).toBe(false);
		vi.advanceTimersByTime(1);
		expect(harness.state().viewOnly).toBe(true);
	});

	test('after a drop, a longer pass is not ended by the shorter one before it', () => {
		const harness = start();
		liveFor(harness, 5).drop();
		vi.advanceTimersByTime(RETRY_DELAYS_MS[0]!);
		// A code was entered in another tab meanwhile: this hello had a new pass.
		liveFor(harness, 100);

		// Where the first pass would have stopped the page.
		vi.advanceTimersByTime(10_000);
		expect(harness.state().viewOnly).toBe(false);
		vi.advanceTimersByTime(88_999);
		expect(harness.state().viewOnly).toBe(false);
		vi.advanceTimersByTime(1);
		expect(harness.state().viewOnly).toBe(true);
	});

	test('a session that was stopped does nothing when its pass ends', () => {
		const harness = start();
		liveFor(harness, 5);
		harness.session.stop();
		const states = harness.states.length;

		vi.advanceTimersByTime(60_000);

		expect(harness.states).toHaveLength(states);
	});

	test('the server saying so first is the same end', () => {
		// The page's timer is the early one. The server's refusal still counts.
		const harness = start();
		const socket = liveFor(harness, 10);

		socket.receive({ type: 'error', error: 'view_only', message: 'Editing needs an access code.' });
		expect(harness.state().viewOnly).toBe(true);
		const states = harness.states.length;
		vi.advanceTimersByTime(20_000);

		expect(harness.states).toHaveLength(states);
	});
});

describe('stopping', () => {
	test('the socket is closed, and nothing more happens', () => {
		const harness = start();
		const socket = goLive(harness);
		harness.editor.draw(element('a', 1));
		harness.session.localChange();
		harness.session.cursor({ x: 1, y: 1 });
		socket.take();
		const states = harness.states.length;

		harness.session.stop();
		socket.drop();
		socket.receive({ type: 'slot', slot: 3, title: 'Late' });
		harness.session.localChange();
		harness.session.cursor({ x: 2, y: 2 });
		harness.session.rename('Late');
		harness.session.reconnect();
		vi.advanceTimersByTime(60_000);

		expect(socket.closed).toBe(true);
		expect(socket.take()).toEqual([]);
		expect(harness.sockets).toHaveLength(1);
		expect(harness.states).toHaveLength(states);
	});

	test('a session stopped while waiting to try again does not try', () => {
		const harness = start();
		harness.socket().drop();

		harness.session.stop();
		vi.advanceTimersByTime(60_000);

		expect(harness.sockets).toHaveLength(1);
	});
});

describe('saving', () => {
	function saved(socket: FakeSocket, seq: number): void {
		socket.receive({ type: 'saved', epoch: 1, savedAt: '2026-11-12T09:00:00.000Z', seq });
	}

	test('an edit is saving at once, and saved when the server says its number is', () => {
		// S-013: the UI shows saving and then saved.
		const harness = start();
		const socket = goLive(harness);
		expect(harness.state().status).toBe('live');

		harness.editor.draw(element('a', 1));
		harness.session.localChange();

		// Before the edit has even been sent.
		expect(harness.state().status).toBe('saving');
		expect(socket.take()).toEqual([]);
		vi.advanceTimersByTime(SEND_INTERVAL_MS);
		expect(socket.take()).toMatchObject([{ type: 'elements', seq: 1 }]);
		expect(harness.state().status).toBe('saving');

		saved(socket, 1);

		expect(harness.state().status).toBe('saved');
	});

	test('a later edit is saving again until its own number is saved', () => {
		const harness = start();
		const socket = goLive(harness);
		harness.editor.draw(element('a', 1));
		harness.session.localChange();
		vi.advanceTimersByTime(SEND_INTERVAL_MS);
		saved(socket, 1);

		harness.editor.draw(element('a', 2));
		harness.session.localChange();
		expect(harness.state().status).toBe('saving');
		vi.advanceTimersByTime(SEND_INTERVAL_MS);

		// The answer to the first message, again, does not cover the second.
		saved(socket, 1);
		expect(harness.state().status).toBe('saving');
		saved(socket, 2);
		expect(harness.state().status).toBe('saved');
	});

	test('an edit made while an earlier one is being saved keeps the status at saving', () => {
		const harness = start();
		const socket = goLive(harness);
		harness.editor.draw(element('a', 1));
		harness.session.localChange();
		vi.advanceTimersByTime(SEND_INTERVAL_MS);

		// Drawn, and not yet sent, when the first answer arrives.
		harness.editor.draw(element('b', 1));
		harness.session.localChange();
		saved(socket, 1);

		expect(harness.state().status).toBe('saving');
		vi.advanceTimersByTime(SEND_INTERVAL_MS);
		saved(socket, 2);
		expect(harness.state().status).toBe('saved');
	});

	test('an answer that arrives late, for an earlier number, takes nothing back', () => {
		const harness = start();
		const socket = goLive(harness);
		for (const version of [1, 2]) {
			harness.editor.draw(element('a', version));
			harness.session.localChange();
			vi.advanceTimersByTime(SEND_INTERVAL_MS);
		}
		saved(socket, 2);

		saved(socket, 1);

		expect(harness.state().status).toBe('saved');
	});

	test('saved before welcome is not heard, and covers nothing sent later', () => {
		const harness = start();
		const socket = harness.socket();
		socket.open();

		saved(socket, 1);
		welcome(socket);
		socket.receive({ type: 'scene', epoch: 1, elements: [], files: [] });
		expect(harness.state().status).toBe('live');
		harness.editor.draw(element('a', 1));
		harness.session.localChange();
		vi.advanceTimersByTime(SEND_INTERVAL_MS);

		// The first message of this session has number 1, and nobody has saved it.
		expect(socket.take()).toMatchObject([{ type: 'elements', seq: 1 }]);
		expect(harness.state().status).toBe('saving');
	});

	test('the page is told of a status once, however often it is worked out', () => {
		const harness = start();
		const socket = goLive(harness);
		// Welcome made the page live. The scene after it said which epoch the
		// canvas is on, and nothing else the bar shows.
		expect(harness.states.map((state) => [state.status, state.epoch])).toEqual([
			['live', null],
			['live', 1]
		]);
		harness.editor.draw(element('a', 1));
		harness.session.localChange();
		vi.advanceTimersByTime(SEND_INTERVAL_MS);

		saved(socket, 1);
		saved(socket, 1);

		expect(harness.states.map((state) => state.status)).toEqual([
			'live',
			'live',
			'saving',
			'saved'
		]);
	});

	test('one answer may cover several messages', () => {
		const harness = start();
		const socket = goLive(harness);
		for (const version of [1, 2, 3]) {
			harness.editor.draw(element('a', version));
			harness.session.localChange();
			vi.advanceTimersByTime(SEND_INTERVAL_MS);
		}

		saved(socket, 3);

		expect(harness.state().status).toBe('saved');
	});

	test('a change that leaves nothing to send is not saving, and sends nothing', () => {
		const harness = start();
		const socket = goLive(harness, [element('a', 1)]);
		const states = harness.states.length;

		// A selection, a scroll, a pointer over the canvas.
		for (let count = 0; count < 3; count += 1) harness.session.localChange();
		// Not even a timer is set for it.
		expect(vi.getTimerCount()).toBe(0);
		vi.advanceTimersByTime(1000);

		expect(harness.states).toHaveLength(states);
		expect(harness.state().status).toBe('live');
		expect(socket.take()).toEqual([]);
	});

	test("someone else's edit does not make this browser saving", () => {
		const harness = start();
		const socket = goLive(harness);

		socket.receive({ type: 'elements', epoch: 1, elements: [element('theirs', 1)] });
		harness.session.localChange();
		vi.advanceTimersByTime(1000);

		expect(harness.state().status).toBe('live');
		expect(socket.take()).toEqual([]);
	});

	test('saved stays until the next edit, and is not shown again after a reconnect', () => {
		const harness = start();
		const first = goLive(harness);
		harness.editor.draw(element('a', 1));
		harness.session.localChange();
		vi.advanceTimersByTime(SEND_INTERVAL_MS);
		saved(first, 1);
		harness.session.localChange();
		expect(harness.state().status).toBe('saved');

		first.drop();
		expect(harness.state().status).toBe('disconnected');
		vi.advanceTimersByTime(RETRY_DELAYS_MS[0]!);
		const socket = goLive(harness, [element('a', 1)]);

		// Nothing was waiting, so nothing is asked, and the new socket has saved nothing.
		expect(socket.take()).toEqual([]);
		expect(harness.state().status).toBe('live');
	});

	test('an edit the last socket never heard saved for is asked about on the next', () => {
		const harness = start();
		const first = goLive(harness);
		harness.editor.draw(element('a', 1));
		harness.session.localChange();
		vi.advanceTimersByTime(SEND_INTERVAL_MS);
		first.drop();
		vi.advanceTimersByTime(RETRY_DELAYS_MS[0]!);

		// The server did get the edit. Whether it reached the disk is not known.
		const socket = goLive(harness, [element('a', 1)]);

		// An empty batch with a number: a question the server answers with `saved`.
		expect(socket.take()).toEqual([{ type: 'elements', epoch: 1, elements: [], seq: 2 }]);
		expect(harness.state().status).toBe('saving');
		saved(socket, 2);
		expect(harness.state().status).toBe('saved');
	});

	test('an answer from before the drop is not heard on the dead socket', () => {
		const harness = start();
		const first = goLive(harness);
		harness.editor.draw(element('a', 1));
		harness.session.localChange();
		vi.advanceTimersByTime(SEND_INTERVAL_MS);
		first.drop();

		saved(first, 1);

		expect(harness.state().status).toBe('disconnected');
	});

	test('a viewer is never saving', () => {
		const harness = start();
		const socket = goLive(harness, [], true);

		harness.editor.draw(element('a', 1));
		harness.session.localChange();
		vi.advanceTimersByTime(1000);
		saved(socket, 1);

		expect(harness.state().status).toBe('live');
		expect(socket.take()).toEqual([]);
	});

	test('a browser that turns out to be a viewer stops saying saving', () => {
		const harness = start();
		const socket = goLive(harness);
		harness.editor.draw(element('a', 1));
		harness.session.localChange();
		vi.advanceTimersByTime(SEND_INTERVAL_MS);
		expect(harness.state().status).toBe('saving');

		socket.receive({ type: 'error', error: 'view_only', message: 'Editing needs an access code.' });

		expect(harness.state()).toMatchObject({ status: 'live', viewOnly: true });
	});

	test('a scene of another epoch ends the wait for what was sent to the old one', () => {
		const harness = start();
		const socket = goLive(harness);
		harness.editor.draw(element('a', 1));
		harness.session.localChange();
		vi.advanceTimersByTime(SEND_INTERVAL_MS);
		socket.take();
		expect(harness.state().status).toBe('saving');

		socket.receive({ type: 'scene', epoch: 2, elements: [element('restored', 1)], files: [] });

		expect(harness.state().status).toBe('live');
		expect(socket.take()).toEqual([]);
	});

	test('an edit the server refuses stays unsaved', () => {
		const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
		const harness = start();
		const socket = goLive(harness);
		harness.editor.draw(element('a', 1));
		harness.session.localChange();
		vi.advanceTimersByTime(SEND_INTERVAL_MS);

		socket.receive({
			type: 'error',
			error: 'scene_too_large',
			message: "The slot's scene may be at most 52428800 bytes."
		});

		// No `saved` came for it, and the bar does not pretend one did.
		expect(harness.state().status).toBe('saving');
		expect(warn).toHaveBeenCalledWith(
			"segl: scene_too_large: The slot's scene may be at most 52428800 bytes."
		);
	});
});

describe('images', () => {
	const FILE_ID = 'f'.repeat(40);
	const FILE: CanvasFile = {
		id: FILE_ID,
		mimeType: 'image/png',
		dataURL: 'data:image/png;base64,AAAA'
	};
	const REF: FileRef = { id: FILE_ID, hash: hashOf(FILE_ID), mimeType: 'image/png' };
	const picture = (version = 1): WireElement => ({
		...element('picture', version),
		fileId: FILE_ID
	});

	/** Let the transfers that have ended be heard. */
	async function settle(): Promise<void> {
		await vi.advanceTimersByTimeAsync(0);
	}

	test('a placed image is sent, its file is uploaded, and the server is told which it is', async () => {
		// T-007, the browser's half.
		const harness = start();
		const socket = goLive(harness);

		harness.editor.place(picture(), FILE);
		harness.session.localChange();

		expect(harness.state().status).toBe('saving');
		expect(harness.transport.uploads).toEqual([FILE]);
		await vi.advanceTimersByTimeAsync(SEND_INTERVAL_MS);

		// Two messages, each with a number of its own. This upload ended before
		// the edit's 30 ms were over, so the file was named first. Either order
		// is taken by the server.
		expect(socket.take()).toEqual([
			{ type: 'files', epoch: 1, files: [REF], seq: 1 },
			{ type: 'elements', epoch: 1, elements: [picture()], seq: 2 }
		]);

		// One of the two being saved is not the image being saved.
		socket.receive({ type: 'saved', epoch: 1, savedAt: 't', seq: 1 });
		expect(harness.state().status).toBe('saving');
		socket.receive({ type: 'saved', epoch: 1, savedAt: 't', seq: 2 });
		expect(harness.state().status).toBe('saved');
		// And it is done once.
		harness.session.localChange();
		await settle();
		expect(harness.transport.uploads).toHaveLength(1);
		expect(socket.take()).toEqual([]);
	});

	test('while the upload is under way the status is saving, whatever else is saved', async () => {
		const harness = start();
		const socket = goLive(harness);
		let finish: (hash: string) => void = () => {};
		harness.transport.upload = (file) => {
			harness.transport.uploads.push(file);
			return new Promise((resolve) => {
				finish = resolve;
			});
		};
		harness.editor.place(picture(), FILE);
		harness.session.localChange();
		vi.advanceTimersByTime(SEND_INTERVAL_MS);
		socket.receive({ type: 'saved', epoch: 1, savedAt: 't', seq: 1 });

		expect(harness.state().status).toBe('saving');
		expect(socket.take()).toMatchObject([{ type: 'elements' }]);

		finish(REF.hash);
		await settle();
		expect(socket.take()).toEqual([{ type: 'files', epoch: 1, files: [REF], seq: 2 }]);
	});

	test('an image someone else placed is fetched once the server names its file', async () => {
		const harness = start();
		const socket = goLive(harness);

		socket.receive({ type: 'elements', epoch: 1, elements: [picture()] });
		harness.session.localChange();
		expect(harness.transport.downloads).toEqual([]);
		socket.receive({ type: 'files', epoch: 1, files: [REF] });
		await settle();

		expect(harness.transport.downloads).toEqual([REF]);
		expect(harness.editor.files.get(FILE_ID)).toEqual({
			id: FILE_ID,
			mimeType: 'image/png',
			dataURL: `data:image/png;base64,${REF.hash.slice(0, 8)}`
		});
		// Nothing of it is uploaded or sent back, and the status never moved.
		harness.session.localChange();
		vi.advanceTimersByTime(1000);
		expect(harness.transport.uploads).toEqual([]);
		expect(socket.take()).toEqual([]);
		expect(harness.state().status).toBe('live');
	});

	test('the file list that came with the loaded scene is fetched before the socket opens', async () => {
		const editor = new FakeEditor();
		editor.draw(picture());
		const transport = new FakeTransport();

		const session = new CollabSession({
			url: URL,
			epoch: 1,
			elements: [picture()],
			editor,
			transport,
			files: [REF],
			hello: () => ({ clientId: 'client-1', displayName: 'Guest1', editToken: '' }),
			onState: () => {},
			createSocket: (url) => new FakeSocket(url)
		});
		await settle();

		expect(transport.downloads).toEqual([REF]);
		expect(editor.files.has(FILE_ID)).toBe(true);
		session.stop();
	});

	test('the files of the scene the socket sends are fetched', async () => {
		const harness = start();
		const socket = harness.socket();
		socket.open();
		welcome(socket);

		socket.receive({ type: 'scene', epoch: 1, elements: [picture()], files: [REF] });
		await settle();

		expect(harness.transport.downloads).toEqual([REF]);
		expect(harness.editor.files.has(FILE_ID)).toBe(true);
		expect(socket.take()).toEqual([]);
	});

	test('a viewer fetches files and uploads none', async () => {
		const harness = start();
		const socket = goLive(harness, [], true);
		harness.editor.place(
			{ ...element('mine', 1), fileId: 'e'.repeat(40) },
			{ ...FILE, id: 'e'.repeat(40) }
		);
		socket.receive({ type: 'elements', epoch: 1, elements: [picture()] });
		socket.receive({ type: 'files', epoch: 1, files: [REF] });
		harness.session.localChange();
		await settle();

		expect(harness.transport.downloads).toEqual([REF]);
		expect(harness.transport.uploads).toEqual([]);
		expect(socket.take()).toEqual([]);
	});

	test('files of another epoch are left alone', async () => {
		const harness = start();
		const socket = goLive(harness, [picture()]);

		socket.receive({ type: 'files', epoch: 2, files: [REF] });
		await settle();

		expect(harness.transport.downloads).toEqual([]);
	});

	test('a file uploaded while the socket was down is named once the scene is back', async () => {
		const harness = start();
		goLive(harness).drop();
		harness.editor.place(picture(), FILE);
		harness.session.localChange();
		await settle();
		// The upload needs no socket. Naming the file does.
		expect(harness.transport.uploads).toEqual([FILE]);

		vi.advanceTimersByTime(RETRY_DELAYS_MS[0]!);
		const socket = goLive(harness);

		expect(socket.take()).toEqual([
			{ type: 'elements', epoch: 1, elements: [picture()], seq: 1 },
			{ type: 'files', epoch: 1, files: [REF], seq: 2 }
		]);
		expect(harness.state().status).toBe('saving');
	});

	test('a file the server forgot with a restart is named again, without a second upload', async () => {
		const harness = start();
		const first = goLive(harness);
		harness.editor.place(picture(), FILE);
		harness.session.localChange();
		await vi.advanceTimersByTimeAsync(SEND_INTERVAL_MS);
		first.receive({ type: 'saved', epoch: 1, savedAt: 't', seq: 1 });
		first.drop();
		vi.advanceTimersByTime(RETRY_DELAYS_MS[0]!);

		// The element reached the disk. The file list did not.
		const socket = goLive(harness, [picture()]);

		expect(socket.take()).toEqual([
			{ type: 'elements', epoch: 1, elements: [], seq: 3 },
			{ type: 'files', epoch: 1, files: [REF], seq: 4 }
		]);
		expect(harness.transport.uploads).toHaveLength(1);
	});

	test('bytes the server does not have are uploaded again, and named again', async () => {
		vi.spyOn(console, 'warn').mockImplementation(() => {});
		const harness = start();
		const socket = goLive(harness);
		harness.editor.place(picture(), FILE);
		harness.session.localChange();
		await vi.advanceTimersByTimeAsync(SEND_INTERVAL_MS);
		socket.take();

		socket.receive({ type: 'error', error: 'unknown_file', message: 'Upload first.' });
		await settle();

		expect(harness.transport.uploads).toEqual([FILE, FILE]);
		expect(socket.take()).toEqual([{ type: 'files', epoch: 1, files: [REF], seq: 3 }]);
		expect(harness.state().status).toBe('saving');
	});

	test('an upload that fails is tried again, and the status stays saving meanwhile', async () => {
		vi.spyOn(console, 'warn').mockImplementation(() => {});
		const harness = start();
		const socket = goLive(harness);
		harness.transport.failures.push(new TypeError('Failed to fetch'));
		harness.editor.place(picture(), FILE);
		harness.session.localChange();
		await vi.advanceTimersByTimeAsync(SEND_INTERVAL_MS);
		socket.receive({ type: 'saved', epoch: 1, savedAt: 't', seq: 1 });

		expect(harness.state().status).toBe('saving');
		expect(socket.take()).toMatchObject([{ type: 'elements' }]);

		await vi.advanceTimersByTimeAsync(RETRY_MS);

		expect(harness.transport.uploads).toEqual([FILE, FILE]);
		expect(socket.take()).toEqual([{ type: 'files', epoch: 1, files: [REF], seq: 2 }]);
	});

	test('a stopped session hears nothing of a transfer that ends afterwards', async () => {
		const harness = start();
		const socket = goLive(harness);
		harness.editor.place(picture(), FILE);
		harness.session.localChange();
		// And an image of someone else's, whose file is on its way.
		const theirs = 'e'.repeat(40);
		socket.receive({
			type: 'elements',
			epoch: 1,
			elements: [{ ...element('theirs', 1), fileId: theirs }]
		});
		socket.receive({ type: 'files', epoch: 1, files: [{ ...REF, id: theirs }] });
		expect(harness.transport.downloads).toHaveLength(1);

		harness.session.stop();
		await vi.advanceTimersByTimeAsync(1000);
		harness.session.localChange();

		// The canvas is being taken down: nothing is handed to it, or sent.
		expect(harness.editor.files.has(theirs)).toBe(false);
		expect(socket.take()).toEqual([]);
		expect(harness.transport.uploads).toHaveLength(1);
	});
});

describe('what the server sends that is not a message', () => {
	test.each(['', '{', '[]', '{"type":"saved","epoch":1}', '{"type":"scene","epoch":1}'])(
		'%j is ignored',
		(text) => {
			const harness = start();
			const socket = goLive(harness);
			const states = harness.states.length;

			socket.onmessage?.({ data: text });

			expect(harness.states).toHaveLength(states);
			expect(harness.editor.calls).toEqual(['reconcile']);
		}
	);

	test('a socket that throws on send does not break the page', () => {
		const harness = start();
		const socket = goLive(harness);
		socket.send = () => {
			throw new Error('the socket is closing');
		};

		expect(() => harness.session.rename('Ada')).not.toThrow();
	});
});
