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
 * Follow mode, this browser as the one followed (T18, D2-041). The server
 * says how many follow this connection. Only while someone does is the view
 * sent: at once when one more starts, and then as it changes, at most five
 * times a second. The server sends it to the followers alone.
 */
import type { View } from './protocol.ts';
import { Throttle } from './throttle.ts';

/** At most one `view` in this time. */
export const VIEW_INTERVAL_MS = 200;

/** How long the bar says why a follow did not start (T19). */
export const REFUSED_FOLLOW_MS = 5000;

type Timer = ReturnType<typeof setTimeout>;

/**
 * A follow the server refused with `cannot_follow`, which the bar says for a
 * few seconds. `show` takes true when it starts, and false when it ends.
 */
export class Refusal {
	private readonly show: (shown: boolean) => void;
	private timer: Timer | undefined;

	constructor(show: (shown: boolean) => void) {
		this.show = show;
	}

	/** Say it, for the whole time again if it is being said. */
	refused(): void {
		clearTimeout(this.timer);
		this.show(true);
		this.timer = setTimeout(() => {
			this.timer = undefined;
			this.show(false);
		}, REFUSED_FOLLOW_MS);
	}

	/** The session stops: nothing more is said. */
	stop(): void {
		clearTimeout(this.timer);
		this.timer = undefined;
	}
}

/** Whether two views show the same area of the same page. */
export function sameView(a: View, b: View): boolean {
	return (
		a.x === b.x &&
		a.y === b.y &&
		a.width === b.width &&
		a.height === b.height &&
		(a.page ?? null) === (b.page ?? null)
	);
}

export class Leading {
	private count = 0;
	private latest: View | null = null;
	private readonly throttle: Throttle<View>;

	/** `send` puts one view on the socket. */
	constructor(send: (view: View) => void) {
		this.throttle = new Throttle(VIEW_INTERVAL_MS, send);
	}

	/** How many follow this connection now. A new one is sent the view at once. */
	followers(count: number): void {
		const more = count > this.count;
		this.count = count;
		if (count === 0) this.throttle.cancel();
		else if (more && this.latest !== null) this.throttle.push(this.latest);
	}

	/** What this browser shows changed, or may have. */
	view(view: View): void {
		if (this.latest !== null && sameView(this.latest, view)) return;
		this.latest = view;
		if (this.count > 0) this.throttle.push(view);
	}

	/** The connection went. A new one starts with nobody following it. */
	reset(): void {
		this.count = 0;
		this.throttle.cancel();
	}
}
