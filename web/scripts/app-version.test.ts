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

import { expect, test } from 'vitest';
import { projectVersion, readProjectVersion } from './app-version.ts';

test('reads version from the [project] table', () => {
	const toml = [
		'# Canonical versions',
		'[project]',
		'name = "segl"',
		'version = "1.4.2"  # the application',
		'',
		'[runtime]',
		'python = "3.15.2"'
	].join('\n');

	expect(projectVersion(toml)).toBe('1.4.2');
});

test('a version key in another table is not the application version', () => {
	const toml = ['[held.vite]', 'version = "8.3.8"', '', '[project]', 'version = "0.3.0"'].join(
		'\n'
	);

	expect(projectVersion(toml)).toBe('0.3.0');
});

test('a file without the entry is an error, not an empty version', () => {
	expect(() => projectVersion('[runtime]\npython = "3.15.2"\n')).toThrow('[project]');
});

test('the repository file has a version', () => {
	const version = readProjectVersion(new URL('../../versions.toml', import.meta.url));

	expect(version).toMatch(/^\d+\.\d+\.\d+$/);
});
