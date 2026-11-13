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
 * One slot: the segl bar, and under it the canvas with that slot's scene,
 * shared live with everyone else on the slot.
 */
import { lazy, Suspense, useCallback, useEffect, useState } from 'react';
import {
	fetchRevisions,
	fetchScene,
	fetchSlots,
	importScene,
	renameSlot,
	restoreRevision,
	type SlotScene
} from './api.ts';
import { editingState } from './bar/notice.ts';
import { SeglBar } from './bar/SeglBar.tsx';
import type { WireElement } from './collab/elements.ts';
import type { FileRef } from './collab/files.ts';
import { useCollab } from './collab/useCollab.ts';
import { storageKey, type AppConfig } from './config.ts';
import { exportName } from './importing.ts';
import { loadedScene, type Load } from './load.ts';
import { browserStorage, writeLastSlot } from './slots.ts';
import type { DisplayName } from './useDisplayName.ts';
import type { Pass } from './usePass.ts';

// Its own chunk: the bar paints before the editor has arrived.
const Canvas = lazy(() => import('./canvas/Canvas.tsx'));

const NO_TITLES: ReadonlyMap<number, string> = new Map();
const NO_FILES: readonly FileRef[] = [];
const NO_ELEMENTS: readonly WireElement[] = [];

export interface SlotPageProps {
	config: AppConfig;
	slot: number;
	/** This browser's display name. It belongs to the browser, not to a slot. */
	displayName: DisplayName;
	/** This browser's pass, which an access code bought. It belongs to the browser too. */
	editPass: Pass;
}

export function SlotPage({ config, slot, displayName, editPass }: SlotPageProps) {
	const pass = editPass.pass;
	const [titles, setTitles] = useState(NO_TITLES);
	const [load, setLoad] = useState<Load<SlotScene>>({ state: 'loading' });
	const [attempt, setAttempt] = useState(0);
	// Null on the way to another slot too, while `load` is still the old slot's.
	const scene = loadedScene(load, slot);
	const collab = useCollab({
		config,
		slot,
		epoch: scene === null ? null : scene.epoch,
		elements: scene === null ? NO_ELEMENTS : scene.elements,
		files: scene === null ? NO_FILES : scene.files,
		name: displayName.name,
		pass
	});
	// Until the server has said, a browser may edit unless a code is needed.
	const viewOnly = collab.state.viewOnly ?? config.editRequired;

	useEffect(() => {
		writeLastSlot(browserStorage(), storageKey(config, 'lastSlot'), slot);
	}, [config, slot]);

	useEffect(() => {
		const abort = new AbortController();
		setLoad({ state: 'loading' });
		Promise.all([fetchSlots(config, abort.signal), fetchScene(config, slot, abort.signal)])
			.then(([slots, loaded]) => {
				setTitles(new Map(slots.map((entry) => [entry.number, entry.title])));
				setLoad({ state: 'ready', slot, scene: loaded });
			})
			.catch((error: unknown) => {
				if (abort.signal.aborted) return;
				const message = error instanceof Error ? error.message : String(error);
				setLoad({ state: 'failed', message });
			});
		return () => abort.abort();
	}, [config, slot, attempt]);

	const setTitle = useCallback((number: number, title: string) => {
		setTitles((before) =>
			before.get(number) === title ? before : new Map(before).set(number, title)
		);
	}, []);

	// The room's title: in `welcome`, and again whenever someone changes it.
	const roomTitle = collab.state.title;
	useEffect(() => {
		if (roomTitle !== null) setTitle(slot, roomTitle);
	}, [roomTitle, slot, setTitle]);

	const retitle = useCallback(
		async (title: string) => {
			const stored = await renameSlot(config, slot, title, pass);
			setTitle(stored.number, stored.title);
		},
		[config, slot, pass, setTitle]
	);

	const loadHistory = useCallback(
		(signal: AbortSignal) => fetchRevisions(config, slot, signal),
		[config, slot]
	);

	// The canvas is not touched here. The server sends the restored scene to
	// every browser on the slot, this one among them, over the socket.
	const name = displayName.name;
	const restore = useCallback(
		async (revision: number) => {
			await restoreRevision(config, slot, revision, name, pass);
		},
		[config, slot, name, pass]
	);

	// The exported file that waits for the second press, with the slot it was
	// offered on: chosen in the bar, or dropped on the canvas.
	const [offered, setOffered] = useState<{ slot: number; file: File } | null>(null);
	const importFile = offered !== null && offered.slot === slot ? offered.file : null;
	const chooseImport = useCallback(
		(file: File | null) => setOffered(file === null ? null : { slot, file }),
		[slot]
	);

	// As a restore: the canvas is not touched here, and the scene arrives
	// over the socket.
	const importFrom = useCallback(
		async (file: File) => {
			await importScene(config, slot, file, name, pass);
		},
		[config, slot, name, pass]
	);

	const title = titles.get(slot);
	useEffect(() => {
		document.title = title ? `${title} · segl` : 'segl';
	}, [title]);

	return (
		<div className="segl">
			<SeglBar
				slot={slot}
				titles={titles}
				editing={editingState({
					editRequired: config.editRequired,
					viewOnly: collab.state.viewOnly,
					hasPass: pass !== ''
				})}
				version={__SEGL_VERSION__}
				displayName={displayName.name}
				onRename={displayName.rename}
				status={collab.state.status}
				participants={collab.state.participants}
				self={collab.state.connectionId}
				canEdit={!viewOnly}
				onRetitle={retitle}
				epoch={collab.state.epoch}
				onLoadHistory={loadHistory}
				onRestore={restore}
				importFile={importFile}
				onChooseImport={chooseImport}
				onImport={importFrom}
			/>
			<main className="segl__canvas">
				{scene !== null && (
					<Suspense fallback={<p className="segl__status">Loading the editor…</p>}>
						<Canvas
							key={slot}
							document={scene.scene}
							exportName={exportName(title, slot)}
							viewOnly={viewOnly}
							onSceneFile={chooseImport}
							onEditor={collab.onEditor}
							onChange={collab.onChange}
							onCursor={collab.onCursor}
						/>
					</Suspense>
				)}
				{scene === null && load.state !== 'failed' && (
					<p className="segl__status">Loading slot {slot}…</p>
				)}
				{load.state === 'failed' && (
					<p className="segl__status" role="alert">
						segl could not load slot {slot}: {load.message}
						<button type="button" onClick={() => setAttempt((count) => count + 1)}>
							Try again
						</button>
					</p>
				)}
			</main>
		</div>
	);
}
