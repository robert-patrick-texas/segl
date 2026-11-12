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

/** This browser's display name, as React state (docs/ARCHITECTURE.md, "Display names"). */
import { useCallback, useEffect, useState } from 'react';
import { allocateDisplayName } from './api.ts';
import { storageKey, type AppConfig } from './config.ts';
import { assignName, readStoredName, retryDelay, titleCaseName, writeStoredName } from './names.ts';
import { browserStorage } from './slots.ts';

export interface DisplayName {
	/** The label, or null until the server has assigned one. */
	name: string | null;
	/**
	 * Replace the label with a name the person typed. Returns the name as
	 * stored, title-cased, or null when it is not 1 to 40 characters.
	 */
	rename(text: string): string | null;
}

/**
 * The stored label, or one the server assigns when none is stored. The label
 * is kept under `segl:{basePath}:displayName`, so the server is asked once
 * for a browser, not once for a page. T06 sends this label on the socket and
 * does not ask again.
 */
export function useDisplayName(config: AppConfig): DisplayName {
	const key = storageKey(config, 'displayName');
	const [name, setName] = useState(() => readStoredName(browserStorage(), key));

	useEffect(() => {
		if (name !== null) return;
		let stopped = false;
		let timer: ReturnType<typeof setTimeout> | undefined;
		const ask = () => {
			assignName(browserStorage(), key, () => allocateDisplayName(config)).then(
				(assigned) => {
					// A name typed while the request was out stays: typing one
					// ends this effect, and `stopped` drops the late answer.
					if (!stopped) setName(assigned);
				},
				(error: unknown) => {
					// Refused for asking too often, or the server is away. The
					// page works without a label, and asks again later.
					if (!stopped) timer = setTimeout(ask, retryDelay(error));
				}
			);
		};
		ask();
		return () => {
			stopped = true;
			clearTimeout(timer);
		};
	}, [config, key, name]);

	// Another tab of this browser stored a label: show the same one here.
	useEffect(() => {
		const onStorage = (event: StorageEvent) => {
			if (event.key !== key) return;
			const stored = readStoredName(browserStorage(), key);
			if (stored !== null) setName(stored);
		};
		window.addEventListener('storage', onStorage);
		return () => window.removeEventListener('storage', onStorage);
	}, [key]);

	const rename = useCallback(
		(text: string) => {
			const typed = titleCaseName(text);
			if (typed === null) return null;
			writeStoredName(browserStorage(), key, typed);
			setName(typed);
			return typed;
		},
		[key]
	);

	return { name, rename };
}
