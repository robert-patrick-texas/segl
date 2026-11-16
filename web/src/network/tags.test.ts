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
import { STATE_NAMES, STATES, TAG_LETTERS } from './kinds.ts';
import { retag, tagOf, untagged } from './tags.ts';

describe('the tag of each state', () => {
	test.each([
		['existing', '', 'Existing'],
		['planned', 'P', 'Planned'],
		['remove', 'R', 'To remove']
	] as const)('%s shows "%s" and is called %s', (state, tag, name) => {
		expect(tagOf(state)).toBe(tag);
		expect(STATE_NAMES[state]).toBe(name);
	});

	test('a tag is a letter, never a color', () => {
		for (const state of STATES) expect(TAG_LETTERS[state]).toMatch(/^[A-Z]?$/);
	});
});

describe('the label rewrite', () => {
	test('10G, P 10G, R 10G, 10G', () => {
		let label = '10G';
		label = retag(label, 'existing', 'planned');
		expect(label).toBe('P 10G');
		label = retag(label, 'planned', 'remove');
		expect(label).toBe('R 10G');
		label = retag(label, 'remove', 'existing');
		expect(label).toBe('10G');
	});

	test.each([
		['', 'existing', 'planned', 'P'],
		['P', 'planned', 'remove', 'R'],
		['R', 'remove', 'existing', ''],
		['', 'existing', 'existing', ''],
		['P 10G', 'planned', 'planned', 'P 10G'],
		['10G to the core', 'existing', 'remove', 'R 10G to the core'],
		['R 10G\nsecond line', 'remove', 'planned', 'P 10G\nsecond line']
	] as const)('"%s" from %s to %s is "%s"', (label, from, to, expected) => {
		expect(retag(label, from, to)).toBe(expected);
	});

	test('a label changed by hand stays as the person wrote it', () => {
		// The person took the tag out: nothing of theirs goes.
		expect(retag('10G', 'planned', 'remove')).toBe('R 10G');
		expect(retag('10G', 'planned', 'existing')).toBe('10G');
		// Words that only start with the letter are theirs.
		expect(retag('Primary', 'planned', 'existing')).toBe('Primary');
		expect(retag('PR 4', 'planned', 'existing')).toBe('PR 4');
		// An existing link's label that starts with "P " is the team's own.
		expect(retag('P 2 uplink', 'existing', 'planned')).toBe('P P 2 uplink');
		// So is a space at its start: an existing link has no tag to take off.
		expect(retag(' 10G', 'existing', 'planned')).toBe('P  10G');
		expect(untagged(' 10G', 'existing')).toBe(' 10G');
	});

	test('untagged leaves the words', () => {
		expect(untagged('P 10G', 'planned')).toBe('10G');
		expect(untagged('P', 'planned')).toBe('');
		expect(untagged('P 10G', 'remove')).toBe('P 10G');
		expect(untagged('R 10G', 'existing')).toBe('R 10G');
	});
});
