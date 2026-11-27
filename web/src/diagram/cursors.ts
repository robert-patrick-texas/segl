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
 * The others' cursors in Diagram mode (T18). segl's `js/PostConfig.js` draws
 * them in drawio's frame, as the whiteboards' editor draws its own: an arrow
 * and the person's name, in the connection's color. The protocol carries no
 * color (D2-027), so every browser works it out from the connection id.
 */
import { UNNAMED } from '../bar/presence.ts';
import type { Peer } from '../collab/session.ts';

/** One cursor, as the frame draws it. */
export interface FrameCursor {
	/** The connection's id. */
	id: string;
	name: string;
	color: string;
	/** Where it is, in the diagram's coordinates, and on which page. */
	x: number;
	y: number;
	page: string | null;
}

/**
 * Return the color the pinned editor gives a connection's cursor on the
 * whiteboards: its `getClientColor`, from the connection id, which the
 * package does not export. `cursors.test.ts` holds this to the editor's own
 * code, read from its build.
 */
export function cursorColor(connectionId: string): string {
	let hash = 0;
	for (let index = 0; index < connectionId.length; index++) {
		hash = (hash << 5) - hash + connectionId.charCodeAt(index);
	}
	const hue = (Math.abs(hash) % 37) * 10;
	return `hsl(${hue}, 100%, 83%)`;
}

/** Return the cursors the frame draws: the others' that have one, with a name and a color. */
export function frameCursors(peers: Iterable<Peer>, self: string | null): FrameCursor[] {
	const shown: FrameCursor[] = [];
	for (const { connectionId, displayName, cursor } of peers) {
		if (connectionId === self || cursor === null) continue;
		shown.push({
			id: connectionId,
			name: displayName ?? UNNAMED,
			color: cursorColor(connectionId),
			x: cursor.x,
			y: cursor.y,
			page: cursor.page ?? null
		});
	}
	return shown;
}
