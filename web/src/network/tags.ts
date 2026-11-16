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
 * The tag that shows a state (N-004; D2-038): none for Existing, `P` for
 * Planned, `R` for To remove. A device's tag is a text of its own in the
 * device's group. A link's tag starts the link's label, before the team's
 * own words: `P 10G`.
 */
import { TAG_LETTERS, type State } from './kinds.ts';

/** The tag a state shows, or `''` for none. */
export function tagOf(state: State): string {
	return TAG_LETTERS[state];
}

/**
 * The label without the tag that the state `from` put at its start. Only
 * that letter and its space go: a label the person changed by hand, so that
 * it no longer starts with the tag, is left as they wrote it.
 */
export function untagged(label: string, from: State): string {
	const tag = tagOf(from);
	if (tag === '') return label;
	if (label === tag) return '';
	return label.startsWith(`${tag} `) ? label.slice(tag.length + 1) : label;
}

/** A link's label once its state goes from `from` to `to`: `10G`, `P 10G`, `R 10G`, `10G`. */
export function retag(label: string, from: State, to: State): string {
	const words = untagged(label, from);
	const tag = tagOf(to);
	if (tag === '') return words;
	return words === '' ? tag : `${tag} ${words}`;
}
