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
 * Vite configuration (docs/DEVELOPMENT.md, "Dev loop").
 *
 * The build uses `base: './'`: `dist/index.html` names its files
 * `./assets/...`, and code-split chunks find each other relative to
 * themselves, so one build works at a host root and under any path a proxy
 * strips (D2-007). Python serves `dist/` and rewrites `./` to `../` for a
 * slot page, which is one level down.
 *
 * The dev server serves the page at the host root and proxies `/api` and
 * `/collab` (the WebSocket) to Python, with `changeOrigin: false` so that the
 * Origin check still sees the browser's own host.
 */
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';
import { readProjectVersion } from './scripts/app-version.ts';
import { editorFonts } from './scripts/editor-fonts.ts';

const backend = process.env['SEGL_API_URL'] ?? 'http://127.0.0.1:8000';
const version = readProjectVersion(new URL('../versions.toml', import.meta.url));

export default defineConfig({
	base: './',
	plugins: [react(), editorFonts()],
	define: {
		__SEGL_VERSION__: JSON.stringify(version)
	},
	build: {
		outDir: 'dist',
		emptyOutDir: true,
		// The editor is one large chunk on its own; the warning is noise here.
		chunkSizeWarningLimit: 3000
	},
	server: {
		host: '127.0.0.1',
		port: 5173,
		strictPort: true,
		proxy: {
			'/api': { target: backend, changeOrigin: false },
			'/collab': { target: backend, changeOrigin: false, ws: true }
		}
	},
	test: {
		include: ['src/**/*.test.ts', 'scripts/**/*.test.ts'],
		environment: 'node'
	}
});
