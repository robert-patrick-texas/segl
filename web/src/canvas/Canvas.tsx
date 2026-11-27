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
 * The Excalidraw editor. Only the files in this folder import the upstream
 * package. The rest of the application talks to this component.
 */
import { Excalidraw } from '@excalidraw/excalidraw';
import '@excalidraw/excalidraw/index.css';
import type { OrderedExcalidrawElement } from '@excalidraw/excalidraw/element/types';
import type { AppState, ExcalidrawImperativeAPI } from '@excalidraw/excalidraw/types';
import {
	useCallback,
	useEffect,
	useMemo,
	useRef,
	useState,
	type CSSProperties,
	type DragEvent
} from 'react';
import type { Cursor, View } from '../collab/protocol.ts';
import type { SceneEditor } from '../collab/session.ts';
import { dropGoesTo } from '../importing.ts';
import type { LinkKind, State } from '../network/kinds.ts';
import { NetworkPanel } from '../network/NetworkPanel.tsx';
import { selectedObject, type NetworkObject } from '../network/selection.ts';
import './canvas.css';
import { makeEditor } from './editor.ts';
import { visibleArea } from './fit.ts';
import { clearHandle, publishHandle } from './handle.ts';
import { networkLibrary, renewCopies, setLinkKind, setObjectState } from './network.ts';
import { initialDataFrom } from './scene.ts';

export interface CanvasProps {
	/** The slot's stored scene document. Read once, when the canvas mounts. */
	document: unknown;
	/** What the editor calls a file it exports, without the extension. */
	exportName?: string;
	/**
	 * Called with a scene file that was dropped on the canvas. The editor is
	 * not given it: the page imports it, for everyone on the slot.
	 */
	onSceneFile?: (file: File) => void;
	/** True when this browser may look and not edit. */
	viewOnly?: boolean;
	/** Called with the editor once it is mounted, and with null when it goes. */
	onEditor?: (editor: SceneEditor | null) => void;
	/** Called when anything in the editor changed. The elements may be the same. */
	onChange?: () => void;
	/** Called as this browser's pointer moves over the canvas. */
	onCursor?: (cursor: Cursor) => void;
	/** Called with the area of the scene the canvas shows, whenever the editor changed (T18). */
	onView?: (view: View) => void;
	/**
	 * Called when the editor ended its follow of this connection: the person
	 * scrolled, zoomed, clicked on the canvas, or pressed its own Stop, or the
	 * person followed left.
	 */
	onUnfollow?: (connectionId: string) => void;
}

type PointerUpdate = { pointer: { x: number; y: number } };

/**
 * The editor's own ways to open a scene file are off: its menu entry, and
 * Ctrl+O with it. Each would put the file in this browser's canvas alone. The
 * editor's export stays, as its menu has it (S-011, D2-031).
 */
const UI_OPTIONS = { canvasActions: { loadScene: false } };

/** Whether the panel would show the same thing for both. */
function sameObject(a: NetworkObject | null, b: NetworkObject | null): boolean {
	return JSON.stringify(a) === JSON.stringify(b);
}

export default function Canvas({
	document,
	exportName,
	onSceneFile,
	viewOnly = false,
	onEditor,
	onChange,
	onCursor,
	onView,
	onUnfollow
}: CanvasProps) {
	// segl's network library, which the editor merges with the person's own.
	const initialData = useMemo(
		() => ({ ...initialDataFrom(document), libraryItems: networkLibrary() }),
		[document]
	);
	const wrapper = useRef<HTMLDivElement>(null);
	const [picked, setPicked] = useState<NetworkObject | null>(null);
	const [sidebar, setSidebar] = useState(0);
	// The editor hands out its API from its constructor: during a render, and
	// before it has mounted or loaded the scene. In development React constructs
	// the editor twice and mounts one of the two. So the APIs are only kept
	// here, and the first change the editor reports picks the one whose editor
	// has loaded, which the one that was thrown away never does.
	const offered = useRef<ExcalidrawImperativeAPI[]>([]);
	const [api, setApi] = useState<ExcalidrawImperativeAPI | null>(null);
	const keepApi = useCallback((given: ExcalidrawImperativeAPI) => {
		offered.current.push(given);
	}, []);
	const changed = useCallback(
		(elements: readonly OrderedExcalidrawElement[], appState: AppState) => {
			if (offered.current.length > 0) {
				const mounted = offered.current.find((each) => !each.getAppState().isLoading);
				if (mounted !== undefined) {
					offered.current = [];
					setApi(mounted);
				}
			}
			const next = selectedObject(elements, new Set(Object.keys(appState.selectedElementIds)));
			setPicked((before) => (sameObject(before, next) ? before : next));
			// The panel moves left of the library while it is open.
			const open = appState.openSidebar !== null;
			const width = open
				? (wrapper.current?.querySelector('.excalidraw .sidebar')?.getBoundingClientRect().width ??
					0)
				: 0;
			setSidebar((before) => (before === width ? before : width));
			onView?.(
				visibleArea({
					scrollX: appState.scrollX,
					scrollY: appState.scrollY,
					zoom: appState.zoom.value,
					width: appState.width,
					height: appState.height
				})
			);
			onChange?.();
		},
		[onChange, onView]
	);

	const setState = useCallback(
		(state: State) => {
			if (api !== null && picked !== null) setObjectState(api, picked.objectId, state);
		},
		[api, picked]
	);
	const setKind = useCallback(
		(kind: LinkKind) => {
			if (api !== null && picked !== null) setLinkKind(api, picked.objectId, kind);
		},
		[api, picked]
	);

	useEffect(() => {
		if (api === null) return;
		publishHandle(api);
		onEditor?.(makeEditor(api));
		return () => {
			clearHandle();
			onEditor?.(null);
		};
	}, [api, onEditor]);

	// The editor says when a follow starts and ends, segl's own changes too.
	// Only an end matters: a follow starts from segl's bar.
	useEffect(() => {
		if (api === null || onUnfollow === undefined) return;
		return api.onUserFollow(({ userToFollow, action }) => {
			if (action === 'UNFOLLOW') onUnfollow(userToFollow.socketId);
		});
	}, [api, onUnfollow]);

	const pointerMoved = useCallback(
		({ pointer }: PointerUpdate) => onCursor?.({ x: pointer.x, y: pointer.y }),
		[onCursor]
	);

	// On the way down to the editor, which would open a dropped scene file
	// itself, and would place an image on a viewer's canvas. For an editor, an
	// image or a library of shapes goes on to it.
	const dropped = useCallback(
		(event: DragEvent<HTMLDivElement>) => {
			const file = event.dataTransfer.files.item(0);
			const goesTo = dropGoesTo(file, viewOnly);
			if (goesTo === 'editor') return;
			event.preventDefault();
			event.stopPropagation();
			if (goesTo === 'import' && file !== null) onSceneFile?.(file);
		},
		[onSceneFile, viewOnly]
	);

	return (
		<div
			className="segl-canvas"
			ref={wrapper}
			onDropCapture={dropped}
			style={{ '--segl-sidebar': `${sidebar}px` } as CSSProperties}
		>
			<Excalidraw
				initialData={initialData}
				excalidrawAPI={keepApi}
				name={exportName}
				UIOptions={UI_OPTIONS}
				viewModeEnabled={viewOnly}
				onChange={changed}
				onPointerUpdate={pointerMoved}
				onDuplicate={renewCopies}
			/>
			{picked !== null && api !== null && (
				<NetworkPanel object={picked} onState={setState} onKind={setKind} />
			)}
		</div>
	);
}
