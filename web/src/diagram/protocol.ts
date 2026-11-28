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
 * Diagram mode's messages on the collaboration socket, slot 9's (docs/API.md,
 * "Diagram mode"). The rest, `welcome` and `presence` among them, are the
 * whiteboards' (`../collab/protocol.ts`).
 */
import { markOf, parseServerMessage, type ServerMessage } from '../collab/protocol.ts';
import type { Selection } from './frame.ts';

/** A drawio patch, as drawio's diff sync makes it. segl does not read one. */
export type DrawioPatch = Record<string, unknown>;

/** One numbered patch, as the server sends it on. */
export interface NumberedPatch {
	/** Its number: the server takes patches in this order. */
	n: number;
	/** The id the page that made it gave it. */
	pid: string;
	patch: DrawioPatch;
	/** drawio's checksum of its sender's diagram after it, or null. */
	checksum: number | null;
	/** Its sender held every patch before it, so its checksum is the diagram's. */
	exact: boolean;
}

export type DiagramMessage =
	| {
			type: 'diagram';
			epoch: number;
			/** The whole diagram, `xml`, or only the patches after `count`. */
			whole: boolean;
			mark: string | null;
			/** The newest patch the xml holds, or the one the page's mark named. */
			count: number;
			xml: string | null;
			patches: NumberedPatch[];
	  }
	| ({ type: 'patch'; epoch: number; mark: string | null } & NumberedPatch)
	/** Who holds the pen now: a connection id, or null when it is free. */
	| { type: 'pen'; holder: string | null }
	/** What another connection has selected now, or null for nothing (T19). */
	| { type: 'selection'; connectionId: string; selection: Selection | null };

/** What the server sends on slot 9: one of the above, or a whiteboard's message. */
export type SlotNineMessage = DiagramMessage | ServerMessage;

export type DiagramClientMessage =
	| {
			type: 'patch';
			epoch: number;
			/** The newest numbered patch this page holds. */
			base: number;
			pid: string;
			patch: DrawioPatch;
			checksum: number | null;
			/** The page's whole diagram, with this patch. */
			xml: string;
			seq: number;
	  }
	| { type: 'copy'; epoch: number; base: number; xml: string }
	| { type: 'reload' }
	| { type: 'pen'; take: boolean }
	/** What this browser has selected, or null: nothing, or more than 50 cells. */
	| { type: 'selection'; selection: Selection | null };

type Fields = Record<string, unknown>;

function isFields(value: unknown): value is Fields {
	return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isCount(value: unknown): value is number {
	return Number.isInteger(value) && (value as number) >= 0;
}

function numbered(value: unknown): NumberedPatch | null {
	if (!isFields(value)) return null;
	const { n, pid, patch, checksum, exact } = value;
	if (!isCount(n) || n < 1 || typeof pid !== 'string' || !isFields(patch)) return null;
	if (checksum !== null && !Number.isInteger(checksum)) return null;
	if (typeof exact !== 'boolean') return null;
	return { n, pid, patch, checksum: checksum as number | null, exact };
}

/** The most cells a selection names: more than this is sent as none. */
export const MAX_SELECTED = 50;

/** The longest page or cell id a selection names. */
const MAX_ID_LENGTH = 128;

function isId(value: unknown): value is string {
	return typeof value === 'string' && value.length >= 1 && value.length <= MAX_ID_LENGTH;
}

/** Return a selection a message carries, null for none, or undefined when it is not one. */
function selectionOf(value: unknown): Selection | null | undefined {
	if (value === null) return null;
	if (!isFields(value)) return undefined;
	const { page, cells } = value;
	if (page !== null && !isId(page)) return undefined;
	if (!Array.isArray(cells) || cells.length < 1 || cells.length > MAX_SELECTED) return undefined;
	if (!cells.every(isId)) return undefined;
	return { page, cells };
}

function holderOf(value: unknown): string | null | undefined {
	if (value === null) return null;
	return typeof value === 'string' && value !== '' ? value : undefined;
}

/**
 * Return a message the server sent on slot 9, or null for text that is not
 * one this page knows. A `welcome` comes back as the whiteboards' parser
 * reads it. `penOfWelcome` reads who holds the pen from its text.
 */
export function parseDiagramMessage(text: unknown): SlotNineMessage | null {
	let message: unknown;
	try {
		message = typeof text === 'string' ? JSON.parse(text) : null;
	} catch {
		return null;
	}
	if (!isFields(message)) return null;
	switch (message['type']) {
		case 'diagram': {
			const { epoch, whole, count, xml, patches } = message;
			if (!Number.isInteger(epoch) || typeof whole !== 'boolean' || !isCount(count)) return null;
			if (!Array.isArray(patches)) return null;
			const list = patches.map(numbered);
			if (list.includes(null)) return null;
			if (whole && typeof xml !== 'string') return null;
			return {
				type: 'diagram',
				epoch: epoch as number,
				whole,
				mark: markOf(message['mark']),
				count,
				xml: whole ? (xml as string) : null,
				patches: list as NumberedPatch[]
			};
		}
		case 'patch': {
			const entry = numbered(message);
			const { epoch } = message;
			if (entry === null || !Number.isInteger(epoch)) return null;
			return { type: 'patch', epoch: epoch as number, mark: markOf(message['mark']), ...entry };
		}
		case 'pen': {
			const holder = holderOf(message['holder']);
			return holder === undefined ? null : { type: 'pen', holder };
		}
		case 'selection': {
			const { connectionId } = message;
			const selection = selectionOf(message['selection']);
			if (typeof connectionId !== 'string' || connectionId === '' || selection === undefined) {
				return null;
			}
			return { type: 'selection', connectionId, selection };
		}
		default:
			return parseServerMessage(text);
	}
}

/** Return who holds the pen as a `welcome` on slot 9 says, or null. */
export function penOfWelcome(text: unknown): string | null {
	try {
		const message: unknown = typeof text === 'string' ? JSON.parse(text) : null;
		if (!isFields(message) || message['type'] !== 'welcome') return null;
		return holderOf(message['pen']) ?? null;
	} catch {
		return null;
	}
}

/** Return the diagram a stored head of slot 9 holds, `{ "diagram": xml }`, or `''`. */
export function diagramOf(document: unknown): string {
	return isFields(document) && typeof document['diagram'] === 'string' ? document['diagram'] : '';
}
