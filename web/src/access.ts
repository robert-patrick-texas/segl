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
 * The access page's own logic (docs/ARCHITECTURE.md, "Edit gate"; D2-033):
 * what the server's answer to a code means, the words for it, and where the
 * person goes afterwards. `AccessPage.tsx` is the page.
 *
 * It is not a login. It takes a code, knows no user, and keeps no account.
 */
import { parseSlot } from './slots.ts';

/** What came of entering a code. */
export type Outcome =
	/** The code was right, and this is the pass it bought. */
	| { kind: 'pass'; pass: string }
	/** Not one of this segl's codes. */
	| { kind: 'wrong' }
	/** Too many wrong codes came from this address. `seconds` is the wait, or null. */
	| { kind: 'wait'; seconds: number | null }
	/** This segl asks for no code: everyone can edit. */
	| { kind: 'open' }
	/** The server could not be asked, or answered something else. */
	| { kind: 'failed' };

/** The parts of an `ApiError` this module reads. */
interface Refusal {
	code: string;
	retryAfter: number | null;
}

function isRefusal(error: unknown): error is Refusal {
	return typeof error === 'object' && error !== null && 'code' in error && 'retryAfter' in error;
}

/** What a failed call to `POST api/v1/access` means (docs/API.md). */
export function refusalOutcome(error: unknown): Outcome {
	if (!isRefusal(error)) return { kind: 'failed' };
	if (error.code === 'wrong_code') return { kind: 'wrong' };
	if (error.code === 'rate_limited') return { kind: 'wait', seconds: error.retryAfter };
	if (error.code === 'no_access_codes') return { kind: 'open' };
	return { kind: 'failed' };
}

export const WRONG_CODE = "That is not one of this segl's access codes.";
export const NO_CODE_NEEDED = 'This segl asks for no access code. Everyone can edit.';
export const NOT_REACHED = 'segl could not be asked. Try again.';

/** How long to wait, in words: `1 minute`, `15 minutes`, `less than a minute`. */
export function waitWords(seconds: number | null): string {
	if (seconds === null) return 'later';
	if (seconds < 60) return 'in less than a minute';
	const minutes = Math.ceil(seconds / 60);
	return minutes === 1 ? 'in 1 minute' : `in ${minutes} minutes`;
}

/** What the page says for an outcome, or `''` for a pass: the page then leaves. */
export function outcomeWords(outcome: Outcome): string {
	switch (outcome.kind) {
		case 'pass':
			return '';
		case 'wrong':
			return WRONG_CODE;
		case 'wait':
			return `Too many wrong codes came from this address. Try again ${waitWords(outcome.seconds)}.`;
		case 'open':
			return NO_CODE_NEEDED;
		case 'failed':
			return NOT_REACHED;
	}
}

/** What a code needs before it is worth sending: something other than spaces. */
export function isTyped(code: string): boolean {
	return code.trim() !== '';
}

/** What the bar's link hands the access page: the slot the person was on. */
export interface CameFrom {
	slot: number;
}

/**
 * The slot to go back to: the one the person came from, which the router
 * carries in the history entry, or the last one this browser opened, or 1.
 * Whatever is in that state is checked: it comes from the browser's history.
 */
export function returnSlot(state: unknown, lastSlot: number | null): number {
	if (typeof state === 'object' && state !== null && 'slot' in state) {
		const slot = parseSlot(String((state as { slot: unknown }).slot));
		if (slot !== null) return slot;
	}
	return lastSlot ?? 1;
}
