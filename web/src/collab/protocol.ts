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

/** A cursor, in the canvas's own coordinates. */
export interface Cursor {
	x: number;
	y: number;
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
			connectionId: string;
			participants: Participant[];
	  }
	| { type: 'scene'; epoch: number; elements: WireElement[]; files: FileRef[] }
	| { type: 'elements'; epoch: number; elements: WireElement[] }
	| { type: 'files'; epoch: number; files: FileRef[] }
	| { type: 'saved'; epoch: number; savedAt: string; seq: number }
	| { type: 'slot'; slot: number; title: string }
	| ({ type: 'presence'; cursor: Cursor | null } & Participant)
	| { type: 'presence-end'; connectionId: string }
	| { type: 'error'; error: string; message: string };

/**
 * `seq` numbers the messages that change what is stored. The server answers
 * with `saved` and the number of the newest one that is on the disk.
 */
export type ClientMessage =
	| { type: 'hello'; clientId: string; displayName: string | null; editToken: string }
	| { type: 'elements'; epoch: number; elements: WireElement[]; seq: number }
	| { type: 'files'; epoch: number; files: FileRef[]; seq: number }
	| { type: 'presence'; cursor: Cursor | null }
	| { type: 'rename'; displayName: string };

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

function cursor(value: unknown): Cursor | null | undefined {
	if (value === null) return null;
	if (!isFields(value)) return undefined;
	const { x, y } = value;
	return Number.isFinite(x) && Number.isFinite(y) ? { x: x as number, y: y as number } : undefined;
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
			const { slot, title, epoch, viewOnly, connectionId, participants } = message;
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
				connectionId,
				participants: people as Participant[]
			};
		}
		case 'scene': {
			const list = elements(message['elements']);
			// A scene from a segl older than the file list has none.
			const files = parseFileRefs(message['files'] ?? []);
			const { epoch } = message;
			if (list === null || files === null || !Number.isInteger(epoch)) return null;
			return { type: 'scene', epoch: epoch as number, elements: list, files };
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
		case 'error': {
			const { error, message: said } = message;
			if (typeof error !== 'string') return null;
			return { type: 'error', error, message: typeof said === 'string' ? said : error };
		}
		default:
			return null;
	}
}
