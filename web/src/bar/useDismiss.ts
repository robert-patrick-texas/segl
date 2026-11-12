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

/** How a list that drops down from the bar is closed without choosing from it. */
import { useEffect, useRef, type RefObject } from 'react';

/**
 * While `open`, call `close` when the person presses Escape, or presses
 * anywhere outside `wrapper`: on the rest of the bar, or on the canvas.
 */
export function useDismiss(
	open: boolean,
	wrapper: RefObject<HTMLElement | null>,
	close: () => void
): void {
	// The newest `close`, so that the listeners are not added again at every render.
	const latest = useRef(close);
	useEffect(() => {
		latest.current = close;
	});

	useEffect(() => {
		if (!open) return;
		const onPointerDown = (event: PointerEvent) => {
			if (!wrapper.current?.contains(event.target as Node)) latest.current();
		};
		const onKeyDown = (event: KeyboardEvent) => {
			if (event.key === 'Escape') latest.current();
		};
		// On the way down: the canvas may keep a press to itself.
		document.addEventListener('pointerdown', onPointerDown, true);
		document.addEventListener('keydown', onKeyDown);
		return () => {
			document.removeEventListener('pointerdown', onPointerDown, true);
			document.removeEventListener('keydown', onKeyDown);
		};
	}, [open, wrapper]);
}
