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
 * The messages of the collaboration socket, `collab?slot=N` (docs/API.md,
 * "WebSocket"). `parseServerMessage` checks what arrives, so that the rest of
 * the page can trust a message's shape.
 */
import { isWireElement, type WireElement } from './elements.ts';
import { parseFileRefs, type FileRef } from './files.ts';

/**
 * A cursor, in the canvas's own coordinates. On slot 9 it is in the diagram's,
 * with the id of the diagram's page it is on, or null when drawio named none.
 */
export interface Cursor {
	x: number;
	y: number;
	page?: string | null;
}

/**
 * The area a browser shows, in the canvas's coordinates, and on slot 9 the
 * diagram's, with its page (T18). Its width and height are more than 0.
 */
export interface View {
	x: number;
	y: number;
	width: number;
	height: number;
	page?: string | null;
}

/**
 * One connection on the slot. Two tabs of one browser are two of them. It
 * has no color: the editor draws its cursor in one it works out from
 * `connectionId`, the same in every browser.
 */
export interface Participant {
	connectionId: string;
	/** Null for a browser the server has not yet given a label. */
	displayName: string | null;
}

export type ServerMessage =
	| {
			type: 'welcome';
			slot: number;
			title: string;
			epoch: number;
			viewOnly: boolean;
			/**
			 * The seconds until this connection's pass ends, or null when it
			 * does not end: a viewer, a segl without access codes, or passes
			 * without a limit. A length, not a time of day, so this browser's
			 * clock does not come into it.
			 */
			editEndsIn: number | null;
			connectionId: string;
			participants: Participant[];
			/**
			 * The server's version, as `segl --version` prints it, or null when
			 * the server sent none: a segl older than T19.
			 */
			version: string | null;
	  }
	| SceneMessage
	| { type: 'elements'; epoch: number; elements: WireElement[] }
	| { type: 'files'; epoch: number; files: FileRef[] }
	| { type: 'saved'; epoch: number; savedAt: string; seq: number }
	| { type: 'slot'; slot: number; title: string }
	| ({ type: 'presence'; cursor: Cursor | null } & Participant)
	| { type: 'presence-end'; connectionId: string }
	/** How many connections follow this one now. */
	| { type: 'followers'; count: number }
	/** What the connection this one follows shows now. */
	| { type: 'view'; connectionId: string; view: View }
	| { type: 'error'; error: string; message: string };

/**
 * The room's scene. A whole one holds every element and the files they name.
 * One that is not whole holds only what changed since the mark the page sent
 * in `hello`. `mark` names what the server held when it sent this one.
 */
export interface SceneMessage {
	type: 'scene';
	epoch: number;
	elements: WireElement[];
	files: FileRef[];
	whole: boolean;
	mark: string | null;
}

/** The longest mark the server takes back in `hello`. */
export const MAX_MARK_LENGTH = 64;

/**
 * Return a mark the server sent, or null when it is not one. The page does
 * not read a mark. It hands it back.
 */
export function markOf(value: unknown): string | null {
	return typeof value === 'string' && value.length <= MAX_MARK_LENGTH ? value : null;
}

/**
 * `seq` numbers the messages that change what is stored. The server answers
 * with `saved` and the number of the newest one that is on the disk.
 */
export type ClientMessage =
	| {
			type: 'hello';
			clientId: string;
			displayName: string | null;
			editToken: string;
			/** The mark of the newest scene the server sent this page, or null. */
			mark: string | null;
	  }
	| { type: 'elements'; epoch: number; elements: WireElement[]; seq: number }
	| { type: 'files'; epoch: number; files: FileRef[]; seq: number }
	| { type: 'presence'; cursor: Cursor | null }
	| { type: 'rename'; displayName: string }
	/** Follow this connection's view, or stop: null. */
	| { type: 'follow'; connectionId: string | null }
	/** What this browser shows, for the connections that follow it. */
	| { type: 'view'; view: View };

type Fields = Record<string, unknown>;

