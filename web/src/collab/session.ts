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
 * One slot's live connection: the socket, the reconnects, and what goes over
 * it (docs/ARCHITECTURE.md, "Collaboration").
 *
 * The session knows nothing of React or of the editor. The canvas is a
 * `SceneEditor`, and the page hears of changes through `onState`.
 *
 * It keeps no queue of edits. What it keeps is `known`, the copy of each
 * element the server holds. Whatever the canvas holds that beats that copy is
 * what has to be sent: after an edit, and after a reconnect, when the canvas
 * still holds everything drawn while the socket was down.
 *
 * It numbers what it sends, and the server answers `saved` with the number of
 * the newest message that is on its disk. Until then the status is `saving`.
 * The files of images go beside the elements: `FileSync` uploads and fetches
 * the bytes, and the session tells the server which file id they are.
 */
import { knownFrom, note, pendingElements, type Known, type WireElement } from './elements.ts';
import { FileSync, type FileEditor, type FileRef, type FileTransport } from './files.ts';
import {
	parseServerMessage,
	type ClientMessage,
	type Cursor,
	type Participant,
	type ServerMessage
} from './protocol.ts';

/**
 * What the bar shows (S-013). `live` is a connection with nothing to save
 * yet. `saving` is an edit, or an image's file, that the server has not yet
 * called saved. `saved` is everything this browser sent being on the
 * server's disk.
 */
export type ConnectionStatus = 'connecting' | 'live' | 'saving' | 'saved' | 'disconnected';

/** The socket alone: the three of those that are not about saving. */
type Link = 'connecting' | 'live' | 'disconnected';

/** Another connection on the slot, as the canvas draws it. */
export interface Peer extends Participant {
	cursor: Cursor | null;
}

/** What the session needs of the canvas. `web/src/canvas/editor.ts` implements it. */
export interface SceneEditor extends FileEditor {
	/** Every element the canvas holds that is worth sending, deleted ones included. */
	elements(): readonly WireElement[];
	/** Merge elements from the server into the canvas, keeping the newer copy of each. */
	reconcile(remote: readonly WireElement[]): void;
	/** Put this scene in place of the canvas's own: a restore or an import. */
	replace(elements: readonly WireElement[]): void;
	/** Draw the other connections' cursors. */
	showPeers(peers: readonly Peer[]): void;
}

export interface SessionState {
	status: ConnectionStatus;
	/** This connection's id, while live. */
	connectionId: string | null;
	/** Whether the server lets this connection edit. Null until it has said. */
	viewOnly: boolean | null;
	/** The slot's title as the server last sent it. */
	title: string | null;
	/**
	 * The epoch of the scene on the canvas, once the server has sent its scene.
	 * A restore, by anyone, moves it on.
	 */
	epoch: number | null;
	/** Every connection on the slot, this one included, in the order they joined. */
	participants: readonly Participant[];
}

export const INITIAL_STATE: SessionState = {
	status: 'connecting',
	connectionId: null,
	viewOnly: null,
	title: null,
	epoch: null,
	participants: []
};

/** The part of `WebSocket` the session uses. */
export interface SocketLike {
	onopen: ((event: unknown) => void) | null;
	onmessage: ((event: { data: unknown }) => void) | null;
	onclose: ((event: unknown) => void) | null;
	send(text: string): void;
	close(): void;
}

export interface Hello {
	clientId: string;
	displayName: string | null;
	editToken: string;
}

export interface SessionOptions {
	/** `wss://dev.example.com/board/collab?slot=3`. */
	url: string;
	/** The epoch of the scene the canvas was loaded with. */
	epoch: number;
	editor: SceneEditor;
	/** How the files of images reach the server and come back. */
	transport: FileTransport;
	/** The file list that came with the scene the canvas was loaded with. */
	files?: readonly FileRef[];
	/** Read when a socket opens, so a reconnect sends the label of that moment. */
	hello(): Hello;
	onState(state: SessionState): void;
	/**
	 * Called at each `welcome` with the edit token its `hello` carried, and
	 * whether the server lets that connection edit. `viewOnly` in the state
	 * does not say which token it is an answer to: between a new `hello` and
	 * its `welcome` it is still the answer to the last one.
	 */
	onGate?(editToken: string, viewOnly: boolean): void;
	createSocket?(url: string): SocketLike;
}

