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
 * What every slot states: who can see it, and who can change it (S-016).
 * A browser that may look and not edit is also told that editing is locked,
 * and whether that is for want of an access code or because its pass has
 * ended.
 */

/**
 * Where this browser stands with the edit gate.
 *
 * - `open`: the slot asks for no access code. Everyone edits.
 * - `unlocked`: it asks for one, and the server took this browser's pass.
 * - `locked`: it asks for one, and this browser has no pass.
 * - `refused`: this browser has a pass, and the server did not take it. The
 *   pass has ended, or the site ended it.
 * - `waiting`: this browser has a pass, and the server has not answered yet.
 */
export type Editing = 'open' | 'unlocked' | 'locked' | 'refused' | 'waiting';

export interface GateFacts {
	/** The page was told that this segl asks for an access code. */
	editRequired: boolean;
	/** What the server said, in `welcome` or since, or null until it has. */
	viewOnly: boolean | null;
	/** This browser has a pass to send. */
	hasPass: boolean;
}

/**
 * The server's own answer comes first: the page's `editRequired` is from when
 * it loaded, and the site may have set codes, or taken them away, since.
 */
export function editingState({ editRequired, viewOnly, hasPass }: GateFacts): Editing {
	if (viewOnly === true) return hasPass ? 'refused' : 'locked';
	if (viewOnly === false) return editRequired && hasPass ? 'unlocked' : 'open';
	if (!editRequired) return 'open';
	return hasPass ? 'waiting' : 'locked';
}

const SEEN = 'Shared workspace. Anyone who can open this page can see it';

const EDITING: Record<Exclude<Editing, 'open'>, string> = {
	unlocked: 'This browser entered an access code and can edit.',
	locked: 'Editing is locked: it needs an access code.',
	refused: 'Editing is locked: the access this browser had has ended.',
	waiting: 'Editing needs an access code.'
};

/** The notice in two parts: that the slot is shared, and what editing takes here. */
export function sharedNotice(editing: Editing): { shared: string; editing: string } {
	if (editing === 'open') return { shared: `${SEEN} and edit it.`, editing: '' };
	return { shared: `${SEEN}.`, editing: EDITING[editing] };
}

/** What the link to the access page says. */
export const ENTER_CODE = 'Enter access code';

/**
 * Whether the bar offers the way to the access page: to a browser that the
 * server keeps from editing, for want of a pass or because its pass ended.
 * Not while the server has yet to answer for a pass this browser has.
 */
export function offersAccess(editing: Editing): boolean {
	return editing === 'locked' || editing === 'refused';
}
