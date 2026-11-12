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
import type { ExcalidrawImperativeAPI } from '@excalidraw/excalidraw/types';
import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent } from 'react';
import type { Cursor } from '../collab/protocol.ts';
import type { SceneEditor } from '../collab/session.ts';
import { goesToImport } from '../importing.ts';
import './canvas.css';
import { makeEditor } from './editor.ts';
import { clearHandle, publishHandle } from './handle.ts';
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
}

type PointerUpdate = { pointer: { x: number; y: number } };

/**
 * The editor's own ways to open a scene file are off: its menu entry, and
 * Ctrl+O with it. Each would put the file in this browser's canvas alone. The
 * editor's export stays, as its menu has it (S-011, D2-031).
 */
const UI_OPTIONS = { canvasActions: { loadScene: false } };

export default function Canvas({
	document,
	exportName,
	onSceneFile,
	viewOnly = false,
	onEditor,
	onChange,
	onCursor
}: CanvasProps) {
	const initialData = useMemo(() => initialDataFrom(document), [document]);
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
	const changed = useCallback(() => {
		if (offered.current.length > 0) {
			const mounted = offered.current.find((each) => !each.getAppState().isLoading);
			if (mounted !== undefined) {
				offered.current = [];
				setApi(mounted);
			}
		}
		onChange?.();
	}, [onChange]);

	useEffect(() => {
		if (api === null) return;
		publishHandle(api);
		onEditor?.(makeEditor(api));
		return () => {
			clearHandle();
			onEditor?.(null);
		};
	}, [api, onEditor]);

	const pointerMoved = useCallback(
		({ pointer }: PointerUpdate) => onCursor?.({ x: pointer.x, y: pointer.y }),
		[onCursor]
	);

	// On the way down to the editor, which would open a dropped scene file
	// itself. An image, or a library of shapes, goes on to it.
	const dropped = useCallback(
		(event: DragEvent<HTMLDivElement>) => {
			const file = event.dataTransfer.files.item(0);
			if (file === null || !goesToImport(file)) return;
			event.preventDefault();
			event.stopPropagation();
			onSceneFile?.(file);
		},
		[onSceneFile]
	);

	return (
		<div className="segl-canvas" onDropCapture={dropped}>
			<Excalidraw
				initialData={initialData}
				excalidrawAPI={keepApi}
				name={exportName}
				UIOptions={UI_OPTIONS}
				viewModeEnabled={viewOnly}
				onChange={changed}
				onPointerUpdate={pointerMoved}
			/>
		</div>
	);
}
