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

/** Which network object a selection is, for segl's panel (D2-038). */
import { isDeviceKind, type ObjectType, type State } from './kinds.ts';
import { isObjectRecord, readRecord, type ObjectRecord } from './record.ts';
import type { Placed } from './copies.ts';
import { untagged } from './tags.ts';

/** The part of an element the panel reads. */
export interface SceneItem extends Placed {
	/** A label's shape or line. */
	containerId?: string | null;
	/** A label's words as the person wrote them: `text` is wrapped to fit. */
	originalText?: string;
}

/** One network object, as the panel shows it. */
export interface NetworkObject {
	objectId: string;
	objectType: ObjectType;
	kind: 'device' | 'link';
	state: State;
	/** A device's label, or a link's label without its tag. */
	name: string;
	/** The element that carries the record: the device's card, or the link's line. */
	elementId: string;
}

interface Holder {
	element: SceneItem;
	record: ObjectRecord;
}

/**
 * The network object the selection is, or null. Every selected element must
 * belong to that one object: its card or line, its label, a line of its
 * glyph, or its tag. Anything else selected with it, or a second object,
 * gives null, and the panel does not show.
 */
export function selectedObject(
	elements: readonly SceneItem[],
	selected: ReadonlySet<string>
): NetworkObject | null {
	if (selected.size === 0) return null;
	const live = elements.filter((element) => !element.isDeleted);
	const holders = new Map<string, Holder>();
	const byGroup = new Map<string, string>();
	const owners = new Map<string, number>();
	for (const element of live) {
		const record = readRecord(element);
		if (!isObjectRecord(record)) continue;
		holders.set(element.id, { element, record });
		owners.set(record.objectId, (owners.get(record.objectId) ?? 0) + 1);
		const group = element.groupIds[0];
		if (group !== undefined && isDeviceKind(record.objectType)) byGroup.set(group, record.objectId);
	}

	// The object each selected element belongs to.
	const objectOf = (element: SceneItem): string | null => {
		const record = readRecord(element);
		if (record !== null) return record.objectId;
		if (element.containerId) return holders.get(element.containerId)?.record.objectId ?? null;
		const group = element.groupIds[0];
		return group === undefined ? null : (byGroup.get(group) ?? null);
	};
	let objectId: string | null = null;
	for (const element of live) {
		if (!selected.has(element.id)) continue;
		const owner = objectOf(element);
		if (owner === null || (objectId !== null && owner !== objectId)) return null;
		objectId = owner;
	}
	// Two elements that claim one id are no one object the panel can change.
	if (objectId === null || owners.get(objectId) !== 1) return null;

	const holder = [...holders.values()].find(({ record }) => record.objectId === objectId)!;
	const { element, record } = holder;
	const label = live.find(
		(each) => each.containerId === element.id && typeof each.originalText === 'string'
	);
	const text = label?.originalText ?? '';
	const device = isDeviceKind(record.objectType);
	return {
		objectId,
		objectType: record.objectType,
		kind: device ? 'device' : 'link',
		state: record.state,
		name: device ? text : untagged(text, record.state),
		elementId: element.id
	};
}
