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
import { editingState, sharedNotice, type Editing } from './notice.ts';

test('every slot says it is shared and open (S-016)', () => {
	expect(sharedNotice('open')).toEqual({
		shared: 'Shared workspace. Anyone who can open this page can see it and edit it.',
		editing: ''
	});
});

test.each<[Editing, string]>([
	['locked', 'Editing is locked: it needs the edit token.'],
	['refused', 'Editing is locked: this segl did not take the edit token this browser has.'],
	['unlocked', 'This browser has the edit token and can edit.'],
	['waiting', 'Editing needs the edit token.']
])(
	'with an edit token, the %s state is said in words, and nobody is promised editing',
	(editing, words) => {
		const notice = sharedNotice(editing);

		expect(notice.shared).toBe('Shared workspace. Anyone who can open this page can see it.');
		expect(notice.shared).not.toContain('edit it');
		expect(notice.editing).toBe(words);
	}
);

test('a view-only browser is told that editing is locked (S-016)', () => {
	expect(sharedNotice('locked').editing).toContain('Editing is locked');
	expect(sharedNotice('refused').editing).toContain('Editing is locked');
	// And only such a browser.
	expect(sharedNotice('unlocked').editing).not.toContain('locked');
	expect(sharedNotice('waiting').editing).not.toContain('locked');
});

test.each<[boolean, boolean | null, boolean, Editing]>([
	// editRequired, viewOnly, hasToken
	// No token is configured: everyone edits, whatever this browser holds.
	[false, null, false, 'open'],
	[false, null, true, 'open'],
	[false, false, false, 'open'],
	[false, false, true, 'open'],
	// One is configured, and the server has not answered yet.
	[true, null, false, 'locked'],
	[true, null, true, 'waiting'],
	// The server has answered.
	[true, false, true, 'unlocked'],
	[true, true, false, 'locked'],
	[true, true, true, 'refused'],
	// The server's answer beats what the page was told when it loaded: a
	// token set since, and a token taken away since.
	[false, true, false, 'locked'],
	[false, true, true, 'refused'],
	[true, false, false, 'open']
])('editRequired %j, viewOnly %j, a token %j: %s', (editRequired, viewOnly, hasToken, expected) => {
	expect(editingState({ editRequired, viewOnly, hasToken })).toBe(expected);
});
