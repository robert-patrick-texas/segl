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
 * buttons, the shared title, room for the presence count (T06), and the
 * notice that the workspace is shared (S-016).
 */
import { NavLink } from 'react-router';
import { SLOT_NUMBERS } from '../slots.ts';
import './bar.css';
import { sharedNotice } from './notice.ts';

export interface SeglBarProps {
	slot: number;
	/** Titles by slot number. Empty until the slot list has loaded. */
	titles: ReadonlyMap<number, string>;
	editRequired: boolean;
	version: string;
}

export function SeglBar({ slot, titles, editRequired, version }: SeglBarProps) {
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
			<h1 className="segl-bar__title">{titles.get(slot) ?? ''}</h1>
			{/* The presence count and its list go here in T06. */}
			<div className="segl-bar__presence" data-testid="presence" />
			<p className="segl-bar__notice" role="note">
				{sharedNotice(editRequired)}
			</p>
			<span className="segl-bar__version" title="segl version">
				segl {version}
			</span>
		</header>
	);
}
