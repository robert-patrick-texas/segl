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
 * The bar as the server renders it to text: which parts it shows on a slot.
 * History stands in as its props: its list opens and loads only in a
 * browser. What a press does is the browser tests' (web/e2e/).
 */
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router';
import { expect, test, vi } from 'vitest';
import type { HistoryControlProps } from './HistoryControl.tsx';
import { CANNOT_FOLLOW } from './presence.ts';
import { SeglBar, type SeglBarProps } from './SeglBar.tsx';
import { RELOAD, UPDATED } from './update.ts';

function props(change: Partial<SeglBarProps> = {}): SeglBarProps {
	return {
		slot: 3,
		titles: new Map(),
		editing: 'open',
		version: '0.9.0',
		serverVersion: '0.9.0',
		displayName: 'Alpha1',
		onRename: () => null,
		status: 'live',
		participants: [{ connectionId: 'me', displayName: 'Alpha1' }],
		self: 'me',
		following: null,
		onFollow: () => {},
		followRefused: false,
		canEdit: true,
		onRetitle: async () => {},
		epoch: 1,
		onLoadHistory: async () => [],
		onRestore: async () => {},
		importFile: null,
		onChooseImport: () => {},
		onImport: async () => {},
		...change
	};
}

vi.mock('./HistoryControl.tsx', () => ({
	HistoryControl: ({ canRestore, penHeld, connected }: HistoryControlProps) =>
		createElement('div', {
			'data-testid': 'history',
			'data-can-restore': String(canRestore),
			'data-pen-held': String(penHeld),
			'data-connected': String(connected)
		})
}));

const DIAGRAM = { holder: null, mine: false, onPen: () => {} };

function bar(change: Partial<SeglBarProps> = {}): string {
	return renderToStaticMarkup(
		createElement(MemoryRouter, null, createElement(SeglBar, props(change)))
	);
}

test('a whiteboard’s bar shows History and Import, and no pen', () => {
	const html = bar();

	expect(html).toContain('data-testid="history"');
	expect(html).toContain('segl-bar__import');
	expect(html).not.toContain('segl-bar__pen');
});

test('slot 9’s bar shows History beside the pen, and no Import', () => {
	const html = bar({ slot: 9, diagram: DIAGRAM });

	expect(html).toContain('data-testid="history"');
	expect(html).not.toContain('segl-bar__import');
	expect(html.indexOf('segl-bar__pen')).toBeLessThan(html.indexOf('data-testid="history"'));
});

test('History on slot 9 offers no Restore while another connection holds the pen', () => {
	expect(bar({ slot: 9, diagram: { ...DIAGRAM, holder: 'Bravo2' } })).toContain(
		'data-pen-held="true"'
	);
	expect(bar({ slot: 9, diagram: { ...DIAGRAM, holder: 'Alpha1', mine: true } })).toContain(
		'data-pen-held="false"'
	);
	expect(bar({ slot: 9, diagram: DIAGRAM })).toContain('data-pen-held="false"');
	expect(bar()).toContain('data-pen-held="false"');
	// Restoring still needs a code, and a connection.
	expect(bar({ slot: 9, diagram: DIAGRAM, canEdit: false })).toContain('data-can-restore="false"');
	expect(bar({ slot: 9, diagram: DIAGRAM, status: 'disconnected' })).toContain(
		'data-connected="false"'
	);
});

test('the update notice shows only when the server names another version', () => {
	expect(bar({ serverVersion: '1.0.0' })).toContain(UPDATED);
	expect(bar({ serverVersion: '1.0.0' })).toContain(`>${RELOAD}</button>`);
	expect(bar({ serverVersion: '0.9.0' })).not.toContain(UPDATED);
	expect(bar({ serverVersion: null })).not.toContain(UPDATED);
	expect(bar({ slot: 9, diagram: DIAGRAM, serverVersion: '1.0.0' })).toContain(UPDATED);
});

test('a refused follow is said while the session says so', () => {
	// React writes the apostrophe as a character reference.
	const said = CANNOT_FOLLOW.replace("'", '&#x27;');

	expect(bar({ followRefused: true })).toContain(said);
	expect(bar({ followRefused: false })).not.toContain(said);
	expect(bar({ slot: 9, diagram: DIAGRAM, followRefused: true })).toContain(said);
});
