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
 * The segl bar. It sits above the canvas, outside it, and holds the slot
 * buttons, the shared title (S-003), who is on the slot (S-010), the state of
 * the connection (S-013), the slot's history (S-005), JSON import (S-011),
 * this browser's display name (S-009), and the notice that the workspace is
 * shared (S-016).
 */
import { NavLink } from 'react-router';
import type { Participant } from '../collab/protocol.ts';
import type { ConnectionStatus } from '../collab/session.ts';
import type { RevisionInfo } from '../history.ts';
import { SLOT_NUMBERS } from '../slots.ts';
import './bar.css';
import { HistoryControl } from './HistoryControl.tsx';
import { ImportControl } from './ImportControl.tsx';
import { NameControl } from './NameControl.tsx';
import { sharedNotice } from './notice.ts';
import { PresenceControl } from './PresenceControl.tsx';
import { statusLabel } from './status.ts';
import { TitleControl } from './TitleControl.tsx';

export interface SeglBarProps {
	slot: number;
	/** Titles by slot number. Empty until the slot list has loaded. */
	titles: ReadonlyMap<number, string>;
	editRequired: boolean;
	version: string;
	/** This browser's display name, or null until the server has assigned one. */
	displayName: string | null;
	/** Store a name the person typed. Returns it as stored, or null when it is not usable. */
	onRename: (text: string) => string | null;
	/** The connection to the slot's room. */
	status: ConnectionStatus;
	/** Every connection on the slot, this one included. Empty when not live. */
	participants: readonly Participant[];
	/** This browser's own connection. */
	self: string | null;
	/** False for a browser that may look and not edit. */
	canEdit: boolean;
	/** Store a new title for this slot on the server. */
	onRetitle: (title: string) => Promise<void>;
	/** The epoch of the scene on the canvas, or null until the server has sent it. */
	epoch: number | null;
	/** Read this slot's revisions from the server, newest first. */
	onLoadHistory: (signal: AbortSignal) => Promise<RevisionInfo[]>;
	/** Put one of this slot's revisions in place of its scene, for everyone. */
	onRestore: (revision: number) => Promise<void>;
	/** The exported file that waits to be imported, or null. */
	importFile: File | null;
	/** Take a file to import, or let go of the one that waits. */
	onChooseImport: (file: File | null) => void;
	/** Put the scene of an exported file in place of this slot's, for everyone. */
	onImport: (file: File) => Promise<void>;
}

export function SeglBar({
	slot,
	titles,
	editRequired,
	version,
	displayName,
	onRename,
	status,
	participants,
	self,
	canEdit,
	onRetitle,
	epoch,
	onLoadHistory,
	onRestore,
	importFile,
	onChooseImport,
	onImport
}: SeglBarProps) {
	// In the slot's room: a restore or an import reaches this canvas over the socket.
	const connected = status === 'live' || status === 'saving' || status === 'saved';
	return (
		<header className="segl-bar">
			<span className="segl-bar__brand">segl</span>
			<nav className="segl-bar__slots" aria-label="Slots">
				{SLOT_NUMBERS.map((number) => {
					const title = titles.get(number) ?? `Slot ${number}`;
					return (
						<NavLink
							key={number}
							to={`/s/${number}`}
							className="segl-bar__slot"
							title={title}
							aria-label={`Slot ${number}: ${title}`}
						>
							{number}
						</NavLink>
					);
				})}
			</nav>
			{/* Keyed by the slot, so a field left open does not follow to the next one. */}
			<TitleControl
				key={slot}
				title={titles.get(slot) ?? ''}
				editable={canEdit}
				onRetitle={onRetitle}
			/>
			<PresenceControl key={`people-${slot}`} participants={participants} self={self} />
			<span className="segl-bar__status" data-state={status} role="status">
				{statusLabel(status)}
			</span>
			{/* Keyed by the slot too: an open list is of the slot it was opened on. */}
			<HistoryControl
				key={`history-${slot}`}
				epoch={epoch}
				canRestore={canEdit}
				connected={connected}
				onLoad={onLoadHistory}
				onRestore={onRestore}
			/>
			<ImportControl
				key={`import-${slot}`}
				file={importFile}
				onChoose={onChooseImport}
				canImport={canEdit}
				connected={connected}
				onImport={onImport}
			/>
			<div className="segl-bar__you">
				{/* The button's own label says the same to a screen reader. */}
				<span aria-hidden="true">You:</span>
				<NameControl name={displayName} onRename={onRename} />
			</div>
			<p className="segl-bar__notice" role="note">
				{sharedNotice(editRequired)}
			</p>
			<span className="segl-bar__version" title="segl version">
				segl {version}
			</span>
		</header>
	);
}
