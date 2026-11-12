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
 * What the editor reads from `window` when its module first runs. Call
 * `prepareEditor` before the canvas is imported.
 */

/**
 * The `source` the editor writes into a scene document. Upstream uses the
 * page's origin. A fixed name keeps a site's host name out of stored scenes
 * and exported files, and makes the empty scene the same on every host.
 */
export const EXPORT_SOURCE = 'segl';

interface EditorGlobals {
	EXCALIDRAW_ASSET_PATH?: string | string[];
	EXCALIDRAW_EXPORT_SOURCE?: string;
}

/**
 * Point the editor at segl for its fonts (S-014, D2-026). Without this it
 * falls back to a public CDN. `rootUrl` is segl's root, where the build's
 * `fonts/` folder is served.
 */
export function prepareEditor(rootUrl: URL, target: EditorGlobals = window as EditorGlobals): void {
	target.EXCALIDRAW_ASSET_PATH = rootUrl.href;
	target.EXCALIDRAW_EXPORT_SOURCE = EXPORT_SOURCE;
}
