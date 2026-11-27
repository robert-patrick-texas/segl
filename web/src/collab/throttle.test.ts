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
import { Throttle } from './throttle.ts';

let sent: string[];
let throttle: Throttle<string>;

beforeEach(() => {
	vi.useFakeTimers();
	sent = [];
	throttle = new Throttle(100, (value) => sent.push(value));
});

afterEach(() => {
	vi.useRealTimers();
});

test('the first goes at once, and only the newest of the rest when the time is up', () => {
	throttle.push('a');
	throttle.push('b');
	throttle.push('c');
	expect(sent).toEqual(['a']);

	vi.advanceTimersByTime(99);
	expect(sent).toEqual(['a']);
	vi.advanceTimersByTime(1);
	expect(sent).toEqual(['a', 'c']);

	// Nothing waits now: the next goes when the time since the last is up.
	vi.advanceTimersByTime(100);
	throttle.push('d');
	expect(sent).toEqual(['a', 'c', 'd']);
});

test('a cancel forgets what waits, and the next goes at once', () => {
	throttle.push('a');
	throttle.push('b');
	throttle.cancel();
	vi.advanceTimersByTime(500);
	expect(sent).toEqual(['a']);

	throttle.push('c');
	expect(sent).toEqual(['a', 'c']);
});
