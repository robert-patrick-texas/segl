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
import { sharedNotice } from './notice.ts';

test('every slot says it is shared and open (S-016)', () => {
	expect(sharedNotice(false)).toBe(
		'Shared workspace. Anyone who can open this page can see it and edit it.'
	);
});

test('with an edit token, the notice does not promise editing', () => {
	const notice = sharedNotice(true);

	expect(notice).toContain('Shared workspace.');
	expect(notice).toContain('Editing needs the edit token.');
	expect(notice).not.toContain('edit it');
});
