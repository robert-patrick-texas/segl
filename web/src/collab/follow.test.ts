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
import { Leading, sameView, VIEW_INTERVAL_MS } from './follow.ts';
import type { View } from './protocol.ts';

const FIRST: View = { x: 0, y: 0, width: 800, height: 600 };
const SECOND: View = { x: 50, y: -20, width: 400, height: 300 };
const THIRD: View = { x: 60, y: -20, width: 400, height: 300 };

let sent: View[];
let leading: Leading;

beforeEach(() => {
	vi.useFakeTimers();
	sent = [];
	leading = new Leading((view) => sent.push(view));
});

afterEach(() => {
	vi.useRealTimers();
});

test('no view is sent while nobody follows', () => {
	leading.view(FIRST);
	leading.view(SECOND);
	vi.advanceTimersByTime(1000);
	expect(sent).toEqual([]);
});

test('a new follower is sent the view at once, and then each change, five a second', () => {
	leading.view(FIRST);
	leading.followers(1);
	expect(sent).toEqual([FIRST]);

	leading.view(SECOND);
	leading.view(THIRD);
	expect(sent).toEqual([FIRST]);
	vi.advanceTimersByTime(VIEW_INTERVAL_MS);
	expect(sent).toEqual([FIRST, THIRD]);
});

test('a second follower is sent the view too, and one fewer sends nothing', () => {
	leading.view(FIRST);
	leading.followers(1);
	vi.advanceTimersByTime(VIEW_INTERVAL_MS);
	leading.followers(2);
	leading.followers(1);
	vi.advanceTimersByTime(VIEW_INTERVAL_MS);
	expect(sent).toEqual([FIRST, FIRST]);
});

test('the same view is not sent again', () => {
	leading.followers(1);
	leading.view(FIRST);
	vi.advanceTimersByTime(VIEW_INTERVAL_MS);
	leading.view({ ...FIRST });
	vi.advanceTimersByTime(VIEW_INTERVAL_MS);
	expect(sent).toEqual([FIRST]);
});

test('with nobody left, what waits is dropped, and a reset starts with nobody', () => {
	leading.followers(1);
	leading.view(FIRST);
	leading.view(SECOND);
	leading.followers(0);
	vi.advanceTimersByTime(VIEW_INTERVAL_MS);
	expect(sent).toEqual([FIRST]);

	leading.followers(1);
	expect(sent).toEqual([FIRST, SECOND]);
	leading.reset();
	leading.view(THIRD);
	vi.advanceTimersByTime(VIEW_INTERVAL_MS);
	expect(sent).toEqual([FIRST, SECOND]);
});

test('a view is the same only on the same page', () => {
	expect(sameView({ ...FIRST, page: 'p1' }, { ...FIRST, page: 'p1' })).toBe(true);
	expect(sameView({ ...FIRST, page: 'p1' }, { ...FIRST, page: 'p2' })).toBe(false);
	expect(sameView(FIRST, { ...FIRST, page: null })).toBe(true);
	expect(sameView(FIRST, SECOND)).toBe(false);
});
