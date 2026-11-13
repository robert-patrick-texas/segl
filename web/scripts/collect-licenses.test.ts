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

import {
	existsSync,
	mkdirSync,
	mkdtempSync,
	readdirSync,
	readFileSync,
	rmSync,
	writeFileSync
} from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, beforeEach, expect, test } from 'vitest';
import type { BundledPackage } from './bundled-packages.ts';
import {
	KEPT,
	KEPT_PACKAGES,
	collectFonts,
	collectPackages,
	folderName,
	keptFor,
	legalFiles,
	readBundled
} from './collect-licenses.ts';
import { EDITOR_FONTS } from './editor-fonts.ts';

let root = '';

beforeEach(() => {
	root = mkdtempSync(join(tmpdir(), 'segl-licenses-'));
});

afterEach(() => {
	rmSync(root, { recursive: true, force: true });
});

function write(path: string, text = 'text'): void {
	const file = join(root, path);
	mkdirSync(join(file, '..'), { recursive: true });
	writeFileSync(file, text);
}

function bundled(name: string, version: string, license = 'MIT'): BundledPackage {
	return { name, version, license, folder: `node_modules/${name}` };
}

/** One file for each kept text, so that none is "for no package". */
function keptPackages(): string {
	for (const [, file] of KEPT_PACKAGES) write(`kept/${file}`, `kept ${file}`);
	return join(root, 'kept');
}

/** A package for each kept text, with no license file of its own. */
function usersOfKept(): BundledPackage[] {
	return KEPT_PACKAGES.map(([key]) => {
		const name = key.endsWith('/') ? `${key}thing` : key;
		write(`node_modules/${name}/index.js`);
		return bundled(name, '1.0.0');
	});
}

test.each([
	'LICENSE',
	'license',
	'LICENSE.md',
	'license.txt',
	'LICENCE',
	'LICENSE-MIT',
	'LICENSE-MPL',
	'COPYING',
	'NOTICE',
	'NOTICE.txt'
])('%s is a license or notice file', (name) => {
	write(`pkg/${name}`);

	expect(legalFiles(join(root, 'pkg'))).toEqual([name]);
});

test.each([
	'license-update.mjs',
	'license.js',
	'LICENSE.json',
	'licenses.md',
	'README.md',
	'package.json',
	'unlicense'
])('%s is not', (name) => {
	write(`pkg/${name}`);

	expect(legalFiles(join(root, 'pkg'))).toEqual([]);
});

test.each([
	['@excalidraw/excalidraw', 'excalidraw.txt'],
	['@radix-ui/react-slot', 'radix-ui.txt'],
	['@radix-ui/primitive', 'radix-ui.txt'],
	['fastdom', 'fastdom.txt'],
	['react-remove-scroll-bar', 'react-remove-scroll-bar.txt']
])('%s has the kept text %s', (name, file) => {
	expect(keptFor(name)).toBe(file);
});

test.each(['react', '@excalidraw/laser-pointer', 'fastdom-extra', 'radix-ui', '@radix-ui'])(
	'%s has no kept text',
	(name) => {
		expect(keptFor(name)).toBeNull();
	}
);

test('every kept package text exists in licenses/packages', () => {
	for (const [, file] of KEPT_PACKAGES) {
		expect(readFileSync(join(KEPT, 'packages', file), 'utf8')).toMatch(/copyright/i);
	}
	expect(readdirSync(join(KEPT, 'packages')).sort()).toEqual(
		KEPT_PACKAGES.map(([, file]) => file).sort()
	);
});

test('a folder is named after the package and its version', () => {
	expect(folderName(bundled('react', '19.3.1'))).toBe('react@19.3.1');
	expect(folderName(bundled('@radix-ui/react-slot', '1.0.1'))).toBe('@radix-ui__react-slot@1.0.1');
});

test("each package's license and notice files are copied, and the list is written", () => {
	write('node_modules/alpha/LICENSE', 'alpha license');
	write('node_modules/alpha/NOTICE', 'alpha notice');
	write('node_modules/alpha/index.js');
	write('node_modules/@scope/beta/license.md', 'beta license');
	const target = join(root, 'out');

	const result = collectPackages(
		[bundled('alpha', '1.0.0'), bundled('@scope/beta', '2.0.0', ''), ...usersOfKept()],
		target,
		root,
		keptPackages()
	);

	expect(result.problems).toEqual([]);
	expect(result.count).toBe(2 + KEPT_PACKAGES.length);
	expect(readdirSync(join(target, 'alpha@1.0.0')).sort()).toEqual(['LICENSE', 'NOTICE']);
	expect(readFileSync(join(target, 'alpha@1.0.0', 'LICENSE'), 'utf8')).toBe('alpha license');
	expect(readdirSync(join(target, '@scope__beta@2.0.0'))).toEqual(['license.md']);
	const list = readFileSync(join(target, 'PACKAGES.txt'), 'utf8').split('\n');
	expect(list).toContain('alpha 1.0.0 MIT');
	// A package.json that names no license: the folder has the text.
	expect(list).toContain('@scope/beta 2.0.0 (see its folder)');
});

