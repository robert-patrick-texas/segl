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

/** A slot's title, as a person types it (docs/API.md, `PATCH /api/v1/slots/{n}`). */

/** The longest title, in characters. The server has the same limit. */
export const MAX_TITLE_LENGTH = 80;

/**
 * Return a typed title without the spaces around it, or null when it is not
 * 1 to 80 characters. The server checks again, and its answer is the one
 * that counts: it also refuses a title with a line break in it.
 */
export function cleanTitle(text: string): string | null {
	const title = text.trim();
	// Characters, not UTF-16 units: the server counts code points.
	const length = Array.from(title).length;
	return length >= 1 && length <= MAX_TITLE_LENGTH ? title : null;
}
