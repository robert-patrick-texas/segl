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
 * The application version for the build, from versions.toml, the only version
 * list (D2-020). Node has no TOML reader, and the build needs one line, so
 * this reads `version` from the `[project]` table and nothing else.
 */
import { readFileSync } from 'node:fs';

/** Return `project.version` from the text of versions.toml. */
export function projectVersion(toml: string): string {
	let table = '';
	for (const raw of toml.split('\n')) {
		const line = raw.trim();
		const header = /^\[([^\]]+)\]$/.exec(line);
		if (header) {
			table = header[1]!.trim();
			continue;
		}
		const entry = table === 'project' ? /^version\s*=\s*"([^"]+)"\s*(?:#.*)?$/.exec(line) : null;
		if (entry) return entry[1]!;
	}
	throw new Error('versions.toml has no version in its [project] table');
}

/** Return `project.version` from the versions.toml at `path`. */
export function readProjectVersion(path: string | URL): string {
	return projectVersion(readFileSync(path, 'utf8'));
}
