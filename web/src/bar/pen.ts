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

/** The words of the pen in Diagram mode's bar. */

/** Return what the bar says of the pen. `holder` is a display name, or null when it is free. */
export function penLabel(holder: string | null, mine: boolean): string {
	if (mine) return 'You have the pen';
	if (holder === null) return 'Pen free';
	return `Pen: ${holder}`;
}

/** Return the display name of whoever holds the pen, or null when it is free. */
export function penHolder(
	pen: string | null,
	participants: readonly { connectionId: string; displayName: string | null }[]
): string | null {
	if (pen === null) return null;
	return participants.find((person) => person.connectionId === pen)?.displayName ?? 'someone';
}
