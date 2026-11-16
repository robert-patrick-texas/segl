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
 * A placed copy is a new object (N-003; D2-038).
 *
 * The editor keeps `customData` on every copy it makes: from the library, a
 * paste, its duplicate, and Alt-drag. So a copy carries its source's object
 * id. The editor hands each of those to the page before they reach the
 * canvas (`onDuplicate`), and this decides which copies get a new id. An
 * element from the socket is never handed over, so it keeps its id.
 */
import {
	isObjectRecord,
	isTagRecord,
	newObjectId,
	readRecord,
	UNPLACED,
	type Carrier
} from './record.ts';

/** The part of an element the copy rule reads. */
export interface Placed extends Carrier {
	id: string;
	isDeleted: boolean;
	groupIds: readonly string[];
}

/**
 * The new object id of each element in `next` that is a copy, by element id.
 *
 * `prev` is the scene before the copy, and the elements of `next` that are
 * not in it are the copies. A copy gets a new id when it came from the
 * library, or when an element still on the canvas holds its id. A cut and a
 * paste keeps the id: the first copy is gone. A device's tag takes the new id
 * of the device it was copied with.
 */
export function copyIds(
	next: readonly Placed[],
	prev: readonly Placed[],
	makeId: () => string = newObjectId
): Map<string, string> {
	const before = new Set(prev.map((element) => element.id));
	const held = new Set<string>();
	for (const element of prev) {
		const record = element.isDeleted ? null : readRecord(element);
		if (record !== null) held.add(record.objectId);
	}
	const isCopy = (objectId: string) => objectId === UNPLACED || held.has(objectId);

	const objects = new Map<string, Placed[]>();
	const tags = new Map<string, Placed[]>();
	for (const element of next) {
		if (before.has(element.id) || element.isDeleted) continue;
		const record = readRecord(element);
		if (record === null || !isCopy(record.objectId)) continue;
		const into = isObjectRecord(record) ? objects : isTagRecord(record) ? tags : null;
		into?.set(record.objectId, [...(into.get(record.objectId) ?? []), element]);
	}

	const ids = new Map<string, string>();
	for (const [objectId, copies] of objects) {
		const ownTags = tags.get(objectId) ?? [];
		tags.delete(objectId);
		if (copies.length === 1) {
			// One copy of the object: its tags are its own, grouped or not.
			const id = makeId();
			for (const element of [...copies, ...ownTags]) ids.set(element.id, id);
			continue;
		}
		// Several copies of one object at once: each tag goes with the copy in its group.
		for (const copy of copies) {
			const id = makeId();
			ids.set(copy.id, id);
			const group = copy.groupIds[0];
			for (const tag of ownTags) {
				if (group !== undefined && tag.groupIds[0] === group) ids.set(tag.id, id);
			}
		}
		for (const tag of ownTags) if (!ids.has(tag.id)) ids.set(tag.id, makeId());
	}
	// A tag copied without its device belongs to no device here.
	for (const copies of tags.values()) for (const tag of copies) ids.set(tag.id, makeId());
	return ids;
}
