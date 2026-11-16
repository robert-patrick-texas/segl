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
 * Network objects in the editor (D2-038): segl's library, a new object id for
 * each copy, and the state and the kind the panel sets. The symbols are plain
 * shapes in `web/src/network/`. This turns them into the editor's elements.
 *
 * Every change here goes through the editor as an edit of this browser's, so
 * the session sends it, the server keeps it, and undo takes it back. A record
 * rides in `customData`, which the editor, the socket, and the server carry
 * as they carry a color.
 */
import {
	CaptureUpdateAction,
	convertToExcalidrawElements,
	newElementWith
} from '@excalidraw/excalidraw';
import type { ExcalidrawElementSkeleton } from '@excalidraw/excalidraw/data/transform';
import type {
	ExcalidrawArrowElement,
	ExcalidrawElement,
	ExcalidrawLinearElement,
	ExcalidrawTextElement,
	FontFamilyValues
} from '@excalidraw/excalidraw/element/types';
import type { ExcalidrawImperativeAPI, LibraryItems } from '@excalidraw/excalidraw/types';
import { copyIds } from '../network/copies.ts';
import { isDeviceKind, KIND_NAMES, type LinkKind, type State } from '../network/kinds.ts';
import {
	isObjectRecord,
	isTagRecord,
	readRecord,
	SCHEMA_VERSION,
	UNPLACED,
	withRecord,
	type ObjectRecord
} from '../network/record.ts';
import {
	CARD,
	DEVICE_SYMBOLS,
	LINE_STYLES,
	LINK_LENGTH,
	LINK_SYMBOLS,
	tagPlace,
	TEXT_SIZE,
	type DeviceSymbol,
	type Path
} from '../network/symbols.ts';
import { retag, tagOf } from '../network/tags.ts';

/** A line's points, as the editor types them. */
type Points = ExcalidrawLinearElement['points'];

/** The editor's Nunito, which its style menu calls Normal. */
const FONT = 6 as FontFamilyValues;

/** The editor's Architect: straight lines, which read better in a diagram. Not a color. */
const ROUGHNESS = 0;

/** The editor's rounded corners for a shape, and its curve for a line. */
const ROUNDED_CARD = { type: 3 as const };
const CURVED_LINE = { type: 2 as const };

/** Library items are dated to segl's first network release, so the editor sorts them alike. */
const CREATED = Date.UTC(2026, 10, 16);

function unplaced(objectType: ObjectRecord['objectType']) {
	return withRecord(undefined, {
		schemaVersion: SCHEMA_VERSION,
		objectId: UNPLACED,
		objectType,
		state: 'existing'
	});
}

function pathSkeleton(path: Path, group: string): ExcalidrawElementSkeleton {
	const xs = path.points.map(([x]) => x);
	const ys = path.points.map(([, y]) => y);
	const left = Math.min(...xs);
	const top = Math.min(...ys);
	return {
		type: 'line',
		x: left,
		y: top,
		width: Math.max(...xs) - left,
		height: Math.max(...ys) - top,
		points: path.points.map(([x, y]) => [x - left, y - top]) as unknown as Points,
		roundness: path.curved ? CURVED_LINE : null,
		roughness: ROUGHNESS,
		groupIds: [group]
	};
}

/** A device's elements: its card with its name, then its glyph. */
function deviceElements(symbol: DeviceSymbol): ExcalidrawElement[] {
	const group = `segl-${symbol.kind}`;
	return convertToExcalidrawElements([
		{
			type: 'rectangle',
			x: 0,
			y: 0,
			width: CARD.width,
			height: CARD.height,
			roundness: ROUNDED_CARD,
			roughness: ROUGHNESS,
			groupIds: [group],
			customData: unplaced(symbol.kind),
			label: {
				text: KIND_NAMES[symbol.kind],
				fontSize: TEXT_SIZE,
				fontFamily: FONT,
				textAlign: 'center',
				verticalAlign: 'bottom',
				groupIds: [group]
			}
		},
		...symbol.glyph.map((path) => pathSkeleton(path, group))
	]);
}

