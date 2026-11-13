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

/** This browser's pass, as React state (docs/ARCHITECTURE.md, "Edit gate"). */
import { useCallback, useEffect, useState } from 'react';
import { storageKey, type AppConfig } from './config.ts';
import { readPass, writePass } from './pass.ts';
import { browserStorage } from './slots.ts';

export interface Pass {
	/** What this page sends, in `hello` and in the header. `''` for none. */
	pass: string;
	/** Keep a pass the server has just issued, for this page and for the browser. */
	store(pass: string): void;
}

/**
 * The pass stored under `segl:{basePath}:editToken`, a key named from when
 * it held a token. The pass belongs to the browser, not to a slot, so this
 * lives above the routes: the access page stores one, and the slot the person
 * goes back to says `hello` with it.
 */
export function usePass(config: AppConfig): Pass {
	const key = storageKey(config, 'editToken');
	const [pass, setPass] = useState(() => readPass(browserStorage(), key));

	// Another tab of this browser stored a pass: this one may edit too. A
	// null key is the whole storage cleared.
	useEffect(() => {
		const onStorage = (event: StorageEvent) => {
			if (event.key !== null && event.key !== key) return;
			setPass(readPass(browserStorage(), key));
		};
		window.addEventListener('storage', onStorage);
		return () => window.removeEventListener('storage', onStorage);
	}, [key]);

	const store = useCallback(
		(issued: string) => {
			writePass(browserStorage(), key, issued);
			setPass(issued);
		},
		[key]
	);

	return { pass, store };
}
