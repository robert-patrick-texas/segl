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

/** Slot 9's live connection, as React state (D2-040). */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { readClientId } from '../collab/identity.ts';
import { collabUrl, storageKey, type AppConfig } from '../config.ts';
import { browserStorage } from '../slots.ts';
import type { DiagramEdit, DiagramFrameLike, FrameWatcher } from './frame.ts';
import { installDiagramHandle } from './handle.ts';
import { DiagramSession, INITIAL_DIAGRAM_STATE, type DiagramState } from './session.ts';

export interface DiagramOptions {
	config: AppConfig;
	slot: number;
	/** The head the page loaded: its epoch, its diagram, and its mark. Null until it has loaded. */
	epoch: number | null;
	xml: string | null;
	mark: string | null;
	name: string | null;
	pass: string;
	/** drawio's frame, once the pane has mounted it. */
	frame: DiagramFrameLike | null;
}

export interface Diagram {
	state: DiagramState;
	/** Give the frame's edits to this. */
	onEdit: (edit: DiagramEdit) => void;
	/** Take the pen, or give it back. */
	onPen: (take: boolean) => void;
	/** Follow this connection's view, or stop: null (T18). For the bar. */
	onFollow: (connectionId: string | null) => void;
	/** Give this to the frame: where the person looks and points, and what they select. */
	watcher: FrameWatcher;
}

/**
 * Connect to slot 9 once the page has its head and the frame is mounted, and
 * stay connected until either changes.
 */
export function useDiagram({
	config,
	slot,
	epoch,
	xml,
	mark,
	name,
	pass,
	frame
}: DiagramOptions): Diagram {
	const [state, setState] = useState<DiagramState>(INITIAL_DIAGRAM_STATE);
	const session = useRef<DiagramSession | null>(null);
	const latestName = useRef(name);
	const sentName = useRef(name);
	const latestPass = useRef(pass);
	const sentPass = useRef(pass);

	useEffect(() => {
		latestName.current = name;
	}, [name]);

	useEffect(() => {
		latestPass.current = pass;
	}, [pass]);

	useEffect(() => {
		if (frame === null || epoch === null || xml === null) return;
		const storage = browserStorage();
		const started = new DiagramSession({
			url: collabUrl(config, slot).href,
			epoch,
			xml,
			mark,
			frame,
			editRequired: config.editRequired,
			hello: () => {
				sentName.current = latestName.current;
				sentPass.current = latestPass.current;
				return {
					clientId: readClientId(storage, storageKey(config, 'clientId')),
					displayName: latestName.current,
					editToken: latestPass.current
				};
			},
			onState: setState
		});
		session.current = started;
		const removeHandle = installDiagramHandle(frame, started);
		started.start();
		return () => {
			removeHandle();
			started.stop();
			session.current = null;
			setState(INITIAL_DIAGRAM_STATE);
		};
	}, [config, slot, epoch, xml, mark, frame]);

	useEffect(() => {
		const sent = sentName.current;
		if (name === null || name === sent || session.current === null) return;
		sentName.current = name;
		if (sent === null) session.current.reconnect();
		else session.current.rename(name);
	}, [name]);

	useEffect(() => {
		if (pass === sentPass.current || session.current === null) return;
		sentPass.current = pass;
		session.current.reconnect();
	}, [pass]);

	const onEdit = useCallback((edit: DiagramEdit) => session.current?.edit(edit), []);
	const onPen = useCallback((take: boolean) => session.current?.pen(take), []);
	const onFollow = useCallback((id: string | null) => session.current?.follow(id), []);
	const watcher = useMemo<FrameWatcher>(
		() => ({
			onView: (view) => session.current?.viewChanged(view),
			onPointer: (cursor) => session.current?.pointer(cursor),
			onLooked: () => session.current?.looked(),
			onSelection: (selection) => session.current?.selectionChanged(selection)
		}),
		[]
	);
	return { state, onEdit, onPen, onFollow, watcher };
}
