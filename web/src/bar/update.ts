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
 * The update notice (T19). A page left open across `segl update` runs its
 * old code until it reloads, so the bar says so when the server's version,
 * from `welcome`, is not the one the page was built with. The page never
 * reloads by itself: a person may be typing.
 */

/** What the bar says when the server runs another version. */
export const UPDATED = 'segl updated';

/** The button that loads the page again. */
export const RELOAD = 'Reload';

/**
 * Whether the server runs another version than the page's. A server that
 * named none, an older segl, is not taken for another.
 */
export function isUpdated(server: string | null, built: string): boolean {
	return server !== null && server !== built;
}
