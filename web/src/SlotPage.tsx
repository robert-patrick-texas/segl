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
import { fetchScene, fetchSlots, renameSlot, type SlotScene } from './api.ts';
import { SeglBar } from './bar/SeglBar.tsx';
import type { FileRef } from './collab/files.ts';
import { readEditToken } from './collab/identity.ts';
import { useCollab } from './collab/useCollab.ts';
import { storageKey, type AppConfig } from './config.ts';
import { loadedScene, type Load } from './load.ts';
import { browserStorage, writeLastSlot } from './slots.ts';
import type { DisplayName } from './useDisplayName.ts';

// Its own chunk: the bar paints before the editor has arrived.
const Canvas = lazy(() => import('./canvas/Canvas.tsx'));

const NO_TITLES: ReadonlyMap<number, string> = new Map();
const NO_FILES: readonly FileRef[] = [];

export interface SlotPageProps {
	config: AppConfig;
	slot: number;
	/** This browser's display name. It belongs to the browser, not to a slot. */
	displayName: DisplayName;
}

export function SlotPage({ config, slot, displayName }: SlotPageProps) {
	const [titles, setTitles] = useState(NO_TITLES);
	const [load, setLoad] = useState<Load<SlotScene>>({ state: 'loading' });
	const [attempt, setAttempt] = useState(0);
	// Null on the way to another slot too, while `load` is still the old slot's.
	const scene = loadedScene(load, slot);
	const collab = useCollab({
		config,
		slot,
		epoch: scene === null ? null : scene.epoch,
		files: scene === null ? NO_FILES : scene.files,
		name: displayName.name
	});
	// Until the server has said, a browser may edit unless a token is needed.
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
			const token = readEditToken(browserStorage(), storageKey(config, 'editToken'));
			const stored = await renameSlot(config, slot, title, token);
			setTitle(stored.number, stored.title);
		},
		[config, slot, setTitle]
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
				editRequired={config.editRequired}
				version={__SEGL_VERSION__}
				displayName={displayName.name}
				onRename={displayName.rename}
				status={collab.state.status}
				participants={collab.state.participants}
				self={collab.state.connectionId}
				canEdit={!viewOnly}
				onRetitle={retitle}
			/>
			<main className="segl__canvas">
				{scene !== null && (
					<Suspense fallback={<p className="segl__status">Loading the editor…</p>}>
						<Canvas
							key={slot}
							document={scene.scene}
							viewOnly={viewOnly}
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
