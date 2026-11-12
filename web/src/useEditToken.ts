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

/** This browser's edit token, as React state (docs/ARCHITECTURE.md, "Edit gate"). */
import { useCallback, useEffect, useRef, useState } from 'react';
import { storageKey, type AppConfig } from './config.ts';
import {
	afterAnswer,
	afterLink,
	afterStorage,
	readEditToken,
	startingToken,
	takeEditLink,
	writeEditToken,
	type TokenState
} from './editToken.ts';
import { browserStorage } from './slots.ts';

export interface EditToken {
	/** What this page sends, in `hello` and in the header. `''` for none. */
	token: string;
	/** The server answered a `hello` that carried `sent`. */
	answered(sent: string, viewOnly: boolean): void;
}

/**
 * The token of the link this page was opened by, `link`, or the one stored
 * under `segl:{basePath}:editToken`. A link's token is stored once the server
 * has taken it (`editToken.ts`). The token belongs to the browser, not to a
 * slot, so this lives above the routes.
 */
export function useEditToken(config: AppConfig, link: string | null): EditToken {
	const key = storageKey(config, 'editToken');
	const [state, setState] = useState(() =>
		startingToken(link, readEditToken(browserStorage(), key))
	);
	// The state as the handlers below last left it: an answer may come before
	// React has rendered the link that it is the answer to.
	const latest = useRef(state);
	const move = useCallback((next: TokenState) => {
		latest.current = next;
		setState(next);
	}, []);

	// A link pasted into this tab while the page is open changes the fragment
	// and loads nothing.
	useEffect(() => {
		const onHashChange = () => {
			const taken = takeEditLink(window);
			if (taken !== null) move(afterLink(latest.current, taken));
		};
		window.addEventListener('hashchange', onHashChange);
		return () => window.removeEventListener('hashchange', onHashChange);
	}, [move]);

	// Another tab of this browser stored a token: this one may edit too. A
	// null key is the whole storage cleared.
	useEffect(() => {
		const onStorage = (event: StorageEvent) => {
			if (event.key !== null && event.key !== key) return;
			move(afterStorage(latest.current, readEditToken(browserStorage(), key)));
		};
		window.addEventListener('storage', onStorage);
		return () => window.removeEventListener('storage', onStorage);
	}, [key, move]);

	const answered = useCallback(
		(sent: string, viewOnly: boolean) => {
			const storage = browserStorage();
			const { state: next, store } = afterAnswer(
				latest.current,
				sent,
				viewOnly,
				readEditToken(storage, key)
			);
			if (store !== null) writeEditToken(storage, key, store);
			if (next !== latest.current) move(next);
		},
		[key, move]
	);

	return { token: state.token, answered };
}
