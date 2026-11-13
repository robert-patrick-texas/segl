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
 * The editor's fonts, served by segl itself (S-014, D2-026).
 *
 * Excalidraw loads its canvas fonts at run time from
 * `window.EXCALIDRAW_ASSET_PATH`, and from a public CDN when that is not set.
 * The fonts ship inside the npm package. This plugin copies that folder into
 * the build as `fonts/`, and serves the same folder from the dev server, so
 * the page never leaves segl for them.
 *
 * One file is not the editor's. `fonts/` in this package holds font files
 * that segl ships in place of the editor's file of the same path, and the
 * build lays them over the copy (D2-026). Today that is Liberation Sans: the
 * editor's file is version 1.05, under the GNU General Public License, and
 * segl ships version 2.1.5, under the SIL Open Font License
 * (`licenses/README.md`).
 */
import { cpSync, createReadStream, existsSync, readdirSync, statSync } from 'node:fs';
import { join, normalize, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import type { Plugin } from 'vite';

/** The folder the pinned package ships. The editor asks for `fonts/<family>/<file>.woff2`. */
export const EDITOR_FONTS = fileURLToPath(
	new URL('../node_modules/@excalidraw/excalidraw/dist/prod/fonts', import.meta.url)
);

/** The font files segl ships in place of the editor's, at the same paths. */
export const REPLACED_FONTS = fileURLToPath(new URL('../fonts', import.meta.url));

/** Return the replaced font files, as `family/file.woff2`, sorted. */
export function replacedFonts(folder: string = REPLACED_FONTS): string[] {
	if (!existsSync(folder)) return [];
	return readdirSync(folder, { recursive: true, encoding: 'utf8' })
		.map((path) => path.split(sep).join('/'))
		.filter((path) => path.endsWith('.woff2'))
		.sort();
}

/**
 * Copy each replaced font over the editor's file of the same path in
 * `target`, a copy of the editor's fonts folder.
 *
 * A replacement for a file the editor does not ship is an error: the editor
 * moved or dropped that font, and the replacement would be served to nobody.
 */
export function replaceFonts(
	target: string,
	folder: string = REPLACED_FONTS,
	fonts: string = EDITOR_FONTS
): string[] {
	const replaced = replacedFonts(folder);
	for (const path of replaced) {
		if (!existsSync(join(fonts, path))) {
			throw new Error(
				`fonts/${path} replaces a file the editor does not ship: ` +
					'see web/licenses/README.md, "The font segl replaces"'
			);
		}
	}
	for (const path of replaced) cpSync(join(folder, path), join(target, path));
	return replaced;
}

/** Return the font file a dev-server request path names, or null. */
export function fontFile(requestPath: string, fonts: string = EDITOR_FONTS): string | null {
	let path: string;
	try {
		path = decodeURIComponent(requestPath.split('?')[0] ?? '');
	} catch {
		return null;
	}
	const file = normalize(join(fonts, path));
	if (!file.startsWith(fonts + sep) || !file.endsWith('.woff2')) return null;
	return file;
}

export function editorFonts(): Plugin {
	let outDir = '';
	let building = false;
	return {
		name: 'segl:editor-fonts',
		configResolved(config) {
			outDir = resolve(config.root, config.build.outDir);
			building = config.command === 'build';
		},
		configureServer(server) {
			server.middlewares.use('/fonts', (request, response, next) => {
				// A replaced font first, then the editor's own.
				const file = [REPLACED_FONTS, EDITOR_FONTS]
					.map((folder) => fontFile(request.url ?? '', folder))
					.find((path) => path !== null && statSync(path, { throwIfNoEntry: false })?.isFile());
				if (!file) return next();
				response.setHeader('Content-Type', 'font/woff2');
				createReadStream(file).pipe(response);
			});
		},
		writeBundle() {
			if (!building) return;
			cpSync(EDITOR_FONTS, join(outDir, 'fonts'), { recursive: true });
			replaceFonts(join(outDir, 'fonts'));
		}
	};
}
