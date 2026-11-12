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
 * The slot's title in the segl bar (S-003). Everyone on the slot shares it.
 * A browser that may edit sees it as a button, which opens a field. Enter, or
 * leaving the field, sends the new title to the server, which tells every
 * browser on the slot. Escape keeps the old one.
 */
import { useEffect, useId, useRef, useState, type FormEvent } from 'react';
import { cleanTitle, MAX_TITLE_LENGTH } from '../titles.ts';

export interface TitleControlProps {
	/** The title, or `''` until the slot list has loaded. */
	title: string;
	/** False for a browser that may look and not edit. */
	editable: boolean;
	/** Store the title on the server. Rejects with the reason when it is refused. */
	onRetitle: (title: string) => Promise<void>;
}

const LENGTH_HINT = `1 to ${MAX_TITLE_LENGTH} characters`;

export function TitleControl({ title, editable, onRetitle }: TitleControlProps) {
	const [editing, setEditing] = useState(false);
	const [text, setText] = useState('');
	const [problem, setProblem] = useState<string | null>(null);
	const [saving, setSaving] = useState(false);
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

	if (!editing || !editable) {
		return (
			<h1 className="segl-bar__title">
				{editable && title !== '' ? (
					<button
						ref={button}
						type="button"
						className="segl-bar__title-button"
						title="Change the title"
						onClick={() => {
							setText(title);
							setProblem(null);
							setEditing(true);
						}}
					>
						{title}
					</button>
				) : (
					title
				)}
			</h1>
		);
	}

	/** Send the typed title. Returns whether the field can close. */
	const save = async (): Promise<boolean> => {
		const typed = cleanTitle(text);
		if (typed === null) {
			setProblem(LENGTH_HINT);
			return false;
		}
		if (typed === title) return true;
		setSaving(true);
		try {
			await onRetitle(typed);
			return true;
		} catch (error) {
			setProblem(error instanceof Error ? error.message : 'segl could not save the title');
			return false;
		} finally {
			setSaving(false);
		}
	};

	const submit = (event: FormEvent) => {
		event.preventDefault();
		void save().then((saved) => {
			if (!saved) return;
			refocus.current = true;
			setEditing(false);
		});
	};

	return (
		<form className="segl-bar__title-form" onSubmit={submit}>
			<input
				className="segl-bar__title-input"
				name="title"
				aria-label="Slot title"
				autoComplete="off"
				autoFocus
				value={text}
				disabled={saving}
				aria-invalid={problem !== null || undefined}
				aria-describedby={problem !== null ? hint : undefined}
				onFocus={(event) => event.target.select()}
				onChange={(event) => {
					setText(event.target.value);
					setProblem(null);
				}}
				onKeyDown={(event) => {
					if (event.key !== 'Escape') return;
					refocus.current = true;
					setEditing(false);
				}}
				onBlur={() => {
					// Closing on Enter or Escape may blur the field as it goes, and
					// so does disabling it while the title is being saved.
					if (refocus.current || saving) return;
					// A title that cannot be saved is dropped, and the old one stays.
					void save().finally(() => setEditing(false));
				}}
			/>
			{problem !== null && (
				<span id={hint} className="segl-bar__title-hint" role="alert">
					{problem}
				</span>
			)}
		</form>
	);
}
