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
 * Diagram mode's part of the bar: the mode, who holds the pen, and the
 * button that takes it or gives it back (D2-040). Anyone who may edit can
 * take the pen, even from its holder.
 */
import { penLabel } from './pen.ts';

export interface PenControlProps {
	/** Who holds the pen: their display name, or null when it is free. */
	holder: string | null;
	/** This browser holds it. */
	mine: boolean;
	/** This browser may edit, and is connected. */
	canTake: boolean;
	onPen: (take: boolean) => void;
}

export function PenControl({ holder, mine, canTake, onPen }: PenControlProps) {
	return (
		<>
			<span className="segl-bar__mode">Diagram mode</span>
			<span
				className="segl-bar__pen"
				role="status"
				data-pen={mine ? 'mine' : holder === null ? 'free' : 'held'}
			>
				{penLabel(holder, mine)}
				{mine && (
					<button type="button" className="segl-bar__pen-button" onClick={() => onPen(false)}>
						Give pen back
					</button>
				)}
				{!mine && canTake && (
					<button type="button" className="segl-bar__pen-button" onClick={() => onPen(true)}>
						Take pen
					</button>
				)}
			</span>
		</>
	);
}