function linkElements(kind: LinkKind): ExcalidrawElement[] {
	return convertToExcalidrawElements([
		{
			type: 'arrow',
			x: 0,
			y: 0,
			width: LINK_LENGTH,
			height: 0,
			points: [
				[0, 0],
				[LINK_LENGTH, 0]
			] as unknown as Points,
			roughness: ROUGHNESS,
			roundness: null,
			...LINE_STYLES[kind],
			customData: unplaced(kind)
		}
	]);
}

/** segl's network library: 12 devices, then 5 links. The editor merges it with the person's own. */
export function networkLibrary(): LibraryItems {
	return [
		...DEVICE_SYMBOLS.map((symbol) => ({
			id: `segl-${symbol.kind}`,
			status: 'unpublished' as const,
			created: CREATED,
			name: KIND_NAMES[symbol.kind],
			elements: deviceElements(symbol)
		})),
		...LINK_SYMBOLS.map((kind) => ({
			id: `segl-${kind}`,
			status: 'unpublished' as const,
			created: CREATED,
			name: KIND_NAMES[kind],
			elements: linkElements(kind)
		}))
	];
}

/**
 * The editor's `onDuplicate`: it calls this with each copy this browser
 * places, before the copy reaches the canvas. A copy gets a new object id in
 * the same step, so undo removes the copy and its id together.
 */
export function renewCopies(
	next: readonly ExcalidrawElement[],
	prev: readonly ExcalidrawElement[]
): ExcalidrawElement[] | void {
	const ids = copyIds(next, prev);
	if (ids.size === 0) return;
	return next.map((element) => {
		const objectId = ids.get(element.id);
		const record = readRecord(element);
		if (objectId === undefined || record === null) return element;
		return newElementWith(element, {
			customData: withRecord(element.customData, { ...record, objectId })
		});
	});
}

/** A text the editor has measured, in segl's font and size. */
function measured(text: string, like?: ExcalidrawTextElement): ExcalidrawTextElement {
	const [element] = convertToExcalidrawElements([
		{
			type: 'text',
			text,
			x: 0,
			y: 0,
			fontSize: like?.fontSize ?? TEXT_SIZE,
			fontFamily: like?.fontFamily ?? FONT
		}
	]);
	return element as ExcalidrawTextElement;
}

function isText(element: ExcalidrawElement): element is ExcalidrawTextElement {
	return element.type === 'text';
}

function isArrow(element: ExcalidrawElement): element is ExcalidrawArrowElement {
	return element.type === 'arrow';
}

/** Where the editor puts a line's label: on its middle point, or the middle of its middle segment. */
function middleOf(line: ExcalidrawLinearElement) {
	const { points } = line;
	const half = Math.floor(points.length / 2);
	const [ax, ay] = points[points.length % 2 === 1 ? half : half - 1] ?? [0, 0];
	const [bx, by] = points[half] ?? [0, 0];
	return { x: line.x + (ax + bx) / 2, y: line.y + (ay + by) / 2 };
}

/** The scene with these elements changed, and new ones placed before the element named. */
function changed(
	scene: readonly ExcalidrawElement[],
	updates: ReadonlyMap<string, ExcalidrawElement>,
	before: { id: string; added: readonly ExcalidrawElement[] } | null
): ExcalidrawElement[] {
	const next: ExcalidrawElement[] = [];
	for (const element of scene) {
		if (before !== null && element.id === before.id) next.push(...before.added);
		next.push(updates.get(element.id) ?? element);
	}
	return next;
}

/** The card or line that carries the object's record. The panel shows only an id one element claims. */
function holderOf(scene: readonly ExcalidrawElement[], objectId: string) {
	for (const element of scene) {
		const record = element.isDeleted ? null : readRecord(element);
		if (isObjectRecord(record) && record.objectId === objectId) return { element, record };
	}
	return null;
}

/**
 * Set an object's state (N-004). Only its record and its tag change: on a
 * device, the tag text in its group, placed under the card so a link's end
 * still finds the card; on a link, the first letter of its label.
 */
