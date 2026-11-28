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
 * The adapter to drawio's editor in its frame (D2-039, rule 5). Every
 * message to and from the frame goes through here: drawio's embed protocol,
 * JSON text with `proto=json` (<https://www.drawio.com/doc/faq/embed-mode>).
 *
 * It takes a message only from its own frame, and only from segl's origin,
 * which serves drawio. It posts one action at a time and waits for drawio's
 * answer before the next, so a patch never reaches a diagram that is still
 * loading. drawio's diff sync is on: an edit comes out as an `autosave` with
 * a patch, a checksum, and the whole XML.
 *
 * segl's `js/PostConfig.js` adds what drawio's messages do not carry. For
 * follow mode and cursors (T18) it reports the view, the pointer, and the
 * person's own scroll, zoom, or click, and it takes segl's own messages,
 * objects with a `segl` field, which drawio's handler never sees: a view to
 * show, and the others' cursors to draw. For T19 it reports a press and this
 * browser's selection, outlines the others' selections, and comes back to
 * the page, the view, and the selection after a load.
 */
import { parseView, type Cursor, type View } from '../collab/protocol.ts';
import type { FrameCursor } from './cursors.ts';
import type { DrawioPatch } from './protocol.ts';

/** The frame's window, as the adapter posts to it. */
export interface FrameTarget {
	postMessage(message: unknown, targetOrigin: string): void;
}

/** A message event, as the adapter reads one. */
export interface FrameEvent {
	source: unknown;
	origin: string;
	data: unknown;
}

/** An edit the person made in the frame. */
export interface DiagramEdit {
	/** drawio's patch, or null for a change outside the pages, such as a setting. */
	patch: DrawioPatch | null;
	checksum: number | null;
	/** The whole diagram after the edit. */
	xml: string;
}

/** Where a person is looking: the scale, the diagram's point at the top left, and the page. */
export interface DiagramView {
	scale: number;
	x: number;
	y: number;
	/** drawio's id of the page shown, or null when drawio named none. */
	page: string | null;
}

/** What this browser has selected in the frame. */
export interface Selection {
	/** drawio's id of the page the cells are on, or null. */
	page: string | null;
	/** 1 to 50 cell ids. */
	cells: readonly string[];
}

/** Another person's selection, as the frame outlines it. */
export interface FrameSelection {
	/** Their connection id. */
	id: string;
	/** Their cursor color, as for their cursor. */
	color: string;
	page: string | null;
	cells: readonly string[];
}

/** What drawio said of a patch it applied. */
export interface PatchResult {
	/** Its diagram's checksum after the patch is not the one sent. */
	mismatch: boolean;
	/** drawio could not apply the patch. */
	error: string | null;
}

/** What the session needs of the frame. `DiagramFrame` is it. */
export interface DiagramFrameLike {
	/** Settles once drawio has said it is ready for a diagram. */
	readonly ready: Promise<void>;
	/**
	 * Put a diagram in place of the frame's, with drawio's read-only view on
	 * or off. It waits until no label is edited and no press is held. With a
	 * view, the person keeps looking where they were, on the same page, with
	 * the cells they had selected that are still there.
	 */
	load(xml: string, readOnly: boolean, view?: DiagramView | null): Promise<void>;
	/** Apply another browser's patch. With a checksum, drawio compares it. */
	patch(patch: DrawioPatch, checksum: number | null): Promise<PatchResult>;
	/** Return the frame's whole diagram. */
	xml(): Promise<string>;
	/** Return where the person is looking, or null when drawio did not say. */
	view(): Promise<DiagramView | null>;
	/** Settles when no label is being edited and no press is held in the frame. */
	idle(): Promise<void>;
	/** Keep drawio's read-only view on, or off. */
	setReadOnly(value: boolean): void;
	/**
	 * Show another browser's view: its page of the diagram, and its area
	 * fitted. Null when the follow ended: a page that comes later is not turned to.
	 */
	showView(view: View | null): void;
	/** Draw these cursors, and only these. */
	showCursors(cursors: readonly FrameCursor[]): void;
	/** Outline these selections, and only these. The frame draws them again after each patch and load. */
	showSelections(selections: readonly FrameSelection[]): void;
}

/** What the person does in the frame, besides editing (T18). */
export interface FrameWatcher {
	/** The area of the diagram the frame shows, with its page, as it changes. */
	onView(view: View): void;
	/** The person's pointer, on the diagram. */
	onPointer(cursor: Cursor): void;
	/** The person scrolled, zoomed, or clicked in the frame themselves. */
	onLooked(): void;
	/** This browser's selection changed: null for none, or for more than 50 cells. */
	onSelection(selection: Selection | null): void;
}

export interface FrameOptions extends Partial<FrameWatcher> {
	/** The frame's window, or null while there is none. */
	target(): FrameTarget | null;
	/** segl's own origin, which serves drawio. */
	origin: string;
	/** The person changed the diagram. */
	onEdit(edit: DiagramEdit): void;
}

/** The URL parameters of drawio's page in Diagram mode. */
export const EMBED_PARAMETERS =
	// Embed mode, its JSON protocol, and no Save or Exit button: the
	// diagram is saved as it changes. stealth and lockdown keep drawio from
	// offering anything that reaches another site, and pwa=0 keeps its
	// service worker off.
	'embed=1&proto=json&noSaveBtn=1&noExitBtn=1&saveAndExit=0&stealth=1&lockdown=1&pwa=0';

/** Return the address of drawio's page under segl's root URL. */
export function drawioAddress(root: URL): string {
	return new URL(`drawio/index.html?${EMBED_PARAMETERS}`, root).href;
}

/** The most cells a selection names: drawio's own sessions send none above it. */
export const SELECTION_LIMIT = 50;

/** The longest page or cell id the server takes. */
const ID_LIMIT = 128;

type Reply = Record<string, unknown>;

interface Waiting {
	event: string;
	resolve(reply: Reply): void;
}

interface Queued {
	action: Reply;
	event: string;
	resolve(reply: Reply): void;
	/** Post it only once no label is edited and no press is held. */
	whenIdle?: boolean;
	/** One of segl's own messages to post just before it. */
	before?: { segl: string } & Record<string, unknown>;
}

export class DiagramFrame implements DiagramFrameLike {
	readonly ready: Promise<void>;
	private readonly options: FrameOptions;
	private markReady!: () => void;
	private isReady = false;
	/** The actions posted and not yet answered: one at a time. */
	private waiting: Waiting | null = null;
	private queue: Queued[] = [];
	/** The read-only view the page wants, and the one drawio last said it has. */
	private wantReadOnly = false;
	private readOnly: boolean | null = null;
	private toggling = false;
	/** A label editor is open, or a press is held, in the frame, and what waits for neither. */
	private editing = false;
	private pressed = false;
	private waitingIdle: Array<() => void> = [];
	/** The others' selections, as last given: drawio is told them once it is ready. */
	private selections: readonly FrameSelection[] | null = null;

	constructor(options: FrameOptions) {
		this.options = options;
		this.ready = new Promise((resolve) => {
			this.markReady = resolve;
		});
	}

	/** Take a message event. The page hands every one here, and the others are ignored. */
	handle(event: FrameEvent): void {
		const target = this.options.target();
		if (target === null || event.source !== target || event.origin !== this.options.origin) {
			return;
		}
		let message: unknown;
		try {
			message = typeof event.data === 'string' ? JSON.parse(event.data) : null;
		} catch {
			return;
		}
		if (typeof message !== 'object' || message === null || Array.isArray(message)) return;
		const reply = message as Reply;
		switch (reply['event']) {
			case 'init':
				if (!this.isReady) {
					this.isReady = true;
					this.markReady();
					if (this.selections !== null) this.showSelections(this.selections);
					this.next();
				}
				return;
			case 'autosave':
				this.edited(reply);
				return;
			case 'readOnly':
				this.readOnly = reply['readOnly'] === true;
				this.toggling = false;
				this.keepReadOnly();
				return;
			case 'editing':
				this.editing = reply['editing'] === true;
				this.settle();
				return;
			case 'press':
				this.pressed = reply['pressed'] === true;
				this.settle();
				return;
			case 'selection': {
				const selection = parseSelection(reply['selection']);
				if (selection !== undefined) this.options.onSelection?.(selection);
				return;
			}
			case 'view': {
				const view = parseView(reply['view']);
				if (view !== null) this.options.onView?.(view);
				return;
			}
			case 'pointer': {
				const { x, y, page } = reply;
				if (!Number.isFinite(x) || !Number.isFinite(y)) return;
				const where = typeof page === 'string' && page !== '' ? page : null;
				this.options.onPointer?.({ x: x as number, y: y as number, page: where });
				return;
			}
			case 'looked':
				this.options.onLooked?.();
				return;
		}
		const waiting = this.waiting;
		if (waiting !== null && reply['event'] === waiting.event) {
			this.waiting = null;
			waiting.resolve(reply);
			this.next();
		}
	}

	load(xml: string, readOnly: boolean, view: DiagramView | null = null): Promise<void> {
		this.wantReadOnly = readOnly;
		const action: Reply = { action: 'load', xml, autosave: 1, diffSync: true, readOnly };
		// A load would end a label being typed, and a drag: it waits for both.
		const when: Pick<Queued, 'whenIdle' | 'before'> = { whenIdle: true };
		if (view !== null) {
			// drawio scales, then scrolls this point of the diagram to the top
			// left, on the first page. PostConfig.js turns to the view's page
			// after the load, sets the view there, and selects again.
			action['scale'] = view.scale;
			action['scroll'] = { x: view.x, y: view.y };
			when.before = { segl: 'keep', view };
		}
		return this.post(action, 'load', when).then(() => undefined);
	}

	async patch(patch: DrawioPatch, checksum: number | null): Promise<PatchResult> {
		const action: Reply = { action: 'patch', patch };
		if (checksum !== null) action['checksum'] = checksum;
		const reply = await this.post(action, 'patch');
		const error = reply['error'];
		return {
			mismatch: reply['checksumMismatch'] === true,
			error: error === undefined || error === null ? null : String(error)
		};
	}

	async xml(): Promise<string> {
		const reply = await this.post({ action: 'export', format: 'xml' }, 'export');
		const xml = reply['xml'];
		if (typeof xml !== 'string') throw new Error('drawio sent no diagram');
		return xml;
	}

	async view(): Promise<DiagramView | null> {
		return viewOf(await this.post({ action: 'export', format: 'xml' }, 'export'));
	}

	idle(): Promise<void> {
		if (this.isIdle()) return Promise.resolve();
		return new Promise((resolve) => this.waitingIdle.push(resolve));
	}

	setReadOnly(value: boolean): void {
		this.wantReadOnly = value;
		this.keepReadOnly();
	}

	showView(view: View | null): void {
		this.tellSegl({ segl: 'view', view });
	}

	showCursors(cursors: readonly FrameCursor[]): void {
		this.tellSegl({ segl: 'cursors', cursors });
	}

	showSelections(selections: readonly FrameSelection[]): void {
		this.selections = selections;
		this.tellSegl({ segl: 'selections', selections });
	}

	private isIdle(): boolean {
		return !this.editing && !this.pressed;
	}

	/** No label is edited and no press is held: what waited for it goes on. */
	private settle(): void {
		if (!this.isIdle()) return;
		for (const resolve of this.waitingIdle.splice(0)) resolve();
		this.next();
	}

	/**
	 * Post one of segl's own messages to `PostConfig.js`. Not one of drawio's
	 * actions, so it waits for no answer, and goes as an object, not as text.
	 */
	private tellSegl(message: { segl: string } & Record<string, unknown>): void {
		if (!this.isReady) return;
		this.options.target()?.postMessage(message, this.options.origin);
	}

	/** Turn drawio's read-only view the way the page wants it. drawio's action toggles it. */
	private keepReadOnly(): void {
		if (this.toggling || this.readOnly === null || this.readOnly === this.wantReadOnly) return;
		const target = this.options.target();
		if (target === null) return;
		this.toggling = true;
		target.postMessage(
			JSON.stringify({ action: 'invokeAction', actionName: 'readOnly' }),
			this.options.origin
		);
	}

	private edited(reply: Reply): void {
		const { patch, checksum, xml } = reply;
		if (typeof xml !== 'string') return;
		const hasPatch = typeof patch === 'object' && patch !== null && !Array.isArray(patch);
		this.options.onEdit({
			patch: hasPatch ? (patch as DrawioPatch) : null,
			checksum: Number.isInteger(checksum) ? (checksum as number) : null,
			xml
		});
	}

	private post(
		action: Reply,
		event: string,
		when: Pick<Queued, 'whenIdle' | 'before'> = {}
	): Promise<Reply> {
		return new Promise((resolve) => {
			this.queue.push({ action, event, resolve, ...when });
			this.next();
		});
	}

	private next(): void {
		if (this.waiting !== null || !this.isReady) return;
		const item = this.queue[0];
		if (item === undefined || (item.whenIdle === true && !this.isIdle())) return;
		const target = this.options.target();
		if (target === null) return;
		this.queue.shift();
		if (item.before !== undefined) target.postMessage(item.before, this.options.origin);
		this.waiting = { event: item.event, resolve: item.resolve };
		target.postMessage(JSON.stringify(item.action), this.options.origin);
	}
}

function isId(value: unknown): value is string {
	return typeof value === 'string' && value.length >= 1 && value.length <= ID_LIMIT;
}

/**
 * Return the selection `PostConfig.js` reported: null for none, or for more
 * than 50 cells, and undefined for a report that is not one. A page id the
 * server would refuse becomes null, and such a cell id is left out, so the
 * page never sends a selection the server refuses.
 */
export function parseSelection(value: unknown): Selection | null | undefined {
	if (value === null) return null;
	if (typeof value !== 'object' || Array.isArray(value)) return undefined;
	const { page, cells } = value as Record<string, unknown>;
	if (!Array.isArray(cells)) return undefined;
	const kept = [...new Set(cells.filter(isId))];
	if (kept.length === 0 || kept.length > SELECTION_LIMIT) return null;
	return { page: isId(page) ? page : null, cells: kept };
}

/**
 * Return the view one of drawio's answers describes, or null. segl's
 * `PostConfig.js` adds `scroll` and `pageId` to them: the diagram's point at
 * the top left is the scroll over the scale, less the translation.
 */
export function viewOf(reply: Reply): DiagramView | null {
	const { scale, translate, scroll } = reply;
	if (typeof scale !== 'number' || !(scale > 0)) return null;
	if (typeof translate !== 'object' || translate === null) return null;
	if (typeof scroll !== 'object' || scroll === null) return null;
	const { x, y } = translate as Record<string, unknown>;
	const { left, top } = scroll as Record<string, unknown>;
	if (![x, y, left, top].every((value) => typeof value === 'number' && Number.isFinite(value))) {
		return null;
	}
	const { pageId } = reply;
	return {
		scale,
		x: (left as number) / scale - (x as number),
		y: (top as number) / scale - (y as number),
		page: typeof pageId === 'string' && pageId !== '' ? pageId : null
	};
}
