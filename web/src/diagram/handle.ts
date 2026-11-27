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
 * A read-only handle on Diagram mode, at `window.SEGL_DIAGRAM`.
 *
 * drawio draws in its own frame, so the browser tests and the measures of
 * D2-040 read the diagram through this: `xml()` asks the frame for its whole
 * diagram, and `counts()` says how often this page found its diagram had
 * drifted and loaded the whole of it again. It changes nothing, and shows
 * nothing the page's own user cannot already see.
 */
import type { DiagramFrameLike } from './frame.ts';
import type { DiagramSession } from './session.ts';

export interface DiagramHandle {
	/** The frame's whole diagram, as drawio's XML. */
	xml(): Promise<string>;
	/** `{ mismatches, reloads }`, as JSON text. */
	counts(): string;
}

declare global {
	interface Window {
		SEGL_DIAGRAM?: DiagramHandle;
	}
}

/** Set the handle. Return what takes it away again. */
export function installDiagramHandle(frame: DiagramFrameLike, session: DiagramSession): () => void {
	const handle: DiagramHandle = {
		xml: () => frame.xml(),
		counts: () => JSON.stringify(session.counts)
	};
	window.SEGL_DIAGRAM = handle;
	return () => {
		if (window.SEGL_DIAGRAM === handle) delete window.SEGL_DIAGRAM;
	};
}
