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
 * captured (docs/DEVELOPMENT.md). It exposes nothing the page's own user
 * cannot already see.
 */
import { serializeAsJSON } from '@excalidraw/excalidraw';
import type { ExcalidrawImperativeAPI } from '@excalidraw/excalidraw/types';

export interface CanvasHandle {
	/** The scene document, as JSON text. */
	document(): string;
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
			)
	};
}

export function clearHandle(): void {
	delete window.SEGL_CANVAS;
}
