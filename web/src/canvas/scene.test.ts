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

import { expect, test } from 'vitest';
import emptyScene from '../../../src/segl/empty_scene.json' with { type: 'json' };
import { initialDataFrom } from './scene.ts';

test('the bootstrap fixture gives its elements and its app state', () => {
	expect(initialDataFrom(emptyScene)).toEqual({
		elements: [],
		appState: emptyScene.appState
	});
});

test('a drawn scene keeps its elements, app state, and files', () => {
	const elements = [{ id: 'a', type: 'rectangle', version: 3 }];
	const appState = { viewBackgroundColor: '#fff' };
	const files = { f1: { id: 'f1', mimeType: 'image/png' } };

	expect(initialDataFrom({ type: 'excalidraw', elements, appState, files })).toEqual({
		elements,
		appState,
		files
	});
});

test('the placeholder from before the fixture is an empty canvas', () => {
	expect(initialDataFrom({ elements: [] })).toEqual({ elements: [] });
});

test.each([null, undefined, 'text', 7, [], { elements: 'x', appState: [], files: 3 }])(
	'%j is an empty canvas, not an error',
	(document) => {
		expect(initialDataFrom(document)).toEqual({ elements: [] });
	}
);
