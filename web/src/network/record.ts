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
 * The record a network object carries in the scene (docs/DATA-MODEL.md,
 * network objects; D2-038).
 *
 * A device's record is on its body, and a link's on its line, as
 * `customData.segl`. A device's tag carries a short record that names the
 * object it belongs to. The page reads a record strictly: anything else is
 * no record, and the element is drawn as it is, as freeform.
 */
import { isDeviceKind, isLinkKind, isState, type ObjectType, type State } from './kinds.ts';

export const SCHEMA_VERSION = 1;

/** The object id of a library item. A placed copy always gets a new one. */
export const UNPLACED = '00000000-0000-0000-0000-000000000000';

export interface ObjectRecord {
	schemaVersion: typeof SCHEMA_VERSION;
	/** A random UUID the page made when the object was placed. Not an element id. */
	objectId: string;
	objectType: ObjectType;
	state: State;
}

export interface TagRecord {
	schemaVersion: typeof SCHEMA_VERSION;
	objectId: string;
	part: 'tag';
}

export type SeglRecord = ObjectRecord | TagRecord;

/** The part of an element a record is read from. */
export interface Carrier {
	type: string;
	customData?: unknown;
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

/** The element types a device's body may be: the editor's shapes that hold a label. */
const BODY_TYPES: readonly string[] = ['rectangle', 'ellipse', 'diamond'];

function isPlainObject(value: unknown): value is Record<string, unknown> {
	return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function hasKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
	const own = Object.keys(value);
	return own.length === keys.length && keys.every((key) => Object.hasOwn(value, key));
}

/**
 * The record in an element's `customData`, or null. It must be exactly one
 * of the two shapes, at schema version 1, with a lowercase UUID, a known
 * kind and state, and on an element of the right type: a device on a shape
 * that holds a label, a link on an arrow, and a tag on a text.
 */
export function readRecord(element: Carrier): SeglRecord | null {
	const { customData } = element;
	if (!isPlainObject(customData)) return null;
	const record = customData['segl'];
	if (!isPlainObject(record)) return null;
	if (record['schemaVersion'] !== SCHEMA_VERSION) return null;
	const objectId = record['objectId'];
	if (typeof objectId !== 'string' || !UUID.test(objectId)) return null;
	if (hasKeys(record, ['schemaVersion', 'objectId', 'part'])) {
		if (record['part'] !== 'tag' || element.type !== 'text') return null;
		return { schemaVersion: SCHEMA_VERSION, objectId, part: 'tag' };
	}
	if (!hasKeys(record, ['schemaVersion', 'objectId', 'objectType', 'state'])) return null;
	const { objectType, state } = record;
	if (!isState(state)) return null;
	if (isDeviceKind(objectType) && BODY_TYPES.includes(element.type)) {
		return { schemaVersion: SCHEMA_VERSION, objectId, objectType, state };
	}
	if (isLinkKind(objectType) && element.type === 'arrow') {
		return { schemaVersion: SCHEMA_VERSION, objectId, objectType, state };
	}
	return null;
}

export function isObjectRecord(record: SeglRecord | null): record is ObjectRecord {
	return record !== null && 'objectType' in record;
}

export function isTagRecord(record: SeglRecord | null): record is TagRecord {
	return record !== null && 'part' in record;
}

/**
 * An element's `customData` with this record in it. Whatever else the
 * element carries there is kept.
 */
export function withRecord(customData: unknown, record: SeglRecord): Record<string, unknown> {
	return { ...(isPlainObject(customData) ? customData : {}), segl: { ...record } };
}

/** A new object id: a random UUID, made by the page (D2-038). */
export function newObjectId(): string {
	return crypto.randomUUID();
}
