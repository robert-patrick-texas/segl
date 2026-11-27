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
 * Diagram mode's pane: drawio's editor in a frame, under the segl bar
 * (D2-039). segl serves drawio from its own origin, under its own root, so
 * the frame works at a host root and under any path a proxy strips.
 */
import { useEffect, useRef } from 'react';
import {
	DiagramFrame,
	drawioAddress,
	type DiagramEdit,
	type DiagramFrameLike,
	type FrameWatcher
} from './frame.ts';
import './diagram.css';

export interface DiagramPaneProps {
	/** segl's root URL. */
	rootUrl: URL;
	/** Takes the frame's adapter once mounted, and null when it goes. */
	onFrame: (frame: DiagramFrameLike | null) => void;
	/** Takes the person's edits. */
	onEdit: (edit: DiagramEdit) => void;
	/** Takes where the person looks and points, for follow mode and cursors (T18). */
	watcher: FrameWatcher;
}

export default function DiagramPane({ rootUrl, onFrame, onEdit, watcher }: DiagramPaneProps) {
	const element = useRef<HTMLIFrameElement>(null);
	const edits = useRef(onEdit);
	const watching = useRef(watcher);

	useEffect(() => {
		edits.current = onEdit;
	}, [onEdit]);

	useEffect(() => {
		watching.current = watcher;
	}, [watcher]);

	useEffect(() => {
		const iframe = element.current;
		if (iframe === null) return;
		const frame = new DiagramFrame({
			target: () => iframe.contentWindow,
			origin: window.location.origin,
			onEdit: (edit) => edits.current(edit),
			onView: (view) => watching.current.onView(view),
			onPointer: (cursor) => watching.current.onPointer(cursor),
			onLooked: () => watching.current.onLooked()
		});
		const listen = (event: MessageEvent) => frame.handle(event);
		window.addEventListener('message', listen);
		onFrame(frame);
		return () => {
			window.removeEventListener('message', listen);
			onFrame(null);
		};
	}, [onFrame]);

	return (
		<iframe
			ref={element}
			className="segl-diagram"
			title="Diagram mode"
			src={drawioAddress(rootUrl)}
		/>
	);
}
