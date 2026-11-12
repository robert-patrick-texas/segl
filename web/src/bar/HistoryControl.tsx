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
 * The slot's history in the segl bar (S-005): the revisions the server
 * keeps, newest first, and a way to put one back. A restore replaces the
 * canvas of everyone on the slot, so it takes two presses. The scene that is
 * replaced is kept as a revision itself, and can be restored in its turn.
 *
 * A browser that may look and not edit sees the list without the buttons.
 */
import { useEffect, useId, useRef, useState } from 'react';
import {
	historyRows,
	NEEDS_CONNECTION,
	NEEDS_TOKEN,
	restoreProblem,
	whenLabel,
	type HistoryRow,
	type RevisionInfo
} from '../history.ts';
import { useShiftIntoView } from './inView.ts';
import { useDismiss } from './useDismiss.ts';

export interface HistoryControlProps {
	/**
	 * The epoch of the scene on the canvas. A restore, by anyone on the slot,
	 * moves it on, and an open list is read again.
	 */
	epoch: number | null;
	/** False for a browser that may look and not edit. */
	canRestore: boolean;
	/** False while this browser is not in the slot's room, and would not see a restore. */
	connected: boolean;
	/** Read the slot's revisions from the server, newest first. */
	onLoad: (signal: AbortSignal) => Promise<RevisionInfo[]>;
	/** Restore a revision. Rejects with the reason when it is refused. */
	onRestore: (revision: number) => Promise<void>;
}

type List =
	| { state: 'loading' }
	| { state: 'ready'; rows: HistoryRow[] }
	| { state: 'failed'; message: string };

export function HistoryControl({
	epoch,
	canRestore,
	connected,
	onLoad,
	onRestore
}: HistoryControlProps) {
	const [open, setOpen] = useState(false);
	const [list, setList] = useState<List>({ state: 'loading' });
	// The row whose restore is waiting for the second press.
	const [chosen, setChosen] = useState<number | null>(null);
	const [restoring, setRestoring] = useState(false);
	const [problem, setProblem] = useState<string | null>(null);
	// Counted up to read the list again.
	const [reads, setReads] = useState(0);
	const wrapper = useRef<HTMLDivElement>(null);
	const panelBox = useRef<HTMLDivElement>(null);
	const panel = useId();

	useDismiss(open, wrapper, () => setOpen(false));
	// Under the button where there is room, and further left where there is not.
	const shift = useShiftIntoView(open, wrapper, panelBox);

	useEffect(() => {
		if (!open) return;
		const abort = new AbortController();
		onLoad(abort.signal).then(
			(revisions) => {
				if (!abort.signal.aborted) setList({ state: 'ready', rows: historyRows(revisions) });
			},
			(error: unknown) => {
				if (abort.signal.aborted) return;
				const message = error instanceof Error ? error.message : String(error);
				setList({ state: 'failed', message });
			}
		);
		return () => abort.abort();
	}, [open, epoch, reads, onLoad]);

	const toggle = () => {
		// Each opening starts from the server's list, not from the last one shown.
		if (!open) {
			setList({ state: 'loading' });
			setChosen(null);
			setProblem(null);
		}
		setOpen(!open);
	};

	const restore = async (revision: number) => {
		setRestoring(true);
		setProblem(null);
		try {
			await onRestore(revision);
			setChosen(null);
		} catch (error) {
			setProblem(restoreProblem(error));
		} finally {
			setRestoring(false);
			// Either way the list has changed, or was older than it looked.
			setReads((count) => count + 1);
		}
	};

	const rows = list.state === 'ready' ? list.rows : [];
	const now = new Date();

	return (
		<div ref={wrapper} className="segl-bar__history" data-testid="history">
			<button
				type="button"
				className="segl-bar__history-button"
				aria-expanded={open}
				aria-controls={open ? panel : undefined}
				title="Earlier versions of this slot"
				onClick={toggle}
			>
				History
			</button>
			{open && (
				<div
					ref={panelBox}
					id={panel}
					className="segl-bar__history-panel"
					style={shift === 0 ? undefined : { left: -shift }}
					role="group"
					aria-label="History of this slot"
					data-state={list.state}
				>
					{list.state === 'loading' && <p className="segl-bar__history-note">Loading…</p>}
					{list.state === 'failed' && (
						<p className="segl-bar__history-problem" role="alert">
							segl could not read the history: {list.message}
						</p>
					)}
					{list.state === 'ready' && rows.length === 0 && (
						<p className="segl-bar__history-note">
							No versions yet. segl keeps one as people draw.
						</p>
					)}
					{rows.length > 0 && (
						<ol className="segl-bar__history-list">
							{rows.map((row) => {
								const when = whenLabel(row.createdAt, now);
								return (
									<li
										key={row.revision}
										className="segl-bar__revision"
										data-revision={row.revision}
										data-epoch={row.epoch}
									>
										<span className="segl-bar__revision-what">
											<time dateTime={row.createdAt} title={row.createdAt}>
												{when}
											</time>
											<span className="segl-bar__revision-who">{row.authorLabel}</span>
											{row.replacement && (
												<span
													className="segl-bar__revision-tag"
													title="A restore or an import put the whole canvas in place here"
												>
													replacement
												</span>
											)}
										</span>
										{canRestore && chosen !== row.revision && (
											<button
												type="button"
												className="segl-bar__revision-button"
												aria-label={`Restore the version of ${when} by ${row.authorLabel}`}
												disabled={restoring || !connected}
												onClick={() => {
													setChosen(row.revision);
													setProblem(null);
												}}
											>
												Restore
											</button>
										)}
										{canRestore && chosen === row.revision && (
											<span className="segl-bar__revision-confirm">
												<span className="segl-bar__revision-question">
													Replace the canvas for everyone?
												</span>
												<button
													type="button"
													className="segl-bar__revision-button"
													data-kind="confirm"
													autoFocus
													disabled={restoring || !connected}
													onClick={() => void restore(row.revision)}
												>
													Restore it
												</button>
												<button
													type="button"
													className="segl-bar__revision-button"
													disabled={restoring}
													onClick={() => setChosen(null)}
												>
													Cancel
												</button>
											</span>
										)}
									</li>
								);
							})}
						</ol>
					)}
					{rows.length > 0 && !canRestore && (
						<p className="segl-bar__history-note">{NEEDS_TOKEN}</p>
					)}
					{rows.length > 0 && canRestore && !connected && (
						<p className="segl-bar__history-note">{NEEDS_CONNECTION}</p>
					)}
					{problem !== null && (
						<p className="segl-bar__history-problem" role="alert">
							{problem}
						</p>
					)}
				</div>
			)}
		</div>
	);
}
