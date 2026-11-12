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

/** What the bar says about the connection to the slot's room (S-013). */
import type { ConnectionStatus } from '../collab/session.ts';

/**
 * `Saved` is the server's word: every edit this browser sent is in the slot's
 * head, on the server's disk. `Saving…` is an edit, or the file of an image,
 * that is not there yet.
 */
export function statusLabel(status: ConnectionStatus): string {
	switch (status) {
		case 'connecting':
			return 'Connecting…';
		case 'live':
			return 'Live';
		case 'saving':
			return 'Saving…';
		case 'saved':
			return 'Saved';
		case 'disconnected':
			return 'Disconnected';
	}
}
