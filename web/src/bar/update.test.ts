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
import { isUpdated, RELOAD, UPDATED } from './update.ts';

test('the notice shows only when the server names another version', () => {
	expect(isUpdated('0.9.0', '0.8.0')).toBe(true);
	expect(isUpdated('0.8.0', '0.8.0')).toBe(false);
	expect(isUpdated(null, '0.8.0')).toBe(false);
});

test('the notice and its button say it in two words each', () => {
	expect(UPDATED).toBe('segl updated');
	expect(RELOAD).toBe('Reload');
});
