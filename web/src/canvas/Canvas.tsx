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
import { useEffect, useMemo } from 'react';
import { clearHandle, publishHandle } from './handle.ts';
import { initialDataFrom } from './scene.ts';

export interface CanvasProps {
	/** The slot's stored scene document. Read once, when the canvas mounts. */
	document: unknown;
	/** True when this browser may look and not edit. */
	viewOnly?: boolean;
}

export default function Canvas({ document, viewOnly = false }: CanvasProps) {
	const initialData = useMemo(() => initialDataFrom(document), [document]);
	useEffect(() => clearHandle, []);
	return (
		<Excalidraw
			initialData={initialData}
			excalidrawAPI={publishHandle}
			viewModeEnabled={viewOnly}
		/>
	);
}
