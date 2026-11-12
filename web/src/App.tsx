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
 * Routes, under segl's root (docs/ARCHITECTURE.md, "Mount and navigation"):
 * the root opens the last slot this browser used, or slot 1. `s/N` opens
 * slot N. Anything else, such as `s/0` or `s/abc`, goes to slot 1.
 */
import { BrowserRouter, Navigate, Route, Routes, useParams } from 'react-router';
import { routerBasename, storageKey, type AppConfig } from './config.ts';
import { SlotPage } from './SlotPage.tsx';
import { browserStorage, FIRST_SLOT, parseSlot, readLastSlot } from './slots.ts';

function LastSlot({ config }: { config: AppConfig }) {
	const last = readLastSlot(browserStorage(), storageKey(config, 'lastSlot'));
	return <Navigate to={`/s/${last ?? FIRST_SLOT}`} replace />;
}

function SlotRoute({ config }: { config: AppConfig }) {
	const slot = parseSlot(useParams()['slot']);
	if (slot === null) return <Navigate to={`/s/${FIRST_SLOT}`} replace />;
	return <SlotPage config={config} slot={slot} />;
}

export function App({ config }: { config: AppConfig }) {
	return (
		<BrowserRouter basename={routerBasename(config)}>
			<Routes>
				<Route path="/" element={<LastSlot config={config} />} />
				<Route path="/s/:slot" element={<SlotRoute config={config} />} />
				<Route path="*" element={<Navigate to={`/s/${FIRST_SLOT}`} replace />} />
			</Routes>
		</BrowserRouter>
	);
}
