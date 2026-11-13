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
import { editingState, ENTER_CODE, offersAccess, sharedNotice, type Editing } from './notice.ts';

test('every slot says it is shared and open (S-016)', () => {
	expect(sharedNotice('open')).toEqual({
		shared: 'Shared workspace. Anyone who can open this page can see it and edit it.',
		editing: ''
	});
});

test.each<[Editing, string]>([
	['locked', 'Editing is locked: it needs an access code.'],
	['refused', 'Editing locked: access expired'],
	['unlocked', 'This browser entered an access code and can edit.'],
	['waiting', 'Editing needs an access code.']
])(
	'with access codes, the %s state is said in words, and nobody is promised editing',
	(editing, words) => {
		const notice = sharedNotice(editing);

		expect(notice.shared).toBe('Shared workspace. Anyone who can open this page can see it.');
		expect(notice.shared).not.toContain('edit it');
		expect(notice.editing).toBe(words);
	}
);

test('a view-only browser is told that editing is locked (S-016)', () => {
	expect(sharedNotice('locked').editing).toContain('Editing is locked');
	expect(sharedNotice('refused').editing).toContain('Editing locked');
	// And only such a browser.
	expect(sharedNotice('unlocked').editing).not.toContain('locked');
	expect(sharedNotice('waiting').editing).not.toContain('locked');
});

test.each<[boolean, boolean | null, boolean, Editing]>([
	// editRequired, viewOnly, hasPass
	// No access code is asked for: everyone edits, whatever this browser holds.
	[false, null, false, 'open'],
	[false, null, true, 'open'],
	[false, false, false, 'open'],
	[false, false, true, 'open'],
	// One is asked for, and the server has not answered yet.
	[true, null, false, 'locked'],
	[true, null, true, 'waiting'],
	// The server has answered.
	[true, false, true, 'unlocked'],
	[true, true, false, 'locked'],
	[true, true, true, 'refused'],
	// The server's answer beats what the page was told when it loaded: codes
	// set since, and codes taken away since.
	[false, true, false, 'locked'],
	[false, true, true, 'refused'],
	[true, false, false, 'open']
])('editRequired %j, viewOnly %j, a pass %j: %s', (editRequired, viewOnly, hasPass, expected) => {
	expect(editingState({ editRequired, viewOnly, hasPass })).toBe(expected);
});

test('a pass that ended while the page was open is the refused state', () => {
	// The server answers the next edit with `view_only`, and the session
	// turns view-only: this browser still has the pass it had.
	expect(editingState({ editRequired: true, viewOnly: true, hasPass: true })).toBe('refused');
	expect(sharedNotice('refused').editing).toBe('Editing locked: access expired');
});

test.each<[Editing, boolean]>([
	['locked', true],
	['refused', true],
	// An editor needs no way in, and neither does a browser on an open segl.
	['unlocked', false],
	['open', false],
	// The server has not yet said no to the pass this browser has.
	['waiting', false]
])('in the %s state, the way to the access page is offered: %j', (editing, offered) => {
	expect(offersAccess(editing)).toBe(offered);
});

test('the way to the access page is named for what it does, and is not a login', () => {
	expect(ENTER_CODE).toBe('Enter access code');
	for (const editing of ['locked', 'refused', 'unlocked', 'waiting'] as const) {
		expect(sharedNotice(editing).editing.toLowerCase()).not.toMatch(/log ?in|sign ?in|password/);
	}
});
