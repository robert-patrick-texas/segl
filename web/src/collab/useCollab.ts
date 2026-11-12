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

/** One slot's live connection, as React state (docs/ARCHITECTURE.md, "Collaboration"). */
import { useCallback, useEffect, useRef, useState } from 'react';
import { collabUrl, storageKey, type AppConfig } from '../config.ts';
import { browserStorage } from '../slots.ts';
import { readClientId, readEditToken } from './identity.ts';
import type { Cursor } from './protocol.ts';
import { CollabSession, INITIAL_STATE, type SceneEditor, type SessionState } from './session.ts';

export interface CollabOptions {
	config: AppConfig;
	slot: number;
	/** The epoch of the scene the canvas was loaded with, or null until it has loaded. */
	epoch: number | null;
	/** This browser's display name, or null while it has none. */
	name: string | null;
}

export interface Collab {
	state: SessionState;
	/** Give these three to the canvas. */
	onEditor: (editor: SceneEditor | null) => void;
	onChange: () => void;
	onCursor: (cursor: Cursor) => void;
}

/**
 * Connect to the slot's room once the canvas is mounted with the slot's
 * scene, and stay connected until the slot or the canvas changes. Before
 * that, and between slots, the state is the initial one: connecting, nobody
 * here.
 */
export function useCollab({ config, slot, epoch, name }: CollabOptions): Collab {
	const [editor, setEditor] = useState<SceneEditor | null>(null);
	// Kept with its slot, so that a state from the slot just left is never shown.
	const [held, setHeld] = useState<{ slot: number; state: SessionState } | null>(null);
	const session = useRef<CollabSession | null>(null);
	const latestName = useRef(name);
	const sentName = useRef(name);

	useEffect(() => {
		latestName.current = name;
	}, [name]);

	useEffect(() => {
		if (editor === null || epoch === null) return;
		const storage = browserStorage();
		const started = new CollabSession({
			url: collabUrl(config, slot).href,
			epoch,
			editor,
			hello: () => {
				sentName.current = latestName.current;
				return {
					clientId: readClientId(storage, storageKey(config, 'clientId')),
					displayName: latestName.current,
					editToken: readEditToken(storage, storageKey(config, 'editToken'))
				};
			},
			onState: (state) => setHeld({ slot, state })
		});
		session.current = started;
		started.start();
		return () => {
			started.stop();
			session.current = null;
			setHeld(null);
		};
	}, [config, slot, epoch, editor]);

	// The label changed after `hello` was sent with another, or with none.
	useEffect(() => {
		const sent = sentName.current;
		if (name === null || name === sent || session.current === null) return;
		sentName.current = name;
		// A first label is one the server assigned, and `hello` carries it as
		// written. Any later one was typed, here or in another tab.
		if (sent === null) session.current.reconnect();
		else session.current.rename(name);
	}, [name]);

	const onChange = useCallback(() => session.current?.localChange(), []);
	const onCursor = useCallback((cursor: Cursor) => session.current?.cursor(cursor), []);

	return {
		state: held !== null && held.slot === slot ? held.state : INITIAL_STATE,
		onEditor: setEditor,
		onChange,
		onCursor
	};
}
