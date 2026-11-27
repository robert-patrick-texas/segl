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
 * At most one message in a given time, for what changes faster than it is
 * worth sending: a cursor, or a view (T18). The first goes at once. One that
 * comes within the time waits, and only the newest of those goes, when the
 * time is up, so the last one sent is always the last one given.
 */
type Timer = ReturnType<typeof setTimeout>;

export class Throttle<T> {
	private readonly interval: number;
	private readonly deliver: (value: T) => void;
	private timer: Timer | undefined;
	private waiting: { value: T } | null = null;

	constructor(interval: number, deliver: (value: T) => void) {
		this.interval = interval;
		this.deliver = deliver;
	}

	/** Send this, now or when the time since the last one is up. */
	push(value: T): void {
		this.waiting = { value };
		if (this.timer === undefined) this.flush();
	}

	/**
	 * Start afresh: what waits is never sent, since only the timer sends it,
	 * and the next one goes at once.
	 */
	cancel(): void {
		clearTimeout(this.timer);
		this.timer = undefined;
	}

	private flush(): void {
		if (this.waiting === null) return;
		const { value } = this.waiting;
		this.waiting = null;
		this.deliver(value);
		this.timer = setTimeout(() => {
			this.timer = undefined;
			this.flush();
		}, this.interval);
	}
}
