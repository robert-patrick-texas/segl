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
import {
	CollabSession,
	CURSOR_INTERVAL_MS,
	INITIAL_STATE,
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

interface Harness {
	session: CollabSession;
	editor: FakeEditor;
	sockets: FakeSocket[];
	states: SessionState[];
	hello: Hello;
	/** The newest socket. */
	socket(): FakeSocket;
	state(): SessionState;
}

function start(epoch = 1): Harness {
	const editor = new FakeEditor();
	const sockets: FakeSocket[] = [];
	const states: SessionState[] = [];
	const hello: Hello = { clientId: 'client-1', displayName: 'Guest1', editToken: '' };
	const session = new CollabSession({
		url: URL,
		epoch,
		editor,
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
	options: { viewOnly?: boolean; participants?: unknown[]; epoch?: number } = {}
): void {
	socket.receive({
		type: 'welcome',
		slot: 3,
		title: 'Workspace 3',
		epoch: options.epoch ?? 1,
		viewOnly: options.viewOnly ?? false,
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

	test('hello carries the label and the token of the moment the socket opens', () => {
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

describe('editing', () => {
	test('a change is sent shortly, with the epoch', () => {
		const harness = start();
		const socket = goLive(harness);

		harness.editor.draw(element('a', 1));
		harness.session.localChange();
		expect(socket.take()).toEqual([]);
		vi.advanceTimersByTime(SEND_INTERVAL_MS);

		expect(socket.take()).toEqual([{ type: 'elements', epoch: 1, elements: [element('a', 1)] }]);
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
			{ type: 'elements', epoch: 1, elements: [element('a', 3), element('b', 1)] }
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
		expect(socket.take()).toEqual([{ type: 'elements', epoch: 1, elements: [element('b', 2)] }]);
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
		expect(socket.take()).toEqual([{ type: 'elements', epoch: 1, elements: [element('a', 3)] }]);
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
			{ type: 'elements', epoch: 1, elements: [element('early', 1)] }
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

		socket.receive({ type: 'error', error: 'view_only', message: 'Editing needs the edit token.' });
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

		expect(socket.take()).toEqual([{ type: 'elements', epoch: 2, elements: [element('a', 1)] }]);
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
			{ type: 'elements', epoch: 1, elements: [element('offline', 1)] }
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

		expect(socket.take()).toEqual([{ type: 'elements', epoch: 1, elements: [element('lost', 1)] }]);
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
