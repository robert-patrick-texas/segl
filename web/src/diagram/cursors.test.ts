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

import { readFileSync } from 'node:fs';
import { expect, test } from 'vitest';
import { cursorColor, frameCursors } from './cursors.ts';

/** The pinned editor's unminified build, which holds its own color rule. */
const EDITOR_BUILD = new URL(
	'../../node_modules/@excalidraw/excalidraw/dist/dev/index.js',
	import.meta.url
);

type EditorColor = (socketId: string, collaborator?: { id?: string }) => string;

/** The editor's `getClientColor`, taken from its build as it is. */
function editorColor(): EditorColor {
	const source = readFileSync(EDITOR_BUILD, 'utf8');
	const hash = /function hashToInteger\(id\) \{[\s\S]*?\n\}/.exec(source);
	const color = /var getClientColor = \(socketId, collaborator\) => \{[\s\S]*?\n\};/.exec(source);
	if (hash === null || color === null) throw new Error('the editor’s color rule moved');
	return new Function(`${hash[0]}\n${color[0]}\nreturn getClientColor;`)() as EditorColor;
}

/** Ids like the server's: 12 characters of the URL-safe alphabet. */
function ids(count: number): string[] {
	const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_';
	let seed = 7;
	const random = () => {
		seed = (seed * 1103515245 + 12345) % 2 ** 31;
		return seed / 2 ** 31;
	};
	return Array.from({ length: count }, () =>
		Array.from({ length: 12 }, () => alphabet[Math.floor(random() * alphabet.length)]).join('')
	);
}

test('a cursor has the color the whiteboards’ editor gives the same connection', () => {
	const theirs = editorColor();
	for (const id of [...ids(500), '', 'me', 'other']) {
		// segl gives the editor the connection id as the collaborator's id.
		expect(cursorColor(id)).toBe(theirs(id, { id }));
	}
});

test('the frame draws the others’ cursors that have one, with a name', () => {
	const shown = frameCursors(
		[
			{ connectionId: 'me', displayName: 'Ann', cursor: { x: 1, y: 2, page: 'p1' } },
			{ connectionId: 'b', displayName: 'Bea', cursor: { x: 3, y: 4, page: 'p2' } },
			{ connectionId: 'c', displayName: null, cursor: { x: 5, y: 6 } },
			{ connectionId: 'd', displayName: 'Dee', cursor: null }
		],
		'me'
	);
	expect(shown).toEqual([
		{ id: 'b', name: 'Bea', color: cursorColor('b'), x: 3, y: 4, page: 'p2' },
		{ id: 'c', name: 'Unnamed', color: cursorColor('c'), x: 5, y: 6, page: null }
	]);
});
