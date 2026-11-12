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

/** One slot: the segl bar, and under it the canvas with that slot's head scene. */
import { lazy, Suspense, useEffect, useState } from 'react';
import { fetchScene, fetchSlots, type SlotScene } from './api.ts';
import { SeglBar } from './bar/SeglBar.tsx';
import { storageKey, type AppConfig } from './config.ts';
import { browserStorage, writeLastSlot } from './slots.ts';

// Its own chunk: the bar paints before the editor has arrived.
const Canvas = lazy(() => import('./canvas/Canvas.tsx'));

type Load =
	| { state: 'loading' }
	| { state: 'ready'; scene: SlotScene }
	| { state: 'failed'; message: string };

const NO_TITLES: ReadonlyMap<number, string> = new Map();

export function SlotPage({ config, slot }: { config: AppConfig; slot: number }) {
	const [titles, setTitles] = useState(NO_TITLES);
	const [load, setLoad] = useState<Load>({ state: 'loading' });
	const [attempt, setAttempt] = useState(0);

	useEffect(() => {
		writeLastSlot(browserStorage(), storageKey(config, 'lastSlot'), slot);
	}, [config, slot]);

	useEffect(() => {
		const abort = new AbortController();
		setLoad({ state: 'loading' });
		Promise.all([fetchSlots(config, abort.signal), fetchScene(config, slot, abort.signal)])
			.then(([slots, scene]) => {
				setTitles(new Map(slots.map((entry) => [entry.number, entry.title])));
				setLoad({ state: 'ready', scene });
			})
			.catch((error: unknown) => {
				if (abort.signal.aborted) return;
				const message = error instanceof Error ? error.message : String(error);
				setLoad({ state: 'failed', message });
			});
		return () => abort.abort();
	}, [config, slot, attempt]);

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
			/>
			<main className="segl__canvas">
				{load.state === 'ready' && (
					<Suspense fallback={<p className="segl__status">Loading the editor…</p>}>
						<Canvas key={slot} document={load.scene.scene} />
					</Suspense>
				)}
				{load.state === 'loading' && <p className="segl__status">Loading slot {slot}…</p>}
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
