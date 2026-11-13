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
 * Which npm packages are in the build, in the form of Sunstone's
 * `frontend/scripts/bundled-packages.ts`.
 *
 * The minified build keeps no license comments, so whoever passes the build
 * on has to carry the license texts beside it. This plugin writes the list
 * of packages whose code is in the build to `.bundled-packages.json`, beside
 * `dist/` and not in it, so segl does not serve it. `collect-licenses.ts`
 * reads the list and copies each package's license text.
 */
import { readFileSync, writeFileSync } from 'node:fs';
import { join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';
import type { Plugin } from 'vite';

/** The web package's folder. Paths in the list are relative to it. */
export const WEB_ROOT = fileURLToPath(new URL('..', import.meta.url));

/** Where the build writes the list. */
export const BUNDLED_FILE = join(WEB_ROOT, '.bundled-packages.json');

export interface BundledPackage {
	name: string;
	version: string;
	/** What its `package.json` says, or `''` when it says nothing. */
	license: string;
	/** The package's folder, relative to `web/`. */
	folder: string;
}

const MARK = '/node_modules/';

/**
 * Return the folder of the package a module is in, or null for segl's own.
 *
 * The last `node_modules` in the path counts: a package nested inside
 * another is a package of its own, often at another version.
 */
export function packageFolder(id: string): string | null {
	const path = (id.split('?')[0] ?? '').replaceAll('\\', '/').replace(/^\0+/, '');
	const at = path.lastIndexOf(MARK);
	if (at < 0) return null;
	const parts = path.slice(at + MARK.length).split('/');
	const name = parts[0]?.startsWith('@') ? `${parts[0]}/${parts[1] ?? ''}` : (parts[0] ?? '');
	if (name === '' || name.endsWith('/')) return null;
	return path.slice(0, at + MARK.length) + name;
}

/** Return the license a `package.json` names, in one line. */
export function licenseOf(manifest: Record<string, unknown>): string {
	const { license, licenses } = manifest;
	if (typeof license === 'string') return license;
	if (Array.isArray(licenses)) {
		return licenses
			.map((entry: unknown) =>
				typeof entry === 'object' && entry !== null && 'type' in entry ? String(entry.type) : ''
			)
			.filter((type) => type !== '')
			.join(' OR ');
	}
	return '';
}

/** Read one package's `package.json`. */
export function describePackage(folder: string, root: string = WEB_ROOT): BundledPackage {
	const manifest: unknown = JSON.parse(readFileSync(join(folder, 'package.json'), 'utf8'));
	if (typeof manifest !== 'object' || manifest === null) {
		throw new Error(`${folder}/package.json is not an object`);
	}
	const fields = manifest as Record<string, unknown>;
	return {
		name: String(fields['name']),
		version: String(fields['version']),
		license: licenseOf(fields),
		folder: relative(root, folder).replaceAll('\\', '/')
	};
}

/**
 * Turn module ids into the list: one entry for each package and version,
 * sorted, so the file is the same from build to build.
 */
export function listPackages(ids: Iterable<string>, root: string = WEB_ROOT): BundledPackage[] {
	const folders = new Set<string>();
	for (const id of ids) {
		const folder = packageFolder(id);
		if (folder !== null) folders.add(folder);
	}
	const found = new Map<string, BundledPackage>();
	for (const folder of [...folders].sort()) {
		const described = describePackage(folder, root);
		const key = `${described.name}@${described.version}`;
		// The same version nested in two places is the same package.
		if (!found.has(key)) found.set(key, described);
	}
	return [...found.values()].sort((a, b) =>
		`${a.name}@${a.version}` < `${b.name}@${b.version}` ? -1 : 1
	);
}

export function bundledPackages(): Plugin {
	return {
		name: 'segl:bundled-packages',
		apply: 'build',
		generateBundle(_options, bundle) {
			const ids: string[] = [];
			for (const output of Object.values(bundle)) {
				if (output.type === 'chunk') ids.push(...output.moduleIds);
			}
			writeFileSync(BUNDLED_FILE, JSON.stringify(listPackages(ids), null, '\t') + '\n');
		}
	};
}
