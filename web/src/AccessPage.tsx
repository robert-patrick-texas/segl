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
 * The access page, `access` under segl's root (docs/ARCHITECTURE.md, "Edit
 * gate"; D2-033). A person enters an access code. A right one buys a pass,
 * which this browser keeps, and the page goes back to the slot the person
 * came from, where the browser now edits.
 *
 * It is not a login: it takes a code, knows no user, and keeps no account.
 * Looking needs no code, and the page says so.
 */
import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react';
import { Link, useLocation, useNavigate } from 'react-router';
import { isTyped, outcomeWords, refusalOutcome, returnSlot, type Outcome } from './access.ts';
import './access.css';
import { requestPass } from './api.ts';
import { storageKey, type AppConfig } from './config.ts';
import { browserStorage, readLastSlot } from './slots.ts';

export interface AccessPageProps {
	config: AppConfig;
	/** Keep the pass a right code bought. */
	onPass: (pass: string) => void;
}

export function AccessPage({ config, onPass }: AccessPageProps) {
	const location = useLocation();
	const navigate = useNavigate();
	const slot = returnSlot(
		location.state,
		readLastSlot(browserStorage(), storageKey(config, 'lastSlot'))
	);
	const back = `/s/${slot}`;
	const [code, setCode] = useState('');
	const [asking, setAsking] = useState(false);
	const [outcome, setOutcome] = useState<Outcome | null>(null);
	const field = useRef<HTMLInputElement>(null);
	const request = useRef<AbortController | null>(null);

	useEffect(() => {
		document.title = 'Access code · segl';
		field.current?.focus();
		// A page that is left takes no answer.
		return () => request.current?.abort();
	}, []);

	const submit = useCallback(
		async (event: FormEvent) => {
			event.preventDefault();
			if (asking || !isTyped(code)) return;
			const abort = new AbortController();
			request.current = abort;
			setAsking(true);
			setOutcome(null);
			let result: Outcome;
			try {
				result = { kind: 'pass', pass: await requestPass(config, code, abort.signal) };
			} catch (error) {
				if (abort.signal.aborted) return;
				result = refusalOutcome(error);
			}
			if (result.kind === 'pass') {
				// Stored first, so the slot says `hello` with it.
				onPass(result.pass);
				navigate(back, { replace: true });
				return;
			}
			setAsking(false);
			setOutcome(result);
			// A code that was refused is not left in the field to be read.
			if (result.kind === 'wrong') setCode('');
			field.current?.focus();
		},
		[asking, back, code, config, navigate, onPass]
	);

	const words = outcome === null ? '' : outcomeWords(outcome);
	// A segl without codes has nothing to enter: the field goes, and the way back stays.
	const open = outcome?.kind === 'open' || !config.editRequired;

	return (
		<main className="segl-access">
			<form className="segl-access__form" onSubmit={submit} aria-labelledby="segl-access-title">
				<p className="segl-access__brand">segl</p>
				<h1 id="segl-access-title" className="segl-access__title">
					Access code
				</h1>
				{open ? (
					<p className="segl-access__note" role="status">
						{outcomeWords({ kind: 'open' })}
					</p>
				) : (
					<>
						<p className="segl-access__note">
							Enter an access code to edit on this segl. Looking needs none.
						</p>
						<label className="segl-access__label" htmlFor="segl-access-code">
							Access code
						</label>
						<input
							ref={field}
							id="segl-access-code"
							className="segl-access__field"
							type="text"
							name="code"
							value={code}
							onChange={(event) => setCode(event.target.value)}
							// A code is shared, and is not this person's password.
							autoComplete="off"
							autoCapitalize="none"
							autoCorrect="off"
							spellCheck={false}
							maxLength={256}
							aria-describedby="segl-access-answer"
							aria-invalid={outcome?.kind === 'wrong'}
						/>
						<button
							type="submit"
							className="segl-access__enter"
							disabled={asking || !isTyped(code)}
						>
							{asking ? 'Asking…' : 'Enter'}
						</button>
						<p
							id="segl-access-answer"
							className="segl-access__answer"
							role="alert"
							data-outcome={outcome?.kind ?? ''}
						>
							{words}
						</p>
					</>
				)}
				<Link className="segl-access__back" to={back} replace>
					Back to slot {slot}
				</Link>
			</form>
		</main>
	);
}