/** How long after a socket closes the next one is tried: sooner at first. */
export const RETRY_DELAYS_MS = [500, 1000, 2000, 5000];

/** Edits are gathered for this long and sent as one message. */
export const SEND_INTERVAL_MS = 30;

/** At most one cursor message in this time. */
export const CURSOR_INTERVAL_MS = 50;

type Timer = ReturnType<typeof setTimeout>;

function openWebSocket(url: string): SocketLike {
	// The browser's handlers take an Event, of which the session reads `data`.
	return new WebSocket(url) as unknown as SocketLike;
}

export class CollabSession {
	private readonly options: SessionOptions;
	private readonly files: FileSync;
	private state: SessionState = INITIAL_STATE;
	private link: Link = 'connecting';
	private socket: SocketLike | null = null;
	private stopped = false;
	/** True from `welcome` until the socket closes. */
	private live = false;
	private failures = 0;
	private epoch: number;
	private known: Known = new Map();
	/** The number of the newest message sent that the server answers with `saved`. */
	private seq = 0;
	/** The newest of those numbers the server has called saved. */
	private savedSeq = 0;
	/** The canvas holds an edit that has still to be sent. */
	private unsent = false;
	/** The server has called something saved on this connection. */
	private savedHere = false;
	private readonly peers = new Map<string, Peer>();
	private retryTimer: Timer | undefined;
	private sendTimer: Timer | undefined;
	private cursorTimer: Timer | undefined;
	private cursorWaiting: { cursor: Cursor | null } | null = null;
	private renameWaiting: string | null = null;
	/** The edit token in the `hello` this socket was opened with. */
	private saidToken = '';

	constructor(options: SessionOptions) {
		this.options = options;
		this.epoch = options.epoch;
		this.files = new FileSync({
			editor: options.editor,
			transport: options.transport,
			// Only once the server has said so: an upload needs the edit token.
			mayUpload: () => this.state.viewOnly === false,
			onChange: () => {
				this.announce();
				this.setState();
			}
		});
		// The canvas was loaded over HTTP, and its images wait for their files
		// whether or not the socket ever opens.
		this.files.learn(options.files ?? []);
	}

	/** Open the socket. The session reconnects by itself until `stop`. */
	start(): void {
		this.open();
	}

	stop(): void {
		this.stopped = true;
		this.files.stop();
		this.clearTimers();
		clearTimeout(this.retryTimer);
		const socket = this.socket;
		this.socket = null;
		this.live = false;
		socket?.close();
	}

	/** The canvas changed. What the server has not seen goes out shortly. */
	localChange(): void {
		if (this.stopped) return;
		// An image may have been placed, or one may have arrived without its file.
		this.files.sync();
		if (!this.mayEdit()) return;
		if (!this.unsent) {
			// Said at once, not when the timer fires: until this edit is on the
			// server's disk, the bar must not go on saying `saved`.
			const pending = pendingElements(this.options.editor.elements(), this.known);
			if (pending.length === 0) return;
			this.unsent = true;
			this.setState();
		}
		if (this.sendTimer !== undefined) return;
		this.sendTimer = setTimeout(() => {
			this.sendTimer = undefined;
			this.sendPending();
		}, SEND_INTERVAL_MS);
	}

	/** This browser's pointer moved over the canvas. */
	cursor(cursor: Cursor | null): void {
		if (!this.live) return;
		this.cursorWaiting = { cursor };
		if (this.cursorTimer === undefined) this.sendCursor();
	}

	/**
	 * The person typed a new name. While the socket is not live the name
	 * waits for `welcome`: a `hello` already on its way has the old one.
	 */
	rename(displayName: string): void {
		if (this.stopped) return;
		if (this.live) this.send({ type: 'rename', displayName });
		else this.renameWaiting = displayName;
	}

