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
 * and whether that is for want of a token or because of the one it has.
 */

/**
 * Where this browser stands with the edit gate.
 *
 * - `open`: the slot needs no token. Everyone edits.
 * - `unlocked`: it needs one, and the server took this browser's.
 * - `locked`: it needs one, and this browser has none.
 * - `refused`: this browser has one, and the server did not take it.
 * - `waiting`: this browser has one, and the server has not answered yet.
 */
export type Editing = 'open' | 'unlocked' | 'locked' | 'refused' | 'waiting';

export interface GateFacts {
	/** The page was told that this segl has an edit token. */
	editRequired: boolean;
	/** What the server said in `welcome`, or null until it has. */
	viewOnly: boolean | null;
	/** This browser has a token to send. */
	hasToken: boolean;
}

/**
 * The server's own answer comes first: the page's `editRequired` is from when
 * it loaded, and a token may have been set or taken away since.
 */
export function editingState({ editRequired, viewOnly, hasToken }: GateFacts): Editing {
	if (viewOnly === true) return hasToken ? 'refused' : 'locked';
	if (viewOnly === false) return editRequired && hasToken ? 'unlocked' : 'open';
	if (!editRequired) return 'open';
	return hasToken ? 'waiting' : 'locked';
}

const SEEN = 'Shared workspace. Anyone who can open this page can see it';

const EDITING: Record<Exclude<Editing, 'open'>, string> = {
	unlocked: 'This browser has the edit token and can edit.',
	locked: 'Editing is locked: it needs the edit token.',
	refused: 'Editing is locked: this segl did not take the edit token this browser has.',
	waiting: 'Editing needs the edit token.'
};

/** The notice in two parts: that the slot is shared, and what editing takes here. */
export function sharedNotice(editing: Editing): { shared: string; editing: string } {
	if (editing === 'open') return { shared: `${SEEN} and edit it.`, editing: '' };
	return { shared: `${SEEN}.`, editing: EDITING[editing] };
}
