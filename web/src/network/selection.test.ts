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
import { selectedObject, type SceneItem } from './selection.ts';

const A = 'aaaaaaaa-0000-4000-8000-000000000001';
const B = 'bbbbbbbb-0000-4000-8000-000000000002';

const router: SceneItem[] = [
	{
		id: 'card',
		type: 'rectangle',
		isDeleted: false,
		groupIds: ['g1'],
		customData: { segl: { schemaVersion: 1, objectId: A, objectType: 'router', state: 'planned' } }
	},
	{
		id: 'name',
		type: 'text',
		isDeleted: false,
		groupIds: ['g1'],
		containerId: 'card',
		originalText: 'core-1'
	},
	{ id: 'glyph', type: 'line', isDeleted: false, groupIds: ['g1'] },
	{
		id: 'tag',
		type: 'text',
		isDeleted: false,
		groupIds: ['g1'],
		containerId: null,
		originalText: 'P',
		customData: { segl: { schemaVersion: 1, objectId: A, part: 'tag' } }
	}
];

const cable: SceneItem[] = [
	{
		id: 'line',
		type: 'arrow',
		isDeleted: false,
		groupIds: [],
		customData: { segl: { schemaVersion: 1, objectId: B, objectType: 'cable', state: 'remove' } }
	},
	{
		id: 'label',
		type: 'text',
		isDeleted: false,
		groupIds: [],
		containerId: 'line',
		originalText: 'R 10G'
	}
];

const freeform: SceneItem = { id: 'free', type: 'rectangle', isDeleted: false, groupIds: [] };
const scene = [...router, ...cable, freeform];
const picked = (...ids: string[]) => selectedObject(scene, new Set(ids));

describe('one network object', () => {
	test('a device, selected as its group', () => {
		expect(picked('card', 'name', 'glyph', 'tag')).toEqual({
			objectId: A,
			objectType: 'router',
			kind: 'device',
			state: 'planned',
			name: 'core-1',
			elementId: 'card'
		});
	});

	test.each([['card'], ['name'], ['glyph'], ['tag']])('a device, by its %s alone', (id) => {
		expect(picked(id)?.objectId).toBe(A);
	});

	test("a link: its name is its label's words, without the tag", () => {
		expect(picked('line')).toEqual({
			objectId: B,
			objectType: 'cable',
			kind: 'link',
			state: 'remove',
			name: '10G',
			elementId: 'line'
		});
		expect(picked('label')?.objectId).toBe(B);
	});

	test('a device with no name, and a link with no label', () => {
		const bare = scene.filter((each) => each.id !== 'name' && each.id !== 'label');
		expect(selectedObject(bare, new Set(['card']))?.name).toBe('');
		expect(selectedObject(bare, new Set(['line']))?.name).toBe('');
	});
});

describe('no object', () => {
	test('nothing selected', () => {
		expect(picked()).toBeNull();
	});

	test('a freeform shape', () => {
		expect(picked('free')).toBeNull();
	});

	test('two objects', () => {
		expect(picked('card', 'line')).toBeNull();
	});

	test('an object and a freeform shape', () => {
		expect(picked('card', 'free')).toBeNull();
	});

	test('a deleted object', () => {
		const gone = scene.map((each) => (each.id === 'line' ? { ...each, isDeleted: true } : each));
		expect(selectedObject(gone, new Set(['line']))).toBeNull();
	});

	test('two elements that claim one object id', () => {
		const twice = [...scene, { ...router[0]!, id: 'card2', groupIds: ['g2'] }];
		expect(selectedObject(twice, new Set(['card']))).toBeNull();
	});

	test('a freeform shape the person grouped with a link', () => {
		const grouped = scene.map((each) =>
			each.id === 'line' ? { ...each, groupIds: ['g7'] } : each
		);
		const note: SceneItem = { id: 'note', type: 'rectangle', isDeleted: false, groupIds: ['g7'] };
		expect(selectedObject([...grouped, note], new Set(['line', 'note']))).toBeNull();
		expect(selectedObject([...grouped, note], new Set(['note']))).toBeNull();
		expect(selectedObject([...grouped, note], new Set(['line']))?.objectId).toBe(B);
	});

	test('a tag whose device is gone', () => {
		const orphan = scene.filter((each) => each.id !== 'card');
		expect(selectedObject(orphan, new Set(['tag']))).toBeNull();
	});

	test('an id the scene does not hold', () => {
		expect(picked('elsewhere')).toBeNull();
	});
});
