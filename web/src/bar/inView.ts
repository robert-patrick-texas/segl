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
 * Keeping a panel that drops down from the bar inside the page. It hangs
 * from the left edge of its button. Where the button is too far right for
 * that, on a narrow screen or after a long title, the panel moves left by as
 * much as it has to, so the page never gains a sideways scroll.
 */
import { useLayoutEffect, useState, type RefObject } from 'react';

/** The least room between a panel and the edge of the page, in pixels. */
export const EDGE_MARGIN = 12;

/**
 * Return how far left a panel has to move from under its button to end
 * `margin` short of the page's right edge. `left` is the button's left edge,
 * and all four are pixels. It never moves past the left margin: a panel wider
 * than the page starts there and is cut off on the right.
 */
export function shiftIntoView(
	left: number,
	width: number,
	viewport: number,
	margin = EDGE_MARGIN
): number {
	const over = left + width + margin - viewport;
	return Math.max(0, Math.min(over, left - margin));
}

/**
 * While `open`, return the pixels `panel` has to move left of `anchor`, the
 * element it hangs from, and work it out again when the window is resized.
 * The caller sets it as the panel's `left`, negated.
 */
export function useShiftIntoView(
	open: boolean,
	anchor: RefObject<HTMLElement | null>,
	panel: RefObject<HTMLElement | null>
): number {
	const [shift, setShift] = useState(0);

	// Before the browser paints, so the panel is never seen out of place.
	useLayoutEffect(() => {
		if (!open) return;
		const place = () => {
			const from = anchor.current?.getBoundingClientRect();
			const width = panel.current?.offsetWidth;
			if (from === undefined || width === undefined) return;
			setShift(shiftIntoView(from.left, width, document.documentElement.clientWidth));
		};
		place();
		window.addEventListener('resize', place);
		return () => window.removeEventListener('resize', place);
	}, [open, anchor, panel]);

	return open ? shift : 0;
}
