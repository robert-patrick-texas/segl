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
 * Slot 9's live connection: Diagram mode's co-editing and its pen (D2-040).
 *
 * The server numbers each patch it takes and sends it to every browser, this
 * one too. The session applies the others' patches in that order, through
 * the frame adapter, and knows its own by the id it gave each. `base` is the
 * newest numbered patch the frame holds, and every patch this page sends
 * names it, with the whole diagram. When the server could not keep that copy
 * (`exact` is false on the patch's echo), the session sends a `copy` once it
 * holds everything up to it.
 *
 * A checksum that does not match, after a patch whose sender held every
 * patch before it and while this page waits on none of its own, means this
 * diagram has drifted. The session then asks for the whole diagram, the head
 * and the patches after it, and loads it. It does the same when the server
 * refuses one of its patches: someone else took the pen, or the diagram is
 * too large.
 *
 * Patches this page made that the server has not numbered are kept. After a
 * reconnect, the ones the server never took are sent again.
 *
 * Follow mode and cursors (T18): the frame reports where the person looks
 * and points, and the session draws the others' cursors in it. Each take of
 * the pen starts this browser following the new holder, once, unless it is
 * the holder. The person ends a follow by scrolling, zooming, or clicking in
 * the frame, and it ends when the pen comes back.
 *
 * Loads and selections (T19): a load that is not a join waits until no label
 * is being typed and no press is held, and keeps the person's view and page.
 * A restore by anyone sends every browser the whole diagram of a new epoch,
 * which replaces what this page made of the old one. The frame reports this
 * browser's selection, which goes to the others at most five times a second,
 * and the session hands the others' to the frame in their cursor colors.
 */
import { Leading, Refusal } from '../collab/follow.ts';
import type { ClientMessage, Cursor, Participant, View } from '../collab/protocol.ts';
import {
	CURSOR_INTERVAL_MS,
	LOCK_EARLY_MS,
	MAX_TIMER_MS,
	RETRY_DELAYS_MS,
	type ConnectionStatus,
	type Hello,
	type Peer,
	type SocketLike
} from '../collab/session.ts';
import { Throttle } from '../collab/throttle.ts';
import { cursorColor, frameCursors } from './cursors.ts';
import type {
	DiagramEdit,
	DiagramFrameLike,
	DiagramView,
	FrameSelection,
	Selection
} from './frame.ts';
import {
	parseDiagramMessage,
	penOfWelcome,
	type DiagramClientMessage,
	type DiagramMessage,
	type DrawioPatch,
	type NumberedPatch
} from './protocol.ts';

/** What the bar shows of slot 9. */
export interface DiagramState {
	status: ConnectionStatus;
	connectionId: string | null;
	/** Whether the server lets this connection edit. Null until it has said. */
	viewOnly: boolean | null;
	title: string | null;
	epoch: number | null;
	participants: readonly Participant[];
	/** Who holds the pen: a connection id, or null when it is free. */
	pen: string | null;
	/** The connection whose view this browser follows, or null (T18). */
	following: string | null;
	/** The server refused a follow in the last few seconds: it would close a loop (T19). */
	followRefused: boolean;
	/** The server's version, as the newest `welcome` said, or null when it said none (T19). */
	version: string | null;
}

export const INITIAL_DIAGRAM_STATE: DiagramState = {
	status: 'connecting',
	connectionId: null,
	viewOnly: null,
	title: null,
	epoch: null,
	participants: [],
	pen: null,
	following: null,
	followRefused: false,
	version: null
};

/** At most one `selection` in this time (T19). */
export const SELECTION_INTERVAL_MS = 200;

export interface DiagramSessionOptions {
	/** `wss://dev.example.com/board/collab?slot=9`. */
	url: string;
	/** The head the page loaded over HTTP: its epoch, its diagram, and its mark. */
	epoch: number;
	xml: string;
	mark: string | null;
	frame: DiagramFrameLike;
	/** Whether this segl asks for an access code: a browser may edit until the server says. */
	editRequired: boolean;
	hello(): Hello;
	onState(state: DiagramState): void;
	createSocket?(url: string): SocketLike;
	/** A new id for a patch. */
	newId?(): string;
}

/** What the session counts, for the measures of D2-040. */
export interface DiagramCounts {
	/** Checksums that did not match after a patch. */
	mismatches: number;
	/** Whole diagrams loaded after the first. */
	reloads: number;
}

type Timer = ReturnType<typeof setTimeout>;

interface Unacked {
	patch: DrawioPatch;
	checksum: number | null;
}

function openWebSocket(url: string): SocketLike {
	return new WebSocket(url) as unknown as SocketLike;
}

function randomId(): string {
	return crypto.randomUUID();
}

export class DiagramSession {
	readonly counts: DiagramCounts = { mismatches: 0, reloads: 0 };
	private readonly options: DiagramSessionOptions;
	private state: DiagramState = INITIAL_DIAGRAM_STATE;
	private link: 'connecting' | 'live' | 'disconnected' = 'connecting';
	private socket: SocketLike | null = null;
	private stopped = false;
	private live = false;
	private failures = 0;
	private epoch: number;
	private mark: string | null;
	/** The newest numbered patch the frame holds. */
	private base = 0;
	/** This connection's first `diagram` is done with, so `base` is the server's. */
	private synced = false;
	/** This connection's first `diagram` has still to come. */
	private joining = false;
	/** The patches sent on this connection. One that waits is sent when it joins. */
	private readonly sent = new Set<string>();
	/** A whole diagram is on its way: what comes before it is replaced. */
	private reloading = false;
	/** This page's own patch came back not exact while it waited: a copy follows the load. */
	private copyAfterLoad = false;
	/** Every patch this page made whose number it has not seen. */
	private readonly mine = new Set<string>();
	/** Of those, the ones to send again if the server never took them, in order. */
	private readonly unacked = new Map<string, Unacked>();
	/** Messages from the server and their work on the frame, one at a time. */
	private work: Promise<void> = Promise.resolve();
	private seq = 0;
	private savedSeq = 0;
	private savedHere = false;
	private retryTimer: Timer | undefined;
	private lockTimer: Timer | undefined;
	private renameWaiting: string | null = null;
	/** The others on the slot, with their cursors. */
	private readonly peers = new Map<string, Peer>();
	private readonly cursors = new Throttle<Cursor | null>(CURSOR_INTERVAL_MS, (cursor) =>
		this.send({ type: 'presence', cursor })
	);
	/** This browser as the one followed: its view goes out while someone follows it. */
	private readonly leading = new Leading((view) => this.send({ type: 'view', view }));
	/** The pen holder this browser last followed for taking the pen. */
	private penFollowed: string | null = null;
	/** The newest view of the one followed, shown again after a whole diagram loads. */
	private shown: View | null = null;
	/** What the frame shows, as it last said. */
	private looking: View | null = null;
	private readonly refusal = new Refusal((followRefused) => this.setState({ followRefused }));
	/** This browser's selection, as the frame last said. */
	private selected: Selection | null = null;
	private readonly selections = new Throttle<Selection | null>(SELECTION_INTERVAL_MS, (selection) =>
		this.send({ type: 'selection', selection })
	);
	/** The others' selections, by connection id. */
	private readonly theirs = new Map<string, Selection>();

	constructor(options: DiagramSessionOptions) {
		this.options = options;
		this.epoch = options.epoch;
		this.mark = options.mark;
	}

	/** Load the page's diagram into the frame, and open the socket. */
	start(): void {
		this.enqueue(async () => {
			await this.options.frame.ready;
			await this.options.frame.load(this.options.xml, this.wantsReadOnly());
			// What came before the frame could draw.
			this.drawCursors();
			this.drawSelections();
		});
		this.open();
	}

	stop(): void {
		this.stopped = true;
		this.refusal.stop();
		clearTimeout(this.retryTimer);
		clearTimeout(this.lockTimer);
		const socket = this.socket;
		this.socket = null;
		this.live = false;
		socket?.close();
	}

	/** The person changed the diagram in the frame. */
	edit(edit: DiagramEdit): void {
		if (this.stopped) return;
		if (edit.patch === null) {
			// A change outside the pages. Kept as the server's copy when it can be.
			if (this.live && this.synced) {
				this.send({ type: 'copy', epoch: this.epoch, base: this.base, xml: edit.xml });
			}
			return;
		}
		const pid = (this.options.newId ?? randomId)();
		this.mine.add(pid);
		this.unacked.set(pid, { patch: edit.patch, checksum: edit.checksum });
		// Until this connection is in step, it waits: the next `diagram` sends it.
		if (this.live && this.synced) this.sendPatch(pid, edit.patch, edit.checksum, edit.xml);
		this.setState();
	}

	/**
	 * Take the pen, or give it back. The one who takes it leads: a follow of
	 * theirs ends first, or the others' follow of them would be refused.
	 */
	pen(take: boolean): void {
		if (!this.live) return;
		if (take) this.follow(null);
		this.send({ type: 'pen', take });
	}

	/** Follow this connection's view, or stop: null (T18). */
	follow(connectionId: string | null): void {
		if (!this.live || connectionId === this.state.following) return;
		if (connectionId !== null && !this.peers.has(connectionId)) return;
		this.send({ type: 'follow', connectionId });
		this.shown = null;
		this.setState({ following: connectionId });
	}

	/** The person scrolled, zoomed, or clicked in the frame: a follow ends. */
	looked(): void {
		this.follow(null);
	}

	/** The area of the diagram the frame shows, as it changes. */
	viewChanged(view: View): void {
		this.looking = view;
		this.leading.view(view);
	}

	/** The area of the diagram the frame shows, as it last said, or null. */
	view(): View | null {
		return this.looking;
	}

	/** The person's pointer moved over the diagram. */
	pointer(cursor: Cursor): void {
		if (this.live) this.cursors.push(cursor);
	}

	/**
	 * The person's selection in the frame changed: null for none, or for more
	 * than 50 cells. A viewer's goes too: it changes no diagram.
	 */
	selectionChanged(selection: Selection | null): void {
		this.selected = selection;
		if (this.live) this.selections.push(selection);
	}

	/** This browser's selection, as the frame last said, or null. */
	selection(): Selection | null {
		return this.selected;
	}

	/** Ask for the whole diagram and load it, as after a drift. It changes nothing in the diagram. */
	repair(): void {
		this.askWhole();
	}

	rename(displayName: string): void {
		if (this.stopped) return;
		if (this.live) this.send({ type: 'rename', displayName });
		else this.renameWaiting = displayName;
	}

	/** Connect again now, with a new `hello`: a new label or pass. */
	reconnect(): void {
		if (this.stopped || this.socket === null) return;
		const socket = this.socket;
		this.forget();
		clearTimeout(this.lockTimer);
		socket.close();
		this.link = 'connecting';
		this.setState({ connectionId: null, participants: [], following: null });
		this.open();
	}

	private open(): void {
		clearTimeout(this.retryTimer);
		const socket = (this.options.createSocket ?? openWebSocket)(this.options.url);
		this.socket = socket;
		socket.onopen = () => {
			if (socket !== this.socket) return;
			this.send({ type: 'hello', ...this.options.hello(), mark: this.mark });
		};
		socket.onmessage = (event) => {
			if (socket !== this.socket) return;
			this.receive(event.data);
		};
		socket.onclose = () => {
			if (socket === this.socket) this.dropped();
		};
	}

	/** Forget the socket and everyone on it. A follow either way ends with it. */
	private forget(): void {
		this.socket = null;
		this.live = false;
		this.synced = false;
		this.reloading = false;
		this.cursors.cancel();
		this.selections.cancel();
		this.leading.reset();
		this.peers.clear();
		this.theirs.clear();
		this.drawCursors();
		this.drawSelections();
	}

	private dropped(): void {
		this.forget();
		this.link = 'disconnected';
		this.setState({ connectionId: null, participants: [], following: null });
		const delay = RETRY_DELAYS_MS[Math.min(this.failures, RETRY_DELAYS_MS.length - 1)];
		this.failures += 1;
		this.retryTimer = setTimeout(() => this.open(), delay);
	}

	private send(message: DiagramClientMessage | ClientMessage): void {
		try {
			this.socket?.send(JSON.stringify(message));
		} catch {
			// The socket is going. Its close event starts the reconnect.
		}
	}

	private sendPatch(pid: string, patch: DrawioPatch, checksum: number | null, xml: string): void {
		this.sent.add(pid);
		this.seq += 1;
		this.send({
			type: 'patch',
			epoch: this.epoch,
			base: this.base,
			pid,
			patch,
			checksum,
			xml,
			seq: this.seq
		});
	}

	private enqueue(step: () => Promise<void>): void {
		this.work = this.work.then(step).catch((error: unknown) => {
			console.warn('segl: Diagram mode:', error);
		});
	}

	private receive(text: unknown): void {
		const message = parseDiagramMessage(text);
		if (message === null) return;
		switch (message.type) {
			case 'welcome':
				this.live = true;
				this.link = 'live';
				this.synced = false;
				this.joining = true;
				this.sent.clear();
				this.savedHere = false;
				this.failures = 0;
				this.peers.clear();
				for (const person of message.participants) {
					if (person.connectionId !== message.connectionId) {
						this.peers.set(person.connectionId, { ...person, cursor: null });
					}
				}
				this.setState({
					connectionId: message.connectionId,
					viewOnly: message.viewOnly,
					title: message.title,
					participants: message.participants,
					pen: penOfWelcome(text),
					following: null,
					version: message.version
				});
				if (this.renameWaiting !== null) {
					this.send({ type: 'rename', displayName: this.renameWaiting });
					this.renameWaiting = null;
				}
				this.lockIn(message.editEndsIn);
				this.keepReadOnly();
				this.drawCursors();
				// A new connection has no selection at the server: this browser's goes again.
				if (this.selected !== null) this.selections.push(this.selected);
				// Someone held the pen before this browser came.
				this.penMoved(this.state.pen);
				break;
			case 'diagram': {
				const joining = this.joining;
				this.joining = false;
				this.enqueue(() => this.takeDiagram(message, joining));
				break;
			}
			case 'patch':
				this.enqueue(() => this.takePatch(message));
				break;
			case 'pen':
				this.setState({ pen: message.holder });
				this.keepReadOnly();
				this.penMoved(message.holder);
				break;
			case 'saved':
				if (!this.live) break;
				this.savedSeq = Math.max(this.savedSeq, message.seq);
				this.savedHere = true;
				this.setState();
				break;
			case 'slot':
				this.setState({ title: message.title });
				break;
			case 'presence': {
				const { connectionId, displayName, cursor } = message;
				if (connectionId !== this.state.connectionId) {
					this.peers.set(connectionId, { connectionId, displayName, cursor });
					this.drawCursors();
				}
				const people = this.state.participants;
				const before = people.find((p) => p.connectionId === connectionId);
				if (before?.displayName === displayName) break;
				const person = { connectionId, displayName };
				this.setState({
					participants:
						before === undefined
							? [...people, person]
							: people.map((p) => (p.connectionId === connectionId ? person : p))
				});
				break;
			}
			case 'selection':
				if (message.selection === null) this.theirs.delete(message.connectionId);
				else this.theirs.set(message.connectionId, message.selection);
				this.drawSelections();
				break;
			case 'presence-end':
				if (this.peers.delete(message.connectionId)) this.drawCursors();
				if (this.theirs.delete(message.connectionId)) this.drawSelections();
				this.setState({
					participants: this.state.participants.filter(
						(p) => p.connectionId !== message.connectionId
					),
					// The server ended the follow when its leader left.
					...(this.state.following === message.connectionId ? { following: null } : {})
				});
				break;
			case 'followers':
				this.leading.followers(message.count);
				break;
			case 'view':
				if (message.connectionId === this.state.following) {
					this.shown = message.view;
					this.options.frame.showView(message.view);
				}
				break;
			case 'error':
				if (message.error === 'cannot_follow') {
					// The server kept the follow there was: this one ends it too.
					this.send({ type: 'follow', connectionId: null });
					// The bar says why, when a follow this browser asked for ended.
					if (this.state.following !== null) {
						this.setState({ following: null });
						this.refusal.refused();
					}
					break;
				}
				this.refused(message.error, message.message);
				break;
		}
	}

	/** The server would not take a change: this page's diagram is not the server's. */
	private refused(error: string, said: string): void {
		if (error === 'view_only') {
			this.setState({ viewOnly: true });
			this.keepReadOnly();
		}
		if (error !== 'view_only' && error !== 'pen_held' && error !== 'scene_too_large') {
			console.warn(`segl: ${error}: ${said}`);
			return;
		}
		// Nothing it sent is sent again, and nothing waits to be saved.
		this.unacked.clear();
		this.savedSeq = this.seq;
		this.askWhole();
		this.setState();
	}

	/**
	 * Ask for the whole diagram, once no label is being edited: a load in
	 * its place would end the editing, and what was typed with it.
	 */
	private askWhole(): void {
		if (this.reloading || !this.live) return;
		this.reloading = true;
		const socket = this.socket;
		void this.options.frame.idle().then(() => {
			if (socket === this.socket && this.reloading) this.send({ type: 'reload' });
		});
	}

	private async takeDiagram(
		message: Extract<DiagramMessage, { type: 'diagram' }>,
		joining: boolean
	): Promise<void> {
		const frame = this.options.frame;
		// What this page made before a load, which the load replaced in the frame.
		let made = new Set<string>();
		if (message.whole) {
			if (!joining) this.counts.reloads += 1;
			this.reloading = false;
			let view: DiagramView | null = null;
			if (!joining) {
				// A repair, or a restore by anyone, waits for the person: a load
				// ends a label being typed, and a drag. It keeps where they were
				// looking, on their page.
				await frame.idle();
				view = await frame.view();
			}
			await frame.load(message.xml ?? '', this.wantsReadOnly(), view);
			if (message.epoch !== this.epoch) {
				// A restore (D2-030): what this page made of the diagram that went
				// goes with it, and nothing waits to be saved.
				this.epoch = message.epoch;
				this.unacked.clear();
				this.copyAfterLoad = false;
				this.savedSeq = this.seq;
			}
			// Every edit made before the load has reached this page by now.
			made = new Set(this.unacked.keys());
			this.base = message.count;
			// Every patch after the copy, this page's own too: the load replaced them.
			for (const entry of message.patches) {
				this.unacked.delete(entry.pid);
				this.mine.delete(entry.pid);
				await frame.patch(entry.patch, null);
				this.base = entry.n;
			}
			if (!joining) {
				// What this page made before the load, which the server numbers
				// after the copy it sent: the load replaced it in the frame.
				for (const [pid, entry] of this.unacked) {
					if (made.has(pid)) await frame.patch(entry.patch, null);
				}
			}
		} else {
			this.base = message.count;
			for (const entry of message.patches) await this.apply(entry, null);
		}
		this.mark = message.mark;
		// A load put the person's own view back: a follow shows the leader's again.
		if (message.whole && this.shown !== null) this.options.frame.showView(this.shown);
		if (!joining) {
			// The server kept no copy with a patch of this page's while it waited.
			if (this.copyAfterLoad && this.live) {
				this.copyAfterLoad = false;
				this.send({ type: 'copy', epoch: this.epoch, base: this.base, xml: await frame.xml() });
			}
			// A restore moved the epoch on: an open History reads its list again.
			this.setState(this.state.epoch === this.epoch ? {} : { epoch: this.epoch });
			return;
		}
		// What this page made that the server never took: made while the
		// socket was down, lost with it, or made while this work went on.
		const waiting = () => [...this.unacked].filter(([pid]) => !this.sent.has(pid));
		for (let left = waiting(); left.length > 0; left = waiting()) {
			for (const [pid, entry] of left) {
				if (made.has(pid)) await frame.patch(entry.patch, null);
				// Its checksum was of a diagram that has moved on since.
				this.sendPatch(pid, entry.patch, null, await frame.xml());
			}
		}
		this.synced = true;
		this.setState({ epoch: this.epoch });
	}

	private async takePatch(message: Extract<DiagramMessage, { type: 'patch' }>): Promise<void> {
		if (message.epoch !== this.epoch || message.n <= this.base) return;
		if (this.reloading) {
			// A whole diagram is on its way and replaces the frame's. This page's
			// own patch is noted now: the copy in that whole may hold it, and
			// then the whole does not list it.
			if (this.mine.delete(message.pid)) {
				this.unacked.delete(message.pid);
				if (!message.exact) this.copyAfterLoad = true;
			}
			this.setState();
			return;
		}
		await this.apply(message, message.mark);
		this.setState();
	}

	/** Apply one numbered patch: another page's, or note this page's own. */
	private async apply(entry: NumberedPatch, mark: string | null): Promise<void> {
		if (this.mine.has(entry.pid)) {
			this.mine.delete(entry.pid);
			this.unacked.delete(entry.pid);
			this.base = entry.n;
			if (mark !== null) this.mark = mark;
			// The server kept no copy with it. This page now holds every patch up to it.
			if (!entry.exact && this.live) {
				const xml = await this.options.frame.xml();
				this.send({ type: 'copy', epoch: this.epoch, base: this.base, xml });
			}
			return;
		}
		// The checksum is the whole diagram's only when its sender held every
		// patch before it, this page holds them all, and waits on none of its own.
		const check =
			entry.exact &&
			entry.checksum !== null &&
			this.unacked.size === 0 &&
			this.base === entry.n - 1;
		const result = await this.options.frame.patch(entry.patch, check ? entry.checksum : null);
		this.base = entry.n;
		if (mark !== null) this.mark = mark;
		if (result.error !== null || (check && result.mismatch)) {
			if (check && result.mismatch) this.counts.mismatches += 1;
			this.askWhole();
		}
	}

	/**
	 * The pen moved. A new holder is followed, once, unless it is this browser,
	 * which is not among its own peers. When the pen comes back, the follow it
	 * started ends.
	 */
	private penMoved(holder: string | null): void {
		const before = this.penFollowed;
		if (holder === before) return;
		this.penFollowed = holder;
		if (holder !== null) this.follow(holder);
		else if (before !== null && this.state.following === before) this.follow(null);
	}

	private drawCursors(): void {
		this.options.frame.showCursors(frameCursors(this.peers.values(), this.state.connectionId));
	}

	/** Hand the frame the others' selections, each in its person's cursor color. */
	private drawSelections(): void {
		const shown: FrameSelection[] = [];
		for (const [id, { page, cells }] of this.theirs) {
			shown.push({ id, color: cursorColor(id), page, cells });
		}
		this.options.frame.showSelections(shown);
	}

	/** Whether drawio's read-only view should be on: a viewer, or someone else holds the pen. */
	private wantsReadOnly(): boolean {
		const viewOnly = this.state.viewOnly ?? this.options.editRequired;
		const pen = this.state.pen;
		return viewOnly || (pen !== null && pen !== this.state.connectionId);
	}

	private keepReadOnly(): void {
		this.options.frame.setReadOnly(this.wantsReadOnly());
	}

	private lockIn(seconds: number | null): void {
		clearTimeout(this.lockTimer);
		this.lockTimer = undefined;
		if (seconds !== null) this.lockAfter(seconds * 1000 - LOCK_EARLY_MS);
	}

	private lockAfter(remaining: number): void {
		if (remaining <= 0) {
			if (this.state.viewOnly === false) {
				this.setState({ viewOnly: true });
				this.keepReadOnly();
			}
			return;
		}
		const step = Math.min(remaining, MAX_TIMER_MS);
		this.lockTimer = setTimeout(() => {
			this.lockTimer = undefined;
			this.lockAfter(remaining - step);
		}, step);
	}

	private status(): ConnectionStatus {
		if (this.link !== 'live') return this.link;
		if (this.state.viewOnly !== false) return 'live';
		if (this.unacked.size > 0 || this.seq > this.savedSeq) return 'saving';
		return this.savedHere ? 'saved' : 'live';
	}

	private setState(change: Partial<Omit<DiagramState, 'status'>> = {}): void {
		const before = this.state;
		this.state = { ...before, ...change };
		if (before.following !== null && this.state.following === null) {
			// However the follow ended, the frame stops showing the leader's view.
			this.shown = null;
			this.options.frame.showView(null);
		}
		const status = this.status();
		if (Object.keys(change).length === 0 && status === before.status) return;
		this.state = { ...this.state, status };
		this.options.onState(this.state);
	}
}
