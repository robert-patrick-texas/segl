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
 */
import { cpSync, createReadStream, statSync } from 'node:fs';
import { join, normalize, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import type { Plugin } from 'vite';

/** The folder the pinned package ships. The editor asks for `fonts/<family>/<file>.woff2`. */
export const EDITOR_FONTS = fileURLToPath(
	new URL('../node_modules/@excalidraw/excalidraw/dist/prod/fonts', import.meta.url)
);

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
				const file = fontFile(request.url ?? '');
				if (file === null) return next();
				try {
					statSync(file);
				} catch {
					return next();
				}
				response.setHeader('Content-Type', 'font/woff2');
				createReadStream(file).pipe(response);
			});
		},
		writeBundle() {
			if (building) cpSync(EDITOR_FONTS, join(outDir, 'fonts'), { recursive: true });
		}
	};
}
