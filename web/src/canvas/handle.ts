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
 * A read-only handle on the mounted editor, at `window.SEGL_CANVAS`.
 *
 * The canvas is pixels, so the browser tests read the scene through this:
 * `document()` is the scene document as the editor serializes it for storage.
 * It is also how the bootstrap fixture, `src/segl/empty_scene.json`, was
 * captured (docs/DEVELOPMENT.md). `reconcile()` is the editor's own rule for
 * which copy of an element is kept. `images()` says which images have their
 * files. The handle exposes nothing the page's own user cannot already see,
 * and changes nothing.
 */
import { serializeAsJSON } from '@excalidraw/excalidraw';
import type { ExcalidrawImperativeAPI } from '@excalidraw/excalidraw/types';
import type { WireElement } from '../collab/elements.ts';
import { imageFiles, reconcileWith } from './editor.ts';

export interface CanvasHandle {
	/** The scene document, as JSON text. */
	document(): string;
	/**
	 * What the editor's own `reconcileElements` makes of two lists of
	 * elements, as JSON text in and out. It touches no scene. A browser test
	 * holds it to the table the server's rule is held to.
	 */
	reconcile(local: string, remote: string): string;
	/**
	 * The other connections the editor has been told of, as JSON text: for
	 * each, its `id`, the `username` beside its cursor, and the `pointer`.
	 */
	peers(): string;
	/**
	 * The images on the canvas that are not deleted, as JSON text: for each,
	 * the element's `id`, its `fileId`, where it is, and the `mimeType` of its
	 * file, or null while the canvas does not hold the file.
	 */
	images(): string;
}

declare global {
	interface Window {
		SEGL_CANVAS?: CanvasHandle;
	}
}

export function publishHandle(api: ExcalidrawImperativeAPI): void {
	window.SEGL_CANVAS = {
		document: () =>
			serializeAsJSON(
				api.getSceneElementsIncludingDeleted(),
				api.getAppState(),
				api.getFiles(),
				'database'
			),
		reconcile: (local, remote) =>
			JSON.stringify(
				reconcileWith(api, JSON.parse(local) as WireElement[], JSON.parse(remote) as WireElement[])
			),
		peers: () =>
			JSON.stringify(
				Array.from(api.getAppState().collaborators.values(), ({ id, username, pointer }) => ({
					id,
					username,
					pointer: pointer ?? null
				}))
			),
		images: () => {
			const files = imageFiles(api);
			return JSON.stringify(
				api
					.getSceneElements()
					.filter((element) => element.type === 'image')
					.map(({ id, fileId, x, y, width, height }) => ({
						id,
						fileId,
						x,
						y,
						width,
						height,
						mimeType: (fileId && files.get(fileId)?.mimeType) || null
					}))
			);
		}
	};
}

export function clearHandle(): void {
	delete window.SEGL_CANVAS;
}
