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

/** The words of the presence control (S-010). */

/** What a connection without a label is called in the list. */
export const UNNAMED = 'Unnamed';

/** The count is connections, so two tabs of one browser are two. */
export function presenceLabel(count: number): string {
	return count === 1 ? '1 connection on this slot' : `${count} connections on this slot`;
}