test('a package with no license file gets the kept text', () => {
	const target = join(root, 'out');

	const result = collectPackages(usersOfKept(), target, root, keptPackages());

	expect(result.problems).toEqual([]);
	expect(readFileSync(join(target, '@radix-ui__thing@1.0.0', 'LICENSE'), 'utf8')).toBe(
		'kept radix-ui.txt'
	);
	expect(readFileSync(join(target, 'fastdom@1.0.0', 'LICENSE'), 'utf8')).toBe('kept fastdom.txt');
});

test("a package's own license file is used before the kept text", () => {
	const packages = usersOfKept();
	write('node_modules/fastdom/LICENSE', 'its own');
	const target = join(root, 'out');

	const result = collectPackages(packages, target, root, keptPackages());

	expect(readFileSync(join(target, 'fastdom@1.0.0', 'LICENSE'), 'utf8')).toBe('its own');
	// The kept text is then for nothing, and the build says so.
	expect(result.problems).toEqual(['licenses/packages/fastdom.txt (fastdom) is for no package']);
});

test('a package with no license file and no kept text is a problem', () => {
	write('node_modules/bare/index.js');
	const target = join(root, 'out');

	const result = collectPackages(
		[bundled('bare', '0.1.0'), ...usersOfKept()],
		target,
		root,
		keptPackages()
	);

	expect(result.problems).toEqual(['bare 0.1.0 has no license text']);
	expect(readFileSync(join(target, 'PACKAGES.txt'), 'utf8')).not.toContain('bare');
});

test('a kept text whose file is gone is a problem for its package', () => {
	const kept = keptPackages();
	rmSync(join(kept, 'radix-ui.txt'));

	const result = collectPackages(usersOfKept(), join(root, 'out'), root, kept);

	expect(result.problems).toEqual([
		'@radix-ui/thing 1.0.0 has no license text',
		'licenses/packages/radix-ui.txt (@radix-ui/) is for no package'
	]);
});

test('what an earlier run left in the target is removed', () => {
	write('out/gone@1.0.0/LICENSE');

	collectPackages(usersOfKept(), join(root, 'out'), root, keptPackages());

	expect(existsSync(join(root, 'out', 'gone@1.0.0'))).toBe(false);
});

test("each font family's kept texts are copied", () => {
	write('fonts/Alpha/Alpha-Regular.woff2');
	write('fonts/Beta/Beta-Regular.woff2');
	write('fonts/README.txt');
	write('kept/Alpha/OFL.txt', 'alpha ofl');
	write('kept/Beta/License.txt', 'beta agreement');
	write('kept/Beta/COPYING', 'beta gpl');
	write('out/Old/OFL.txt');
	const target = join(root, 'out');

	const result = collectFonts(target, join(root, 'fonts'), join(root, 'kept'));

	expect(result).toEqual({ count: 2, problems: [] });
	expect(readdirSync(target).sort()).toEqual(['Alpha', 'Beta']);
	expect(readFileSync(join(target, 'Alpha', 'OFL.txt'), 'utf8')).toBe('alpha ofl');
	expect(readdirSync(join(target, 'Beta')).sort()).toEqual(['COPYING', 'License.txt']);
});

test('a font with no kept text, or an empty folder, is a problem', () => {
	write('fonts/Alpha/Alpha-Regular.woff2');
	write('fonts/Beta/Beta-Regular.woff2');
	mkdirSync(join(root, 'kept', 'Beta'), { recursive: true });

	const result = collectFonts(join(root, 'out'), join(root, 'fonts'), join(root, 'kept'));

	expect(result.problems).toEqual([
		'the font Alpha has no license text in licenses/fonts/Alpha/',
		'the font Beta has no license text in licenses/fonts/Beta/'
	]);
});

test('a kept text for a font the editor does not ship is a problem', () => {
	write('fonts/Alpha/Alpha-Regular.woff2');
	write('kept/Alpha/OFL.txt');
	write('kept/Gone/OFL.txt');

	const result = collectFonts(join(root, 'out'), join(root, 'fonts'), join(root, 'kept'));

	expect(result).toEqual({
		count: 1,
		problems: ['licenses/fonts/Gone/ is for no font the editor ships']
	});
});

test('every font the pinned editor ships has a kept text', () => {
	const result = collectFonts(join(root, 'out'));

	expect(result.problems).toEqual([]);
	expect(result.count).toBe(readdirSync(EDITOR_FONTS).length);
	expect(readdirSync(join(root, 'out', 'Liberation')).sort()).toEqual(['COPYING', 'License.txt']);
});

test('the list is read from the file the build wrote', () => {
	write('list.json', JSON.stringify([bundled('alpha', '1.0.0')]));

	expect(readBundled(join(root, 'list.json'))).toEqual([bundled('alpha', '1.0.0')]);
	expect(() => readBundled(join(root, 'none.json'))).toThrow('run `npm run build` first');
});
