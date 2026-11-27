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
 * A whiteboard's view, as follow mode sends it (T18). The pinned editor puts
 * a scene point at `(x + scrollX) * zoom` from the canvas's left edge, and
 * the same for y, so its canvas of `width` by `height` shows the scene from
 * `-scrollX` across `width / zoom`. This file reads no part of the editor, so
 * Vitest can hold it.
 */
import type { View } from '../collab/protocol.ts';

/** The editor's own limits on the zoom. */
export const MIN_ZOOM = 0.1;
export const MAX_ZOOM = 30;

/** What of the editor's state places the scene on its canvas. */
export interface Placement {
	scrollX: number;
	scrollY: number;
	zoom: number;
	/** The canvas's size, in screen pixels. */
	width: number;
	height: number;
}

/** Return the area of the scene a canvas shows. */
export function visibleArea({ scrollX, scrollY, zoom, width, height }: Placement): View {
	return { x: -scrollX, y: -scrollY, width: width / zoom, height: height / zoom };
}

/**
 * Return the scroll and zoom that show all of `view` on a canvas of `width`
 * by `height`, centred: the follower's canvas fits the leader's area, however
 * the two screens differ in size.
 */
export function fitArea(
	view: View,
	width: number,
	height: number
): Pick<Placement, 'scrollX' | 'scrollY' | 'zoom'> {
	const fit = Math.min(width / view.width, height / view.height);
	const zoom = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, fit));
	return {
		scrollX: width / (2 * zoom) - (view.x + view.width / 2),
		scrollY: height / (2 * zoom) - (view.y + view.height / 2),
		zoom
	};
}
