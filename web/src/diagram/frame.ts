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
 */
import type { DrawioPatch } from './protocol.ts';

/** The frame's window, as the adapter posts to it. */
export interface FrameTarget {
	postMessage(message: string, targetOrigin: string): void;
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

/** Where a person is looking: the scale, and the diagram's point at the top left. */
export interface DiagramView {
	scale: number;
	x: number;
	y: number;
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
	 * or off. With a view, the person keeps looking where they were.
	 */
	load(xml: string, readOnly: boolean, view?: DiagramView | null): Promise<void>;
	/** Apply another browser's patch. With a checksum, drawio compares it. */
	patch(patch: DrawioPatch, checksum: number | null): Promise<PatchResult>;
	/** Return the frame's whole diagram. */
	xml(): Promise<string>;
	/** Return where the person is looking, or null when drawio did not say. */
	view(): Promise<DiagramView | null>;
	/** Settles when no label is being edited in the frame. */
	idle(): Promise<void>;
	/** Keep drawio's read-only view on, or off. */
	setReadOnly(value: boolean): void;
}

export interface FrameOptions {
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

type Reply = Record<string, unknown>;

interface Waiting {
	event: string;
	resolve(reply: Reply): void;
}

export class DiagramFrame implements DiagramFrameLike {
	readonly ready: Promise<void>;
	private readonly options: FrameOptions;
	private markReady!: () => void;
	private isReady = false;
	/** The actions posted and not yet answered: one at a time. */
	private waiting: Waiting | null = null;
	private queue: Array<{ action: Reply; event: string; resolve(reply: Reply): void }> = [];
	/** The read-only view the page wants, and the one drawio last said it has. */
	private wantReadOnly = false;
	private readOnly: boolean | null = null;
	private toggling = false;
	/** A label editor is open in the frame, and what waits for it to close. */
	private editing = false;
	private waitingIdle: Array<() => void> = [];

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
				if (!this.editing) {
					for (const resolve of this.waitingIdle.splice(0)) resolve();
				}
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
		if (view !== null) {
			// drawio scales, then scrolls this point of the diagram to the top left.
			action['scale'] = view.scale;
			action['scroll'] = { x: view.x, y: view.y };
		}
		return this.post(action, 'load').then(() => undefined);
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
		if (!this.editing) return Promise.resolve();
		return new Promise((resolve) => this.waitingIdle.push(resolve));
	}

	setReadOnly(value: boolean): void {
		this.wantReadOnly = value;
		this.keepReadOnly();
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

	private post(action: Reply, event: string): Promise<Reply> {
		return new Promise((resolve) => {
			this.queue.push({ action, event, resolve });
			this.next();
		});
	}

	private next(): void {
		if (this.waiting !== null || !this.isReady) return;
		const item = this.queue.shift();
		const target = this.options.target();
		if (item === undefined || target === null) {
			if (item !== undefined) this.queue.unshift(item);
			return;
		}
		this.waiting = { event: item.event, resolve: item.resolve };
		target.postMessage(JSON.stringify(item.action), this.options.origin);
	}
}

/**
 * Return the view one of drawio's answers describes, or null. segl's
 * `PostConfig.js` adds `scroll` to them: the diagram's point at the top left
 * is the scroll over the scale, less the translation.
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
	return {
		scale,
		x: (left as number) / scale - (x as number),
		y: (top as number) / scale - (y as number)
	};
}
