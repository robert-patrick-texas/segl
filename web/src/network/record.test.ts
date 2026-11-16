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

import { describe, expect, test } from 'vitest';
import { DEVICE_KINDS, LINK_KINDS, STATES } from './kinds.ts';
import {
	isObjectRecord,
	isTagRecord,
	newObjectId,
	readRecord,
	UNPLACED,
	withRecord,
	type Carrier,
	type ObjectRecord,
	type TagRecord
} from './record.ts';

const ID = '3f2c9a4e-8b1d-4c6e-9f00-1234567890ab';

function carrying(type: string, segl: unknown, extra: Record<string, unknown> = {}): Carrier {
	return { type, customData: { ...extra, segl } };
}

const device: ObjectRecord = {
	schemaVersion: 1,
	objectId: ID,
	objectType: 'router',
	state: 'planned'
};
const link: ObjectRecord = {
	schemaVersion: 1,
	objectId: ID,
	objectType: 'cable',
	state: 'existing'
};
const tag: TagRecord = { schemaVersion: 1, objectId: ID, part: 'tag' };

describe('a good record', () => {
	test.each(['rectangle', 'ellipse', 'diamond'])('a device on a %s', (type) => {
		expect(readRecord(carrying(type, device))).toEqual(device);
	});

	test.each(DEVICE_KINDS)('every device kind: %s', (objectType) => {
		expect(readRecord(carrying('rectangle', { ...device, objectType }))).toEqual({
			...device,
			objectType
		});
	});

	test.each(LINK_KINDS)('every link kind, on an arrow: %s', (objectType) => {
		expect(readRecord(carrying('arrow', { ...link, objectType }))).toEqual({ ...link, objectType });
	});

	test.each(STATES)('every state: %s', (state) => {
		const record = readRecord(carrying('rectangle', { ...device, state }));
		expect(isObjectRecord(record) && record.state).toBe(state);
	});

	test('a tag, on a text', () => {
		const record = readRecord(carrying('text', tag));
		expect(record).toEqual(tag);
		expect(isTagRecord(record)).toBe(true);
		expect(isObjectRecord(record)).toBe(false);
	});

	test("the library's id is a record too", () => {
		expect(readRecord(carrying('rectangle', { ...device, objectId: UNPLACED }))?.objectId).toBe(
			UNPLACED
		);
	});

	test('other keys of customData stay out of the record', () => {
		const record = readRecord(carrying('rectangle', device, { theirs: { note: 'kept' } }));
		expect(record).toEqual(device);
		expect(isObjectRecord(record)).toBe(true);
	});
});

describe('no record', () => {
	test.each([
		['no customData', { type: 'rectangle' }],
		['customData of another kind', { type: 'rectangle', customData: 'segl' }],
		['customData without segl', { type: 'rectangle', customData: { other: 1 } }],
		['segl that is not an object', { type: 'rectangle', customData: { segl: 'router' } }],
		['segl that is a list', { type: 'rectangle', customData: { segl: [device] } }],
		['segl that is null', { type: 'rectangle', customData: { segl: null } }]
	])('%s', (_name, element) => {
		expect(readRecord(element as Carrier)).toBeNull();
	});
});

describe('each bad shape', () => {
	test.each([
		['schema version 2', { ...device, schemaVersion: 2 }],
		['schema version as text', { ...device, schemaVersion: '1' }],
		['no schema version', { objectId: ID, objectType: 'router', state: 'planned' }],
		['an id that is no UUID', { ...device, objectId: 'router-1' }],
		['an id in capitals', { ...device, objectId: ID.toUpperCase() }],
		['an id with braces', { ...device, objectId: `{${ID}}` }],
		['an id that is a number', { ...device, objectId: 7 }],
		['no id', { schemaVersion: 1, objectType: 'router', state: 'planned' }],
		['an unknown kind', { ...device, objectType: 'unknown' }],
		['a kind in capitals', { ...device, objectType: 'Router' }],
		['an unknown state', { ...device, state: 'observed' }],
		['no state', { schemaVersion: 1, objectId: ID, objectType: 'router' }],
		['a key more', { ...device, scenarioId: ID }],
		['a tag with a kind', { ...tag, objectType: 'router' }],
		['a part that is not a tag', { ...tag, part: 'label' }]
	])('%s', (_name, segl) => {
		expect(readRecord(carrying('rectangle', segl))).toBeNull();
		expect(readRecord(carrying('text', segl))).toBeNull();
		expect(readRecord(carrying('arrow', segl))).toBeNull();
	});

	test.each([
		['a device on an arrow', 'arrow', device],
		['a device on a line', 'line', device],
		['a device on a text', 'text', device],
		['a link on a rectangle', 'rectangle', link],
		['a link on a line', 'line', link],
		['a tag on a rectangle', 'rectangle', tag],
		['a tag on an arrow', 'arrow', tag]
	])('%s', (_name, type, segl) => {
		expect(readRecord(carrying(type, segl))).toBeNull();
	});
});

describe('withRecord', () => {
	test('puts the record in and keeps what else is there', () => {
		expect(withRecord({ theirs: 1, segl: { old: true } }, device)).toEqual({
			theirs: 1,
			segl: device
		});
	});

	test('starts from nothing', () => {
		expect(withRecord(undefined, tag)).toEqual({ segl: tag });
		expect(withRecord('junk', tag)).toEqual({ segl: tag });
	});

	test('does not share the record it was given', () => {
		const given: ObjectRecord = { ...device };
		const made = withRecord(undefined, given);
		given.state = 'remove';
		expect((made['segl'] as { state: string }).state).toBe('planned');
	});
});

test('a new object id is a random UUID the record reader takes', () => {
	const ids = new Set(Array.from({ length: 50 }, () => newObjectId()));
	expect(ids.size).toBe(50);
	for (const objectId of ids) {
		expect(readRecord(carrying('rectangle', { ...device, objectId }))?.objectId).toBe(objectId);
		expect(objectId).not.toBe(UNPLACED);
	}
});
