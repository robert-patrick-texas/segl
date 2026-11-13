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
 * JSON import in the segl bar (S-011): choose a file the editor exported, and
 * put its scene in place of this slot's. That replaces the canvas of everyone
 * on the slot, so it takes a second press, as a restore does. The scene that
 * is replaced is kept in the history, and can be restored.
 *
 * The file may also come from the page: one dropped on the canvas is offered
 * here, with the same question. The export is the editor's own, in its menu.
 */
import { useEffect, useId, useRef, useState } from 'react';
import { IMPORT_NEEDS_CONNECTION, IMPORT_NEEDS_CODE, importProblem } from '../importing.ts';
import { useShiftIntoView } from './inView.ts';
import { useDismiss } from './useDismiss.ts';

export interface ImportControlProps {
	/** The file that waits for the second press, or null. The page holds it. */
	file: File | null;
	/** Take a file the person chose here, or let go of the one that waits. */
	onChoose: (file: File | null) => void;
	/** False for a browser that may look and not edit. */
	canImport: boolean;
	/** False while this browser is not in the slot's room, and would not see the import. */
	connected: boolean;
	/** Import the file. Rejects with the reason when it is refused. */
	onImport: (file: File) => Promise<void>;
}

export function ImportControl({
	file,
	onChoose,
	canImport,
	connected,
	onImport
}: ImportControlProps) {
	// Open without a file: only to say why there is nothing to choose.
	const [explaining, setExplaining] = useState(false);
	const [importing, setImporting] = useState(false);
	const [problem, setProblem] = useState<string | null>(null);
	const wrapper = useRef<HTMLDivElement>(null);
	const panelBox = useRef<HTMLDivElement>(null);
	const input = useRef<HTMLInputElement>(null);
	const confirm = useRef<HTMLButtonElement>(null);
	const panel = useId();
	const able = canImport && connected;
	const open = file !== null || explaining;

	const close = () => {
		// The answer to an import that is under way is still to come.
		if (importing) return;
		setExplaining(false);
		setProblem(null);
		if (file !== null) onChoose(null);
	};
	useDismiss(open, wrapper, close);
	const shift = useShiftIntoView(open, wrapper, panelBox);

	// Another file, or none: what was said of the last one no longer holds.
	useEffect(() => setProblem(null), [file]);

	// The answer takes the focus once the panel is in its place. Focused as it
	// appears, where a narrow page has no room for it yet, it would make the
	// browser scroll the page sideways to show it.
	useEffect(() => {
		if (file !== null) confirm.current?.focus({ preventScroll: true });
	}, [file]);

	const press = () => {
		if (open) close();
		else if (able) input.current?.click();
		else setExplaining(true);
	};

	const runImport = async (chosen: File) => {
		setImporting(true);
		setProblem(null);
		try {
			await onImport(chosen);
			// The scene arrives over the socket, as it does for everyone else.
			onChoose(null);
		} catch (error) {
			setProblem(importProblem(error));
		} finally {
			setImporting(false);
		}
	};

	const why = !canImport ? IMPORT_NEEDS_CODE : !connected ? IMPORT_NEEDS_CONNECTION : null;

	return (
		<div ref={wrapper} className="segl-bar__import" data-testid="import">
			<button
				type="button"
				className="segl-bar__import-button"
				aria-expanded={open}
				aria-controls={open ? panel : undefined}
				title="Replace this slot's canvas with an Excalidraw file"
				onClick={press}
			>
				Import
			</button>
			<input
				ref={input}
				type="file"
				className="segl-bar__import-input"
				accept=".excalidraw,.json,application/json"
				aria-label="An Excalidraw file to import"
				tabIndex={-1}
				onChange={(event) => {
					const chosen = event.target.files?.[0] ?? null;
					// Emptied, so that choosing the same file again is a change too.
					event.target.value = '';
					if (chosen !== null) onChoose(chosen);
				}}
			/>
			{open && (
				<div
					ref={panelBox}
					id={panel}
					className="segl-bar__import-panel"
					style={shift === 0 ? undefined : { left: -shift }}
					role="group"
					aria-label="Import a file into this slot"
				>
					{file !== null && (
						<p className="segl-bar__import-file" title={file.name}>
							{file.name}
						</p>
					)}
					{why !== null && <p className="segl-bar__import-note">{why}</p>}
					{file !== null && why === null && (
						<div className="segl-bar__import-confirm">
							<span className="segl-bar__import-question">
								Replace the canvas for everyone? The one there now is kept in History.
							</span>
							<button
								ref={confirm}
								type="button"
								className="segl-bar__import-answer"
								data-kind="confirm"
								disabled={importing}
								onClick={() => void runImport(file)}
							>
								{importing ? 'Importing…' : 'Import it'}
							</button>
							<button
								type="button"
								className="segl-bar__import-answer"
								disabled={importing}
								onClick={close}
							>
								Cancel
							</button>
						</div>
					)}
					{problem !== null && (
						<p className="segl-bar__import-problem" role="alert">
							{problem}
						</p>
					)}
				</div>
			)}
		</div>
	);
}