function isFields(value: unknown): value is Fields {
	return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function participant(value: unknown): Participant | null {
	if (!isFields(value)) return null;
	const { connectionId, displayName } = value;
	if (typeof connectionId !== 'string' || connectionId === '') return null;
	if (displayName !== null && typeof displayName !== 'string') return null;
	return { connectionId, displayName };
}

/** The page a cursor or a view names: its id, null, or undefined when it names none. */
function pageOf(value: Fields): string | null | undefined | false {
	if (!('page' in value)) return undefined;
	const { page } = value;
	return page === null || (typeof page === 'string' && page !== '') ? page : false;
}

function cursor(value: unknown): Cursor | null | undefined {
	if (value === null) return null;
	if (!isFields(value)) return undefined;
	const { x, y } = value;
	const page = pageOf(value);
	if (!Number.isFinite(x) || !Number.isFinite(y) || page === false) return undefined;
	const point: Cursor = { x: x as number, y: y as number };
	if (page !== undefined) point.page = page;
	return point;
}

/** Return a view a message carries, or null when it is not one. */
export function parseView(value: unknown): View | null {
	if (!isFields(value)) return null;
	const { x, y, width, height } = value;
	const page = pageOf(value);
	if (![x, y, width, height].every(Number.isFinite) || page === false) return null;
	if (!((width as number) > 0 && (height as number) > 0)) return null;
	const view: View = {
		x: x as number,
		y: y as number,
		width: width as number,
		height: height as number
	};
	if (page !== undefined) view.page = page;
	return view;
}

function elements(value: unknown): WireElement[] | null {
	return Array.isArray(value) && value.every(isWireElement) ? value : null;
}

/**
 * Return a message the server sent, or null for text that is not one this
 * page knows: not JSON, another shape, or a type from a later segl.
 */
export function parseServerMessage(text: unknown): ServerMessage | null {
	let message: unknown;
	try {
		message = typeof text === 'string' ? JSON.parse(text) : null;
	} catch {
		return null;
	}
	if (!isFields(message)) return null;
	switch (message['type']) {
		case 'welcome': {
			const { slot, title, epoch, viewOnly, editEndsIn, connectionId, participants } = message;
			if (!Array.isArray(participants)) return null;
			const people = participants.map(participant);
			if (
				typeof slot !== 'number' ||
				typeof title !== 'string' ||
				!Number.isInteger(epoch) ||
				typeof viewOnly !== 'boolean' ||
				typeof connectionId !== 'string' ||
				people.includes(null)
			) {
				return null;
			}
			return {
				type: 'welcome',
				slot,
				title,
				epoch: epoch as number,
				viewOnly,
				// Anything else in its place is no length. The server still refuses
				// an edit after the end, so the page works without it.
				editEndsIn:
					typeof editEndsIn === 'number' && Number.isFinite(editEndsIn) && editEndsIn >= 0
						? editEndsIn
						: null,
				connectionId,
				participants: people as Participant[],
				// Anything but text is no version: the page then says nothing of an update.
				version:
					typeof message['version'] === 'string' && message['version'] !== ''
						? message['version']
						: null
			};
		}
		case 'scene': {
			const list = elements(message['elements']);
			// A scene from a segl older than the file list has none.
			const files = parseFileRefs(message['files'] ?? []);
			const { epoch } = message;
			if (list === null || files === null || !Number.isInteger(epoch)) return null;
			return {
				type: 'scene',
				epoch: epoch as number,
				elements: list,
				files,
				// Whole unless it says otherwise: a segl older than marks sends only whole ones.
				whole: message['whole'] !== false,
				mark: markOf(message['mark'])
			};
		}
		case 'elements': {
			const list = elements(message['elements']);
			const { epoch } = message;
			if (list === null || !Number.isInteger(epoch)) return null;
			return { type: 'elements', epoch: epoch as number, elements: list };
		}
		case 'files': {
			const files = parseFileRefs(message['files']);
			const { epoch } = message;
			if (files === null || !Number.isInteger(epoch)) return null;
			return { type: 'files', epoch: epoch as number, files };
		}
		case 'saved': {
			const { epoch, savedAt, seq } = message;
			if (!Number.isInteger(epoch) || typeof savedAt !== 'string' || !Number.isInteger(seq)) {
				return null;
			}
			return { type: 'saved', epoch: epoch as number, savedAt, seq: seq as number };
		}
		case 'slot': {
			const { slot, title } = message;
			if (typeof slot !== 'number' || typeof title !== 'string') return null;
			return { type: 'slot', slot, title };
		}
		case 'presence': {
			const who = participant(message);
			const where = cursor(message['cursor']);
			if (who === null || where === undefined) return null;
			return { type: 'presence', ...who, cursor: where };
		}
		case 'presence-end': {
			const { connectionId } = message;
			if (typeof connectionId !== 'string') return null;
			return { type: 'presence-end', connectionId };
		}
		case 'followers': {
			const { count } = message;
			if (!Number.isInteger(count) || (count as number) < 0) return null;
			return { type: 'followers', count: count as number };
		}
		case 'view': {
			const { connectionId } = message;
			const view = parseView(message['view']);
			if (typeof connectionId !== 'string' || view === null) return null;
			return { type: 'view', connectionId, view };
		}
		case 'error': {
			const { error, message: said } = message;
			if (typeof error !== 'string') return null;
			return { type: 'error', error, message: typeof said === 'string' ? said : error };
		}
		default:
			return null;
	}
}
