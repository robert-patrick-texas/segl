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

/** From a stored scene document to what the editor takes as `initialData`. */

import type { ExcalidrawInitialDataState } from '@excalidraw/excalidraw/types';

function isRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/**
 * Pick the parts of a stored document the editor restores: its elements, the
 * app state it saved, and its files. The editor checks and repairs each
 * element itself. Anything else, such as a document that is not an object,
 * gives an empty canvas, not an error.
 */
export function initialDataFrom(document: unknown): ExcalidrawInitialDataState {
	if (!isRecord(document)) return { elements: [] };
	const { elements, appState, files } = document;
	return {
		elements: Array.isArray(elements) ? elements : [],
		...(isRecord(appState) ? { appState } : {}),
		...(isRecord(files) ? { files: files as ExcalidrawInitialDataState['files'] } : {})
	};
}
