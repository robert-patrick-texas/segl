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

/**
 * A slot's history as the bar lists it (S-005, docs/API.md): the revisions
 * the server keeps, newest first, and the words for when each was made, for
 * why one was kept, and for a restore that was refused. No React and no
 * editor here.
 */
import { DIAGRAM_SLOT } from './slots.ts';

/**
 * Why the server kept a revision: its scene is the one from just before a
 * big delete, a restore, or an import (docs/DATA-MODEL.md).
 */
export type Kept = 'delete' | 'restore' | 'import';

/** What the list says beside a kept revision. */
export const KEPT_PHRASES: Readonly<Record<Kept, string>> = {
	delete: 'Before delete',
	restore: 'Before restore',
	import: 'Before import'
};

/** One revision, without its scene, as `GET api/v1/slots/{n}/revisions` lists it. */
export interface RevisionInfo {
	/** Counts up per slot from 1, and is not reused. */
	revision: number;
	/** The epoch the scene belongs to. A restore or an import starts a new one. */
	epoch: number;
	/** The display name behind the newest change in it, or `System`. */
	authorLabel: string;
	/** When it was made, in UTC, as the server wrote it. */
	createdAt: string;
	/** Why the server kept it, or null for a revision kept as people drew. */
	kept: Kept | null;
}

/** A revision as a row of the list. */
export interface HistoryRow extends RevisionInfo {
	/**
	 * The scene was put in place whole here, by a restore or an import, and
	 * not drawn. The row below it is then the scene that was replaced. The
	 * server keeps no record of which of the two it was (D2-030).
	 */
	replacement: boolean;
}

function isRevisionInfo(value: unknown): value is RevisionInfo {
	if (typeof value !== 'object' || value === null) return false;
	const row = value as Record<string, unknown>;
	return (
		Number.isInteger(row['revision']) &&
		(row['revision'] as number) >= 1 &&
		Number.isInteger(row['epoch']) &&
		typeof row['authorLabel'] === 'string' &&
		typeof row['createdAt'] === 'string'
	);
}

function isKept(value: unknown): value is Kept {
	return typeof value === 'string' && Object.hasOwn(KEPT_PHRASES, value);
}

/**
 * Return the revisions of a response, or null when it is not such a list.
 * Each is kept as its five fields, whatever else a later segl sends. A
 * reason this page does not know, or none, as from an older segl, is none.
 */
export function parseRevisions(value: unknown): RevisionInfo[] | null {
	if (!Array.isArray(value) || !value.every(isRevisionInfo)) return null;
	return value.map(({ revision, epoch, authorLabel, createdAt, ...rest }) => {
		const kept = (rest as { kept?: unknown }).kept;
		return { revision, epoch, authorLabel, createdAt, kept: isKept(kept) ? kept : null };
	});
}

/**
 * Return the rows of the list, in the order given: newest first.
 *
 * A restore and an import each write the first revision of a new epoch, so a
 * row whose epoch is higher than that of the row below it is one of the two.
 * The oldest row has none below it, and is not marked: what came before it
 * is no longer kept.
 */
export function historyRows(revisions: readonly RevisionInfo[]): HistoryRow[] {
	return revisions.map((row, index) => {
		const older = revisions[index + 1];
		return { ...row, replacement: older !== undefined && row.epoch > older.epoch };
	});
}

export interface WhenOptions {
	/** The language of the words. The browser's own when left out. */
	locale?: string;
	/** The time zone of the clock. The browser's own when left out. */
	timeZone?: string;
}

/**
 * Return when a revision was made, as a person reads it: the time to the
 * second for one made today, and the date with it for an older one. Rows can
 * be a second apart, so the seconds are shown.
 */
export function whenLabel(createdAt: string, now: Date, options: WhenOptions = {}): string {
	const when = new Date(createdAt);
	// Not a time this browser can read: shown as the server wrote it.
	if (Number.isNaN(when.getTime())) return createdAt;
	const { locale, timeZone } = options;
	const day = new Intl.DateTimeFormat(locale, {
		timeZone,
		year: 'numeric',
		month: 'numeric',
		day: 'numeric'
	});
	const today = day.format(when) === day.format(now);
	return new Intl.DateTimeFormat(
		locale,
		today
			? { timeZone, timeStyle: 'medium' }
			: { timeZone, dateStyle: 'medium', timeStyle: 'medium' }
	).format(when);
}

/** What the list says where a viewer would find the restore buttons. */
export const NEEDS_CODE = 'Restoring needs an access code.';

/** What the list says while this browser is not in the slot's room. */
export const NEEDS_CONNECTION = 'Restoring waits for the connection.';

/** What the list says on slot 9 while another connection holds the pen (T19). */
export const NEEDS_PEN = 'Restoring needs the pen.';

export interface RestoreFacts {
	/** This browser may edit. */
	canRestore: boolean;
	/** Another connection holds slot 9's pen: only the holder restores. */
	penHeld: boolean;
	/** This browser is in the slot's room, and would see a restore. */
	connected: boolean;
}

/** Return the question a restore asks before it replaces the slot for everyone: on slot 9, its diagram. */
export function restoreQuestion(diagram: boolean): string {
	return diagram ? 'Replace the diagram for everyone?' : 'Replace the canvas for everyone?';
}

/** Return why the list's Restore buttons are gone or wait, or null when they work. */
export function restoreNote({ canRestore, penHeld, connected }: RestoreFacts): string | null {
	if (!canRestore) return NEEDS_CODE;
	if (penHeld) return NEEDS_PEN;
	if (!connected) return NEEDS_CONNECTION;
	return null;
}

/** The body of `POST api/v1/slots/{n}/restore`. */
export interface RestoreBody {
	revision: number;
	displayName: string | null;
	/** On slot 9, this page's connection, so the server knows whether it holds the pen. */
	connectionId?: string;
}

/** Return what a restore sends. Only slot 9 names the connection: its pen decides who restores. */
export function restoreBody(
	slot: number,
	revision: number,
	displayName: string | null,
	connectionId: string | null
): RestoreBody {
	const body: RestoreBody = { revision, displayName };
	if (slot === DIAGRAM_SLOT && connectionId !== null) body.connectionId = connectionId;
	return body;
}

/**
 * Return what to tell a person whose restore failed. `error` is what the
 * call threw: an `ApiError` carries the server's code.
 */
export function restoreProblem(error: unknown): string {
	const code =
		typeof error === 'object' && error !== null && 'code' in error
			? (error as { code: unknown }).code
			: null;
	if (code === 'view_only') return NEEDS_CODE;
	// Someone else took slot 9's pen since the list was read.
	if (code === 'pen_held') return NEEDS_PEN;
	// The rules the server keeps revisions by dropped it since the list was read.
	if (code === 'revision_not_found') return 'That version is no longer kept.';
	if (error instanceof Error && error.message !== '') return error.message;
	return 'segl could not restore that version.';
}
