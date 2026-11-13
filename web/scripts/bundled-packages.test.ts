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

import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, beforeEach, expect, test } from 'vitest';
import {
	BUNDLED_FILE,
	WEB_ROOT,
	describePackage,
	licenseOf,
	listPackages,
	packageFolder
} from './bundled-packages.ts';

let root = '';

beforeEach(() => {
	root = mkdtempSync(join(tmpdir(), 'segl-bundled-'));
});

afterEach(() => {
	rmSync(root, { recursive: true, force: true });
});

function addPackage(folder: string, manifest: Record<string, unknown>): string {
	const path = join(root, folder);
	mkdirSync(path, { recursive: true });
	writeFileSync(join(path, 'package.json'), JSON.stringify(manifest));
	return path;
}

test.each([
	['/w/node_modules/react/index.js', '/w/node_modules/react'],
	['/w/node_modules/react/cjs/react.production.js?commonjs-module', '/w/node_modules/react'],
	['/w/node_modules/@radix-ui/react-slot/dist/index.mjs', '/w/node_modules/@radix-ui/react-slot'],
	// A nested copy is a package of its own.
	[
		'/w/node_modules/mermaid/node_modules/d3-array/src/index.js',
		'/w/node_modules/mermaid/node_modules/d3-array'
	],
	['\0/w/node_modules/tslib/tslib.es6.mjs', '/w/node_modules/tslib'],
	['C:\\w\\node_modules\\clsx\\dist\\clsx.m.js', 'C:/w/node_modules/clsx']
])('%s is in the package at %s', (id, folder) => {
	expect(packageFolder(id)).toBe(folder);
});

test.each([
	'/w/src/App.tsx',
	'/w/src/canvas/Canvas.tsx?v=1',
	// A query is not part of the path, whatever it names.
	'/w/src/App.tsx?from=/w/node_modules/react/index.js',
	'\0vite/preload-helper.js',
	'/w/node_modules/',
	'/w/node_modules/@scope'
])('%s is in no package', (id) => {
	expect(packageFolder(id)).toBeNull();
});

test.each([
	[{ license: 'MIT' }, 'MIT'],
	[{ license: '(MPL-2.0 OR Apache-2.0)' }, '(MPL-2.0 OR Apache-2.0)'],
	[{ licenses: [{ type: 'MIT', url: 'https://example.com' }] }, 'MIT'],
	[{ licenses: [{ type: 'MIT' }, { type: 'Apache-2.0' }, 'junk'] }, 'MIT OR Apache-2.0'],
	[{ license: { type: 'MIT' } }, ''],
	[{}, '']
])('the license of %j is %j', (manifest, license) => {
	expect(licenseOf(manifest)).toBe(license);
});

test('a package is described from its package.json, with its folder relative to the root', () => {
	const folder = addPackage('node_modules/@scope/thing', {
		name: '@scope/thing',
		version: '1.2.3',
		license: 'ISC'
	});

	expect(describePackage(folder, root)).toEqual({
		name: '@scope/thing',
		version: '1.2.3',
		license: 'ISC',
		folder: 'node_modules/@scope/thing'
	});
});

test('a package.json that is not an object is refused', () => {
	const folder = join(root, 'node_modules/odd');
	mkdirSync(folder, { recursive: true });
	writeFileSync(join(folder, 'package.json'), '"text"');

	expect(() => describePackage(folder, root)).toThrow('is not an object');
});

test('the list has one entry for each package and version, sorted, and leaves segl out', () => {
	const zed = addPackage('node_modules/zed', { name: 'zed', version: '1.0.0', license: 'MIT' });
	const alpha = addPackage('node_modules/alpha', { name: 'alpha', version: '2.0.0' });
	const old = addPackage('node_modules/zed/node_modules/alpha', {
		name: 'alpha',
		version: '1.0.0',
		license: 'BSD-3-Clause'
	});
	// The same version, nested in another place.
	const twin = addPackage('node_modules/other/node_modules/alpha', {
		name: 'alpha',
		version: '2.0.0'
	});

	const listed = listPackages(
		[
			`${zed}/index.js`,
			`${zed}/lib/more.js`,
			`${twin}/index.js`,
			`${old}/index.js`,
			`${alpha}/index.js`,
			join(root, 'src/App.tsx')
		],
		root
	);

	expect(listed).toEqual([
		{
			name: 'alpha',
			version: '1.0.0',
			license: 'BSD-3-Clause',
			folder: 'node_modules/zed/node_modules/alpha'
		},
		{ name: 'alpha', version: '2.0.0', license: '', folder: 'node_modules/alpha' },
		{ name: 'zed', version: '1.0.0', license: 'MIT', folder: 'node_modules/zed' }
	]);
});

test('the list is written beside the build and not into it', () => {
	expect(BUNDLED_FILE).toBe(join(WEB_ROOT, '.bundled-packages.json'));
	expect(BUNDLED_FILE.includes('dist')).toBe(false);
});
