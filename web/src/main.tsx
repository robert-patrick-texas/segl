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

/** Entry point: take an edit link's token, find segl's root, point the editor at it, and render. */
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './App.tsx';
import './app.css';
import { prepareEditor } from './canvas/environment.ts';
import { loadConfig } from './config.ts';
import { takeEditLink } from './editToken.ts';

const container = document.getElementById('root')!;

// First of all, before anything waits or the router reads the address: a
// token in the fragment leaves the address bar as soon as this script runs.
const linkToken = takeEditLink(window);

try {
	const config = await loadConfig(window.SEGL_CONFIG, window.location.href);
	prepareEditor(config.rootUrl);
	createRoot(container).render(
		<StrictMode>
			<App config={config} linkToken={linkToken} />
		</StrictMode>
	);
} catch (error) {
	// Only the dev server gets here, when Python is not answering behind it.
	const message = error instanceof Error ? error.message : String(error);
	container.textContent = `segl could not start: ${message}`;
}
