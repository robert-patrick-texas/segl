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
import {
	historyRows,
	NEEDS_TOKEN,
	parseRevisions,
	restoreProblem,
	whenLabel,
	type RevisionInfo
} from './history.ts';

function revision(number: number, epoch = 1, authorLabel = 'Guest1'): RevisionInfo {
	return { revision: number, epoch, authorLabel, createdAt: '2026-11-12T09:00:00.000Z' };
}

test('a list of revisions is read as its four fields', () => {
	const listed = [
		{ revision: 2, epoch: 1, authorLabel: 'Staff2', createdAt: '2026-11-12T09:00:01.000Z' },
		{ revision: 1, epoch: 1, authorLabel: 'Guest1', createdAt: '2026-11-12T09:00:00.000Z' }
	];

	expect(parseRevisions(listed)).toEqual(listed);
	expect(parseRevisions([])).toEqual([]);
});

test('what a later segl adds to a revision is left out', () => {
	const parsed = parseRevisions([{ ...revision(3), scene: { elements: [] }, kind: 'restore' }]);

	expect(parsed).toEqual([revision(3)]);
});

test.each([
	['no list', undefined],
	['null', null],
	['an object', { revisions: [] }],
	['text', 'none'],
	['a row that is not an object', [revision(2), 7]],
	['a null row', [null]],
	['a revision that is text', [{ ...revision(1), revision: '1' }]],
	['a revision of zero', [{ ...revision(1), revision: 0 }]],
	['a revision with a fraction', [{ ...revision(1), revision: 1.5 }]],
	['an epoch that is text', [{ ...revision(1), epoch: '1' }]],
	['a label that is null', [{ ...revision(1), authorLabel: null }]],
	['a time that is a number', [{ ...revision(1), createdAt: 1762938000000 }]],
	['a row without its time', [{ revision: 1, epoch: 1, authorLabel: 'Guest1' }]]
])('%s is not a history', (_name, value) => {
	expect(parseRevisions(value)).toBeNull();
});

test('the rows are in the order given, and plain drawing marks none', () => {
	const rows = historyRows([revision(3), revision(2), revision(1)]);

	expect(rows.map((row) => row.revision)).toEqual([3, 2, 1]);
	expect(rows.map((row) => row.replacement)).toEqual([false, false, false]);
	expect(rows[0]).toEqual({ ...revision(3), replacement: false });
});

test('the first row of a new epoch is a replacement: a restore or an import', () => {
	// Drawn, drawn, restored, drawn on, an import, restored again.
	const rows = historyRows([
		revision(6, 4),
		revision(5, 3),
		revision(4, 2),
		revision(3, 2),
		revision(2, 1),
		revision(1, 1)
	]);

	expect(rows.map((row) => [row.revision, row.replacement])).toEqual([
		[6, true],
		[5, true],
		[4, false],
		[3, true],
		[2, false],
		[1, false]
	]);
});

test('the oldest row is never marked: what came before it is not kept', () => {
	expect(historyRows([revision(51, 2)]).map((row) => row.replacement)).toEqual([false]);
	expect(historyRows([revision(52, 2), revision(51, 2)]).map((row) => row.replacement)).toEqual([
		false,
		false
	]);
	expect(historyRows([])).toEqual([]);
});

const LONDON = { locale: 'en-GB', timeZone: 'UTC' };
const NOON = new Date('2026-11-12T12:00:00.000Z');

test('a revision of today is shown by its time, to the second', () => {
	expect(whenLabel('2026-11-12T09:05:07.123Z', NOON, LONDON)).toBe('09:05:07');
	expect(whenLabel('2026-11-12T00:00:00.000Z', NOON, LONDON)).toBe('00:00:00');
	expect(whenLabel('2026-11-12T23:59:59.999Z', NOON, LONDON)).toBe('23:59:59');
});

test('an older revision is shown with its date', () => {
	expect(whenLabel('2026-11-11T23:59:59.000Z', NOON, LONDON)).toBe('11 Nov 2026, 23:59:59');
	expect(whenLabel('2025-11-12T09:05:07.000Z', NOON, LONDON)).toBe('12 Nov 2025, 09:05:07');
});

test('today is the day of the clock the person reads', () => {
	// Half past midnight in Tokyo is still the day before in UTC.
	const stamp = '2026-11-12T15:30:00.000Z';
	const now = new Date('2026-11-12T16:00:00.000Z');

	expect(whenLabel(stamp, now, { locale: 'en-GB', timeZone: 'Asia/Tokyo' })).toBe('00:30:00');
	expect(whenLabel(stamp, now, LONDON)).toBe('15:30:00');
	// Late on the 12th in UTC is already the 13th in Tokyo, and not today there.
	const late = new Date('2026-11-12T14:00:00.000Z');
	expect(whenLabel(stamp, late, { locale: 'en-GB', timeZone: 'Asia/Tokyo' })).toBe(
		'13 Nov 2026, 00:30:00'
	);
});

test('the words follow the language asked for', () => {
	const american = whenLabel('2026-11-12T14:05:07.000Z', NOON, {
		locale: 'en-US',
		timeZone: 'UTC'
	});
	// The space before PM is a narrow one in some versions of the language data.
	expect(american.replace(/\s/gu, ' ')).toBe('2:05:07 PM');
	expect(whenLabel('2026-11-11T14:05:07.000Z', NOON, { locale: 'de-DE', timeZone: 'UTC' })).toBe(
		'11.11.2026, 14:05:07'
	);
});

test('a time this browser cannot read is shown as the server wrote it', () => {
	expect(whenLabel('yesterday', NOON, LONDON)).toBe('yesterday');
	expect(whenLabel('', NOON, LONDON)).toBe('');
});

test("without options the browser's own language and clock are used", () => {
	const stamp = '2026-11-12T09:05:07.000Z';

	expect(whenLabel(stamp, new Date(stamp))).toBe(
		new Intl.DateTimeFormat(undefined, { timeStyle: 'medium' }).format(new Date(stamp))
	);
});

class Refused extends Error {
	readonly code: string;

	constructor(code: string, message: string) {
		super(message);
		this.code = code;
	}
}

test('a refused restore is put in words by its code', () => {
	expect(restoreProblem(new Refused('view_only', 'Editing needs the edit token.'))).toBe(
		NEEDS_TOKEN
	);
	expect(restoreProblem(new Refused('revision_not_found', 'The slot has no such revision.'))).toBe(
		'That version is no longer kept.'
	);
});

test('any other failure is told in its own words', () => {
	expect(
		restoreProblem(new Refused('internal_error', 'segl could not complete the request.'))
	).toBe('segl could not complete the request.');
	expect(restoreProblem(new TypeError('Failed to fetch'))).toBe('Failed to fetch');
});

test('a failure with no words gets some', () => {
	expect(restoreProblem(new Error(''))).toBe('segl could not restore that version.');
	expect(restoreProblem('no')).toBe('segl could not restore that version.');
	expect(restoreProblem(null)).toBe('segl could not restore that version.');
	expect(restoreProblem({ code: 7 })).toBe('segl could not restore that version.');
});
