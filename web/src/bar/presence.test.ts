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
import { presenceLabel } from './presence.ts';
import { statusLabel } from './status.ts';

test('the count is named as connections', () => {
	expect(presenceLabel(1)).toBe('1 connection on this slot');
	expect(presenceLabel(2)).toBe('2 connections on this slot');
	expect(presenceLabel(10)).toBe('10 connections on this slot');
});

test('each state of the connection has its words', () => {
	expect(statusLabel('connecting')).toBe('Connecting…');
	expect(statusLabel('live')).toBe('Live');
	expect(statusLabel('disconnected')).toBe('Disconnected');
});
