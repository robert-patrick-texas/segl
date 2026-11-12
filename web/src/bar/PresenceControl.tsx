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
 * Who is on this slot (S-010). The number is the WebSocket connections the
 * server counts on the slot, this one included, so two tabs of one browser
 * count twice. Pressing it lists their labels.
 */
import { useEffect, useId, useRef, useState } from 'react';
import type { Participant } from '../collab/protocol.ts';
import { presenceLabel, UNNAMED } from './presence.ts';

export interface PresenceControlProps {
	/** Every connection on the slot, in the order they joined. Empty when not live. */
	participants: readonly Participant[];
	/** This browser's own connection, marked in the list. */
	self: string | null;
}

export function PresenceControl({ participants, self }: PresenceControlProps) {
	const [open, setOpen] = useState(false);
	const wrapper = useRef<HTMLDivElement>(null);
	const list = useId();
	const count = participants.length;

	useEffect(() => {
		if (!open) return;
		const onPointerDown = (event: PointerEvent) => {
			if (!wrapper.current?.contains(event.target as Node)) setOpen(false);
		};
		const onKeyDown = (event: KeyboardEvent) => {
			if (event.key === 'Escape') setOpen(false);
		};
		document.addEventListener('pointerdown', onPointerDown);
		document.addEventListener('keydown', onKeyDown);
		return () => {
			document.removeEventListener('pointerdown', onPointerDown);
			document.removeEventListener('keydown', onKeyDown);
		};
	}, [open]);

	return (
		<div ref={wrapper} className="segl-bar__presence" data-testid="presence">
			{/* Nothing while the socket is down: this browser is not on the slot then. */}
			{count > 0 && (
				<button
					type="button"
					className="segl-bar__count"
					aria-label={`${presenceLabel(count)}. Show who`}
					aria-expanded={open}
					aria-controls={open ? list : undefined}
					title={presenceLabel(count)}
					onClick={() => setOpen((shown) => !shown)}
				>
					<span className="segl-bar__count-icon" aria-hidden="true" />
					<span data-testid="presence-count">{count}</span>
				</button>
			)}
			{open && count > 0 && (
				<ul id={list} className="segl-bar__people" aria-label="On this slot">
					{participants.map((person) => (
						<li key={person.connectionId} className="segl-bar__person">
							<span className="segl-bar__person-name">{person.displayName ?? UNNAMED}</span>
							{person.connectionId === self && <span className="segl-bar__person-you">you</span>}
						</li>
					))}
				</ul>
			)}
		</div>
	);
}
