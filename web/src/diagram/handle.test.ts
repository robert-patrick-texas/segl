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

import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import type { DiagramFrameLike } from './frame.ts';
import { installDiagramHandle } from './handle.ts';
import type { DiagramSession } from './session.ts';

/** The session's part the handle reads, and what it was asked to do. */
function fakeSession(selection: unknown) {
	const asked: string[] = [];
	const session = {
		counts: { mismatches: 1, reloads: 2 },
		view: () => null,
		repair: () => asked.push('repair'),
		selection: () => selection
	};
	return { session: session as unknown as DiagramSession, asked };
}

const frame = { xml: async () => '<mxfile/>' } as unknown as DiagramFrameLike;

beforeEach(() => {
	vi.stubGlobal('window', {});
});

afterEach(() => {
	vi.unstubAllGlobals();
});

test('repair asks the session for the whole diagram, as after a drift', () => {
	const { session, asked } = fakeSession(null);
	installDiagramHandle(frame, session);

	window.SEGL_DIAGRAM?.repair();

	expect(asked).toEqual(['repair']);
});

test('selection is this browser’s, as JSON text, or null', () => {
	const selected = fakeSession({ page: 'page-3', cells: ['a', 'b'] });
	const remove = installDiagramHandle(frame, selected.session);
	expect(window.SEGL_DIAGRAM?.selection()).toBe('{"page":"page-3","cells":["a","b"]}');
	remove();

	installDiagramHandle(frame, fakeSession(null).session);
	expect(window.SEGL_DIAGRAM?.selection()).toBe('null');
});

test('the handle goes when its page does', async () => {
	const remove = installDiagramHandle(frame, fakeSession(null).session);
	expect(await window.SEGL_DIAGRAM?.xml()).toBe('<mxfile/>');
	expect(window.SEGL_DIAGRAM?.counts()).toBe('{"mismatches":1,"reloads":2}');

	remove();

	expect(window.SEGL_DIAGRAM).toBeUndefined();
});
