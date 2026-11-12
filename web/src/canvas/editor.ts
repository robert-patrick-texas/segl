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
 * The mounted editor as the collaboration session uses it (`SceneEditor` in
 * `collab/session.ts`): read the elements, merge elements from the server, and
 * draw the other people's cursors. This is where the package's
 * `reconcileElements` is called (D2-025).
 */
import {
	CaptureUpdateAction,
	isInvisiblySmallElement,
	reconcileElements,
	restoreElements
} from '@excalidraw/excalidraw';
import type {
	ExcalidrawElement,
	OrderedExcalidrawElement
} from '@excalidraw/excalidraw/element/types';
import type { Collaborator, ExcalidrawImperativeAPI, SocketId } from '@excalidraw/excalidraw/types';
import type { WireElement } from '../collab/elements.ts';
import type { Peer, SceneEditor } from '../collab/session.ts';

type Remote = Parameters<typeof reconcileElements>[1];

/** What a peer without a label is called beside its cursor. */
export const UNNAMED = 'Unnamed';

/**
 * Elements as they came off the socket, made into elements the editor can
 * hold: it checks each one and fills in what an older editor left out.
 */
function restored(elements: readonly WireElement[]): Remote {
	// The package marks elements from elsewhere with a type of their own.
	return restoreElements(elements as unknown as ExcalidrawElement[], null) as unknown as Remote;
}

/**
 * Worth sending: every deleted element, since the deletion is the news, and
 * every other one the editor would keep. A shape with no size, left behind by
 * a click, is dropped by the editor itself on load.
 */
function worthSending(element: ExcalidrawElement): boolean {
	return element.isDeleted || !isInvisiblySmallElement(element);
}

export function collaborators(peers: readonly Peer[]): Map<SocketId, Collaborator> {
	return new Map(
		peers.map((peer) => [
			peer.connectionId as SocketId,
			{
				id: peer.connectionId,
				socketId: peer.connectionId as SocketId,
				// No color: the editor takes one from `id`, and no other.
				username: peer.displayName ?? UNNAMED,
				...(peer.cursor ? { pointer: { ...peer.cursor, tool: 'pointer' as const } } : {})
			}
		])
	);
}

export function makeEditor(api: ExcalidrawImperativeAPI): SceneEditor {
	return {
		elements: () =>
			api.getSceneElementsIncludingDeleted().filter(worthSending) as unknown as WireElement[],
		reconcile(remote) {
			const elements = reconcileElements(
				api.getSceneElementsIncludingDeleted(),
				restored(remote),
				api.getAppState()
			);
			// NEVER: someone else's edit is not on this browser's undo stack.
			api.updateScene({ elements, captureUpdate: CaptureUpdateAction.NEVER });
		},
		replace(elements) {
			api.updateScene({ elements: restored(elements), captureUpdate: CaptureUpdateAction.NEVER });
			// Undo must not reach back into the scene that was replaced.
			api.history.clear();
		},
		showPeers(peers) {
			api.updateScene({ collaborators: collaborators(peers) });
		}
	};
}

/**
 * Reconcile two lists of elements with the package's helper, for the browser
 * test that holds it to `tests/reconcile_cases.json`.
 */
export function reconcileWith(
	api: ExcalidrawImperativeAPI,
	local: readonly WireElement[],
	remote: readonly WireElement[]
): WireElement[] {
	return reconcileElements(
		local as unknown as OrderedExcalidrawElement[],
		remote as unknown as Remote,
		api.getAppState()
	) as unknown as WireElement[];
}
