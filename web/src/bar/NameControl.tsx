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
 * This browser's display name in the segl bar: a button that shows the label
 * and, when pressed, a field to type another (S-009). Enter or leaving the
 * field keeps the new name, title-cased. Escape keeps the old one.
 */
import { useEffect, useId, useRef, useState, type FormEvent } from 'react';

export interface NameControlProps {
	/** The label, or null while the server has not assigned one. */
	name: string | null;
	/** Store a typed name. Returns it as stored, or null when it is not usable. */
	onRename: (text: string) => string | null;
}

export function NameControl({ name, onRename }: NameControlProps) {
	const [editing, setEditing] = useState(false);
	const [text, setText] = useState('');
	const [invalid, setInvalid] = useState(false);
	const button = useRef<HTMLButtonElement>(null);
	// Enter and Escape hand the focus back to the button. Leaving the field
	// for something else does not take it back.
	const refocus = useRef(false);
	const hint = useId();

	useEffect(() => {
		if (!editing && refocus.current) {
			refocus.current = false;
			button.current?.focus();
		}
	}, [editing]);

	if (!editing) {
		return (
			<button
				ref={button}
				type="button"
				className="segl-bar__name"
				title="Change your name"
				aria-label={name === null ? 'Set your name' : `Your name: ${name}. Change it`}
				onClick={() => {
					setText(name ?? '');
					setInvalid(false);
					setEditing(true);
				}}
			>
				{name ?? 'Set your name'}
			</button>
		);
	}

	// Text that was not changed is not a rename: a label from the server's
	// word file, such as McKinley7, keeps its spelling.
	const keep = () => text === (name ?? '') || onRename(text) !== null;

	const submit = (event: FormEvent) => {
		event.preventDefault();
		if (keep()) {
			refocus.current = true;
			setEditing(false);
		} else {
			setInvalid(true);
		}
	};

	return (
		<form className="segl-bar__name-form" onSubmit={submit}>
			<input
				className="segl-bar__name-input"
				name="displayName"
				aria-label="Your name"
				autoComplete="off"
				autoFocus
				value={text}
				aria-invalid={invalid || undefined}
				aria-describedby={invalid ? hint : undefined}
				onFocus={(event) => event.target.select()}
				onChange={(event) => {
					setText(event.target.value);
					setInvalid(false);
				}}
				onKeyDown={(event) => {
					if (event.key !== 'Escape') return;
					refocus.current = true;
					setEditing(false);
				}}
				onBlur={() => {
					// Closing on Enter or Escape may blur the field as it goes.
					if (refocus.current) return;
					// A name that is not usable is dropped, and the old one stays.
					keep();
					setEditing(false);
				}}
			/>
			{invalid && (
				<span id={hint} className="segl-bar__name-hint" role="alert">
					1 to 40 characters
				</span>
			)}
		</form>
	);
}
