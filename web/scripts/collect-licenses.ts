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
 * Copy the license text of everything in the build to two folders, after
 * `npm run build`. The package build runs it (deploy/debian/build.sh), and
 * pytest runs it against the real build, so a part without a license text
 * fails the suite and not only the package.
 *
 * Usage: `node scripts/collect-licenses.ts PACKAGES_DIR FONTS_DIR`
 *
 * - PACKAGES_DIR gets a folder for each npm package in the build, named
 *   `name@version`, with that package's license and notice files, and
 *   `PACKAGES.txt`, the list. A package whose npm files have no license text
 *   gets the one kept in `licenses/packages/`.
 * - FONTS_DIR gets a folder for each font family the editor ships, from
 *   `licenses/fonts/`. The npm package has no license text for any of them.
 *
 * It fails when a package or a font has no text, and when a kept text is for
 * nothing in the build.
 */
import {
	copyFileSync,
	existsSync,
	mkdirSync,
	readdirSync,
	readFileSync,
	rmSync,
	writeFileSync
} from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { BUNDLED_FILE, WEB_ROOT, type BundledPackage } from './bundled-packages.ts';
import { EDITOR_FONTS } from './editor-fonts.ts';

/** The texts segl keeps for what ships none (`licenses/README.md`). */
export const KEPT = join(WEB_ROOT, 'licenses');

/**
 * A package's license and notice files: `LICENSE`, `license.txt`,
 * `LICENSE.md`, `LICENSE-MIT`, `COPYING`, `NOTICE`. Not a script whose name
 * starts the same way.
 */
const LEGAL = /^(licen[cs]e|copying|notice)(-[a-z0-9]+)?(\.(md|txt))?$/i;

/**
 * The kept text for a package whose npm files have none: the package's
 * name, or the scope all its packages share, and the file in
 * `licenses/packages/`.
 */
export const KEPT_PACKAGES: readonly (readonly [string, string])[] = [
	['@excalidraw/excalidraw', 'excalidraw.txt'],
	['@radix-ui/', 'radix-ui.txt'],
	['fastdom', 'fastdom.txt'],
	['react-remove-scroll-bar', 'react-remove-scroll-bar.txt']
];

/** Return the names of a folder's license and notice files, sorted. */
export function legalFiles(folder: string): string[] {
	return readdirSync(folder)
		.filter((name) => LEGAL.test(name))
		.sort();
}

/** Return the kept file for a package name, or null. */
export function keptFor(name: string): string | null {
	for (const [key, file] of KEPT_PACKAGES) {
		if (key.endsWith('/') ? name.startsWith(key) : name === key) return file;
	}
	return null;
}

/** The folder a package's texts go to: `@scope/name` at 1.2.3 is `@scope__name@1.2.3`. */
export function folderName(bundled: BundledPackage): string {
	return `${bundled.name.replace('/', '__')}@${bundled.version}`;
}

export interface Collected {
	/** What was copied, for the summary line. */
	count: number;
	/** What has no license text, or a kept text for nothing. Empty when all is well. */
	problems: string[];
}

/** Copy every bundled package's texts to `target`, and write `PACKAGES.txt`. */
export function collectPackages(
	bundled: readonly BundledPackage[],
	target: string,
	root: string = WEB_ROOT,
	kept: string = join(KEPT, 'packages')
): Collected {
	const problems: string[] = [];
	const used = new Set<string>();
	const lines: string[] = [];
	rmSync(target, { recursive: true, force: true });
	mkdirSync(target, { recursive: true });
	for (const entry of bundled) {
		const source = join(root, entry.folder);
		const files = legalFiles(source);
		const fallback = keptFor(entry.name);
		const folder = join(target, folderName(entry));
		mkdirSync(folder);
		for (const file of files) copyFileSync(join(source, file), join(folder, file));
		if (files.length === 0) {
			if (fallback === null || !existsSync(join(kept, fallback))) {
				problems.push(`${entry.name} ${entry.version} has no license text`);
				continue;
			}
			copyFileSync(join(kept, fallback), join(folder, 'LICENSE'));
			used.add(fallback);
		}
		lines.push(`${entry.name} ${entry.version} ${entry.license || '(see its folder)'}`);
	}
	for (const [key, file] of KEPT_PACKAGES) {
		if (!used.has(file)) problems.push(`licenses/packages/${file} (${key}) is for no package`);
	}
	const head = [
		'The npm packages whose code is in the web application, each with its',
		"version and the license its package.json names. Each package's license",
		'text is in the folder beside this file named after it.',
		''
	];
	writeFileSync(join(target, 'PACKAGES.txt'), [...head, ...lines, ''].join('\n'));
	return { count: lines.length, problems };
}

/** Copy the kept texts of every font family the editor ships to `target`. */
export function collectFonts(
	target: string,
	fonts: string = EDITOR_FONTS,
	kept: string = join(KEPT, 'fonts')
): Collected {
	const problems: string[] = [];
	const families = readdirSync(fonts, { withFileTypes: true })
		.filter((entry) => entry.isDirectory())
		.map((entry) => entry.name)
		.sort();
	const have = existsSync(kept) ? readdirSync(kept).sort() : [];
	rmSync(target, { recursive: true, force: true });
	mkdirSync(target, { recursive: true });
	let count = 0;
	for (const family of families) {
		const source = join(kept, family);
		const files = have.includes(family) ? readdirSync(source).sort() : [];
		if (files.length === 0) {
			problems.push(`the font ${family} has no license text in licenses/fonts/${family}/`);
			continue;
		}
		mkdirSync(join(target, family));
		for (const file of files) copyFileSync(join(source, file), join(target, family, file));
		count += 1;
	}
	for (const family of have) {
		if (!families.includes(family)) {
			problems.push(`licenses/fonts/${family}/ is for no font the editor ships`);
		}
	}
	return { count, problems };
}

/** Read the list the build wrote. */
export function readBundled(file: string = BUNDLED_FILE): BundledPackage[] {
	if (!existsSync(file)) {
		throw new Error(`${file} is missing: run \`npm run build\` first`);
	}
	return JSON.parse(readFileSync(file, 'utf8')) as BundledPackage[];
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
	const [packagesDir, fontsDir] = process.argv.slice(2);
	if (!packagesDir || !fontsDir) {
		console.error('usage: node scripts/collect-licenses.ts PACKAGES_DIR FONTS_DIR');
		process.exit(2);
	}
	const packages = collectPackages(readBundled(), packagesDir);
	const fonts = collectFonts(fontsDir);
	const problems = [...packages.problems, ...fonts.problems];
	for (const problem of problems) console.error(`collect-licenses: ${problem}`);
	if (problems.length > 0) process.exit(1);
	console.log(
		`collect-licenses: ${packages.count} packages in ${packagesDir}, ` +
			`${fonts.count} fonts in ${fontsDir}`
	);
}
