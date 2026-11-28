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
import { diagramOf, parseDiagramMessage, penOfWelcome } from './protocol.ts';

const entry = { n: 3, pid: 'p', patch: { u: {} }, checksum: -4, exact: true };

describe('parseDiagramMessage', () => {
	test('a whole diagram carries its xml', () => {
		const message = {
			type: 'diagram',
			epoch: 2,
			whole: true,
			mark: 's.2.3',
			count: 3,
			xml: '<m/>',
			patches: [entry]
		};

		expect(parseDiagramMessage(JSON.stringify(message))).toEqual(message);
	});

	test('the patches since a mark carry no xml', () => {
		const message = {
			type: 'diagram',
			epoch: 2,
			whole: false,
			mark: 's.2.3',
			count: 2,
			patches: [entry]
		};

		expect(parseDiagramMessage(JSON.stringify(message))).toEqual({ ...message, xml: null });
	});

	test('a numbered patch', () => {
		const message = { type: 'patch', epoch: 1, mark: 's.1.3', ...entry };

		expect(parseDiagramMessage(JSON.stringify(message))).toEqual(message);
	});

	test.each([
		[
			'a whole diagram without xml',
			{ type: 'diagram', epoch: 1, whole: true, count: 0, patches: [] }
		],
		['a count below 0', { type: 'diagram', epoch: 1, whole: false, count: -1, patches: [] }],
		[
			'patches that are not a list',
			{ type: 'diagram', epoch: 1, whole: false, count: 0, patches: {} }
		],
		['a patch numbered 0', { type: 'patch', epoch: 1, ...entry, n: 0 }],
		['a patch that is not an object', { type: 'patch', epoch: 1, ...entry, patch: [] }],
		['a checksum that is not whole', { type: 'patch', epoch: 1, ...entry, checksum: 1.5 }],
		['exact that is not true or false', { type: 'patch', epoch: 1, ...entry, exact: 1 }],
		['a pen holder that is empty', { type: 'pen', holder: '' }],
		['a pen with no holder field', { type: 'pen' }],
		['a selection of nobody', { type: 'selection', selection: null }],
		['a selection with no selection field', { type: 'selection', connectionId: 'c1' }],
		[
			'a selection of an empty connection id',
			{ type: 'selection', connectionId: '', selection: { page: null, cells: ['a'] } }
		],
		[
			'a selection of no cells',
			{ type: 'selection', connectionId: 'c1', selection: { page: null, cells: [] } }
		],
		[
			'a selection of 51 cells',
			{
				type: 'selection',
				connectionId: 'c1',
				selection: { page: null, cells: Array.from({ length: 51 }, (_, i) => `c${i}`) }
			}
		],
		[
			'a selection with a cell id that is not text',
			{ type: 'selection', connectionId: 'c1', selection: { page: null, cells: [7] } }
		],
		[
			'a selection with a cell id too long',
			{ type: 'selection', connectionId: 'c1', selection: { page: null, cells: ['x'.repeat(129)] } }
		],
		[
			'a selection on an empty page id',
			{ type: 'selection', connectionId: 'c1', selection: { page: '', cells: ['a'] } }
		],
		[
			'a selection with no page field',
			{ type: 'selection', connectionId: 'c1', selection: { cells: ['a'] } }
		]
	])('%s is not a message', (_, message) => {
		expect(parseDiagramMessage(JSON.stringify(message))).toBeNull();
	});

	test('who holds the pen, or nobody', () => {
		expect(parseDiagramMessage('{"type":"pen","holder":"c1"}')).toEqual({
			type: 'pen',
			holder: 'c1'
		});
		expect(parseDiagramMessage('{"type":"pen","holder":null}')).toEqual({
			type: 'pen',
			holder: null
		});
	});

	test('another connection’s selection, of up to 50 cells, or of nothing', () => {
		const fifty = Array.from({ length: 50 }, (_, i) => `cell-${i}`);
		const on = {
			type: 'selection',
			connectionId: 'c1',
			selection: { page: 'p'.repeat(128), cells: ['x'.repeat(128), ...fifty.slice(1)] }
		};
		const nowhere = {
			type: 'selection',
			connectionId: 'c2',
			selection: { page: null, cells: ['a'] }
		};
		const none = { type: 'selection', connectionId: 'c3', selection: null };

		expect(parseDiagramMessage(JSON.stringify(on))).toEqual(on);
		expect(parseDiagramMessage(JSON.stringify(nowhere))).toEqual(nowhere);
		expect(parseDiagramMessage(JSON.stringify(none))).toEqual(none);
	});

	test('a whiteboard message is read as the whiteboards read it', () => {
		const saved = { type: 'saved', epoch: 1, savedAt: '2026-11-27T10:00:00.000Z', seq: 4 };

		expect(parseDiagramMessage(JSON.stringify(saved))).toEqual(saved);
		expect(parseDiagramMessage('not json')).toBeNull();
	});
});

test('the pen of a welcome', () => {
	expect(penOfWelcome('{"type":"welcome","pen":"c1"}')).toBe('c1');
	expect(penOfWelcome('{"type":"welcome","pen":null}')).toBeNull();
	expect(penOfWelcome('{"type":"welcome"}')).toBeNull();
	expect(penOfWelcome('{"type":"saved","pen":"c1"}')).toBeNull();
	expect(penOfWelcome('{')).toBeNull();
});

test('the diagram of a stored head', () => {
	expect(diagramOf({ diagram: '<mxfile/>' })).toBe('<mxfile/>');
	expect(diagramOf({ elements: [] })).toBe('');
	expect(diagramOf(null)).toBe('');
});