	/**
	 * Connect again now, with a new `hello`. For a label that arrived after
	 * the socket opened: `rename` would title-case a name from the server's
	 * word file, and `hello` sends it as written. And for an edit token that
	 * changed: the server reads it once, in `hello` (D2-027).
	 */
	reconnect(): void {
		if (this.stopped || this.socket === null) return;
		const socket = this.socket;
		this.leave();
		socket.close();
		this.link = 'connecting';
		this.setState({ connectionId: null, participants: [] });
		this.open();
	}

	private mayEdit(): boolean {
		return this.live && this.state.viewOnly === false;
	}

	private open(): void {
		clearTimeout(this.retryTimer);
		const create = this.options.createSocket ?? openWebSocket;
		const socket = create(this.options.url);
		this.socket = socket;
		// A socket this session has let go of may still call back. It is ignored.
		socket.onopen = () => {
			if (socket !== this.socket) return;
			const hello = this.options.hello();
			this.saidToken = hello.editToken;
			this.send({ type: 'hello', ...hello });
		};
		socket.onmessage = (event) => {
			if (socket !== this.socket) return;
			const message = parseServerMessage(event.data);
			if (message !== null) this.receive(message);
		};
		socket.onclose = () => {
			if (socket === this.socket) this.dropped();
		};
	}

	/** Forget the socket and everyone on it. */
	private leave(): void {
		this.socket = null;
		this.live = false;
		this.clearTimers();
		this.peers.clear();
		this.options.editor.showPeers([]);
	}

	private dropped(): void {
		this.leave();
		this.link = 'disconnected';
		this.setState({ connectionId: null, participants: [] });
		const delay = RETRY_DELAYS_MS[Math.min(this.failures, RETRY_DELAYS_MS.length - 1)];
		this.failures += 1;
		this.retryTimer = setTimeout(() => this.open(), delay);
	}

	private clearTimers(): void {
		clearTimeout(this.sendTimer);
		clearTimeout(this.cursorTimer);
		this.sendTimer = undefined;
		this.cursorTimer = undefined;
		this.cursorWaiting = null;
	}

	private send(message: ClientMessage): void {
		try {
			this.socket?.send(JSON.stringify(message));
		} catch {
			// The socket is going. Its close event starts the reconnect.
		}
	}

	/**
	 * Send the elements the server has not seen. With `ask`, send even when
	 * there are none: the empty batch is a question, which the server answers
	 * with `saved` once everything it holds is on its disk.
	 */
	private sendPending(ask = false): void {
		if (!this.mayEdit()) return;
		const pending = pendingElements(this.options.editor.elements(), this.known);
		this.unsent = false;
		if (pending.length > 0 || ask) {
			this.seq += 1;
			this.send({ type: 'elements', epoch: this.epoch, elements: pending, seq: this.seq });
			note(this.known, pending);
		}
		this.setState();
	}

	/** Tell the server which file ids the uploaded bytes are. */
	private announce(): void {
		if (!this.mayEdit()) return;
		const refs = this.files.unannounced();
		if (refs.length === 0) return;
		this.seq += 1;
		this.send({ type: 'files', epoch: this.epoch, files: refs, seq: this.seq });
		this.files.announced(refs);
	}

	/** Whether this browser holds something the server has not called saved. */
	private unsaved(): boolean {
		return this.unsent || this.seq > this.savedSeq || this.files.busy();
	}

	private status(): ConnectionStatus {
		if (this.link !== 'live') return this.link;
		if (this.state.viewOnly !== false) return 'live';
		if (this.unsaved()) return 'saving';
		return this.savedHere ? 'saved' : 'live';
	}

	private sendCursor(): void {
		if (this.cursorWaiting === null || !this.live) return;
		const { cursor } = this.cursorWaiting;
		this.cursorWaiting = null;
		this.send({ type: 'presence', cursor });
		this.cursorTimer = setTimeout(() => {
			this.cursorTimer = undefined;
			this.sendCursor();
		}, CURSOR_INTERVAL_MS);
	}