export function setObjectState(api: ExcalidrawImperativeAPI, objectId: string, state: State): void {
	const scene: readonly ExcalidrawElement[] = api.getSceneElementsIncludingDeleted();
	const holder = holderOf(scene, objectId);
	if (holder === null || holder.record.state === state) return;
	const { element, record } = holder;
	const updates = new Map<string, ExcalidrawElement>();
	updates.set(
		element.id,
		newElementWith(element, { customData: withRecord(element.customData, { ...record, state }) })
	);
	let added: ExcalidrawElement[] = [];
	const tag = tagOf(state);

	if (isDeviceKind(record.objectType)) {
		const tags = scene.filter(
			(each): each is ExcalidrawTextElement =>
				!each.isDeleted &&
				isText(each) &&
				isTagRecord(readRecord(each)) &&
				readRecord(each)!.objectId === objectId
		);
		const [kept, ...extra] = tags;
		for (const each of extra) updates.set(each.id, newElementWith(each, { isDeleted: true }));
		if (kept !== undefined && tag === '') {
			updates.set(kept.id, newElementWith(kept, { isDeleted: true }));
		} else if (kept !== undefined) {
			const size = measured(tag, kept);
			updates.set(
				kept.id,
				newElementWith(kept, {
					text: tag,
					originalText: tag,
					width: size.width,
					height: size.height
				})
			);
		} else if (tag !== '') {
			const size = measured(tag);
			const place = tagPlace(element, size);
			const [created] = convertToExcalidrawElements([
				{
					type: 'text',
					text: tag,
					...place,
					fontSize: TEXT_SIZE,
					fontFamily: FONT,
					strokeColor: element.strokeColor,
					opacity: element.opacity,
					groupIds: [...element.groupIds],
					customData: withRecord(undefined, {
						schemaVersion: SCHEMA_VERSION,
						objectId,
						part: 'tag'
					})
				}
			]);
			added = [created!];
		}
	} else if (isArrow(element)) {
		const label = scene.find(
			(each): each is ExcalidrawTextElement =>
				!each.isDeleted && isText(each) && each.containerId === element.id
		);
		const text = retag(label?.originalText ?? '', record.state, state);
		if (label !== undefined && text === '') {
			updates.set(label.id, newElementWith(label, { isDeleted: true }));
			updates.set(
				element.id,
				newElementWith(updates.get(element.id)!, {
					boundElements: (element.boundElements ?? []).filter((each) => each.id !== label.id)
				})
			);
		} else if (label !== undefined) {
			const size = measured(text, label);
			const middle = middleOf(element);
			updates.set(
				label.id,
				newElementWith(label, {
					text,
					originalText: text,
					width: size.width,
					height: size.height,
					x: middle.x - size.width / 2,
					y: middle.y - size.height / 2
				})
			);
		} else if (text !== '') {
			const middle = middleOf(element);
			// The editor centers a new text on x and y itself, from its alignment.
			const [created] = convertToExcalidrawElements([
				{
					type: 'text',
					text,
					x: middle.x,
					y: middle.y,
					fontSize: TEXT_SIZE,
					fontFamily: FONT,
					textAlign: 'center',
					verticalAlign: 'middle',
					strokeColor: element.strokeColor,
					containerId: element.id
				}
			]);
			updates.set(
				element.id,
				newElementWith(updates.get(element.id)!, {
					boundElements: [...(element.boundElements ?? []), { type: 'text', id: created!.id }]
				})
			);
			// A label is drawn after its line.
			const next = changed(scene, updates, null);
			const at = next.findIndex((each) => each.id === element.id);
			next.splice(at + 1, 0, created!);
			api.updateScene({ elements: next, captureUpdate: CaptureUpdateAction.IMMEDIATELY });
			return;
		}
	}
	api.updateScene({
		elements: changed(scene, updates, added.length > 0 ? { id: element.id, added } : null),
		captureUpdate: CaptureUpdateAction.IMMEDIATELY
	});
}

/** Set a link's kind (N-002): its line style, its width, and its ends, and nothing else. */
export function setLinkKind(api: ExcalidrawImperativeAPI, objectId: string, kind: LinkKind): void {
	const scene: readonly ExcalidrawElement[] = api.getSceneElementsIncludingDeleted();
	const holder = holderOf(scene, objectId);
	if (holder === null || holder.record.objectType === kind || !isArrow(holder.element)) return;
	const { element, record } = holder;
	const updates = new Map<string, ExcalidrawElement>([
		[
			element.id,
			newElementWith(element, {
				...LINE_STYLES[kind],
				customData: withRecord(element.customData, { ...record, objectType: kind })
			})
		]
	]);
	api.updateScene({
		elements: changed(scene, updates, null),
		captureUpdate: CaptureUpdateAction.IMMEDIATELY
	});
}
