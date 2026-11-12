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
import { loadedScene, type Load } from './load.ts';

const scene = { epoch: 1 };

test('a scene loaded for this slot is the one to mount', () => {
	expect(loadedScene({ state: 'ready', slot: 3, scene }, 3)).toBe(scene);
});

test("another slot's scene is not this slot's", () => {
	// The one render between two slots: the new number, the old scene.
	expect(loadedScene({ state: 'ready', slot: 3, scene }, 4)).toBeNull();
});

test.each<Load<typeof scene>>([{ state: 'loading' }, { state: 'failed', message: 'no' }])(
	'there is none while %j',
	(load) => {
		expect(loadedScene(load, 3)).toBeNull();
	}
);