	private receive(message: ServerMessage): void {
		switch (message.type) {
			case 'welcome':
				this.live = true;
				this.link = 'live';
				this.savedHere = false;
				this.failures = 0;
				this.peers.clear();
				for (const person of message.participants) {
					this.peers.set(person.connectionId, { ...person, cursor: null });
				}
				this.setState({
					connectionId: message.connectionId,
					viewOnly: message.viewOnly,
					title: message.title,
					participants: message.participants
				});
				this.showPeers();
				if (this.renameWaiting !== null) {
					this.send({ type: 'rename', displayName: this.renameWaiting });
					this.renameWaiting = null;
				}
				this.options.onGate?.(this.saidToken, message.viewOnly);
				break;
			case 'scene':
				if (this.live) this.takeScene(message.epoch, message.elements, message.files);
				break;
			case 'files':
				// The files other browsers added. The canvas fetches what it lacks.
				if (this.live && message.epoch === this.epoch) this.files.learn(message.files);
				break;
			case 'saved':
				if (!this.live) break;
				this.savedSeq = Math.max(this.savedSeq, message.seq);
				this.savedHere = true;
				this.setState();
				break;
			case 'elements':
				// From another epoch: the scene of the new one is on its way.
				if (!this.live || message.epoch !== this.epoch) break;
				this.options.editor.reconcile(message.elements);
				note(this.known, message.elements);
				// Where this browser's copy won, the server has yet to get it.
				this.localChange();
				break;
			case 'slot':
				this.setState({ title: message.title });
				break;
			case 'presence': {
				if (!this.live) break;
				const { type: _type, ...peer } = message;
				const before = this.peers.get(peer.connectionId);
				this.peers.set(peer.connectionId, peer);
				// A cursor alone changes nothing the bar shows.
				if (before?.displayName !== peer.displayName) {
					this.setState({ participants: this.participants() });
				}
				this.showPeers();
				break;
			}
			case 'presence-end':
				if (this.peers.delete(message.connectionId)) {
					this.setState({ participants: this.participants() });
					this.showPeers();
				}
				break;
			case 'error':
				// The server dropped an edit: this browser is a viewer after all.
				if (message.error === 'view_only') {
					this.setState({ viewOnly: true });
					break;
				}
				console.warn(`segl: ${message.error}: ${message.message}`);
				// The bytes of a file this browser named are not on the server.
				if (message.error === 'unknown_file') this.files.lost();
				break;
		}
	}

	private takeScene(
		epoch: number,
		elements: readonly WireElement[],
		files: readonly FileRef[]
	): void {
		if (epoch === this.epoch) {
			// The same scene, further on. Nothing this browser holds is thrown away.
			this.options.editor.reconcile(elements);
		} else {
			// Another scene: a restore or an import happened. What was sent for
			// the old one has nothing left to wait for.
			this.options.editor.replace(elements);
			this.epoch = epoch;
			this.savedSeq = this.seq;
		}
		this.known = knownFrom(elements);
		// Now, not shortly: these are the edits made while the socket was down.
		clearTimeout(this.sendTimer);
		this.sendTimer = undefined;
		// A message the last socket never heard `saved` for is asked about again.
		this.sendPending(this.seq > this.savedSeq);
		// The server's list for this scene. What this browser uploaded and the
		// list lacks is named again, and what the canvas lacks is fetched.
		this.files.reset(files);
		this.announce();
		// Said only when it moved: an open history list reads it again then.
		this.setState(this.state.epoch === this.epoch ? {} : { epoch: this.epoch });
	}

	private participants(): Participant[] {
		return Array.from(this.peers.values(), ({ connectionId, displayName }) => ({
			connectionId,
			displayName
		}));
	}

	private showPeers(): void {
		const me = this.state.connectionId;
		this.options.editor.showPeers(
			Array.from(this.peers.values()).filter((peer) => peer.connectionId !== me)
		);
	}

	/** Apply a change, work out the status, and tell the page if anything is new. */
	private setState(change: Partial<Omit<SessionState, 'status'>> = {}): void {
		const before = this.state;
		// First without the status: it depends on `viewOnly`, which may be changing.
		this.state = { ...before, ...change };
		const status = this.status();
		if (Object.keys(change).length === 0 && status === before.status) return;
		this.state = { ...this.state, status };
		this.options.onState(this.state);
	}
}
