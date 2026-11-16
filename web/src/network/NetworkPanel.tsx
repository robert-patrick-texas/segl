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
 * segl's panel for one selected network object (D2-038): its kind, its name,
 * and its state, which it sets, and a link's kind. The name is the label on
 * the canvas, and is edited there.
 */
import { KIND_NAMES, LINK_KINDS, STATE_NAMES, STATES, type LinkKind, type State } from './kinds.ts';
import './network.css';
import type { NetworkObject } from './selection.ts';

export interface NetworkPanelProps {
	object: NetworkObject;
	onState(state: State): void;
	onKind(kind: LinkKind): void;
}

export function NetworkPanel({ object, onState, onKind }: NetworkPanelProps) {
	return (
		<section className="segl-network" aria-label="Network object">
			<p className="segl-network__what">
				<span className="segl-network__kind">{KIND_NAMES[object.objectType]}</span>
				{object.name !== '' && <span className="segl-network__name">{object.name}</span>}
			</p>
			<div className="segl-network__states" role="group" aria-label="State">
				{STATES.map((state) => (
					<button
						key={state}
						type="button"
						aria-pressed={state === object.state}
						onClick={() => onState(state)}
					>
						{STATE_NAMES[state]}
					</button>
				))}
			</div>
			{object.kind === 'link' && (
				<label className="segl-network__link">
					Kind
					<select
						value={object.objectType}
						onChange={(event) => onKind(event.target.value as LinkKind)}
					>
						{LINK_KINDS.map((kind) => (
							<option key={kind} value={kind}>
								{KIND_NAMES[kind]}
							</option>
						))}
					</select>
				</label>
			)}
		</section>
	);
}
