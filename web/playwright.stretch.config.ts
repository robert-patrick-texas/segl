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
 * The two size runs of docs/TEST-PLAN.md ("Preliminary sizes"): ten editors
 * on one slot, and a slot of a thousand elements. They are not part of the
 * gate. Run them when the numbers are wanted, and read what they print:
 * `npm run stretch`, after `npm run build`.
 *
 * The runs use the servers and the ports of the browser tests
 * (`playwright.config.ts`), so the two do not run at the same time. Each run
 * starts new servers. Every spec runs twice: against Python alone, and
 * through nginx at `/board/`, as a site serves it.
 */
import { defineConfig } from '@playwright/test';
import main from './playwright.config.ts';

const MOUNTS = ['direct', 'board'];

export default defineConfig({
	...main,
	testDir: 'stretch',
	testMatch: '*.stretch.ts',
	outputDir: 'test-results/stretch',
	timeout: 300_000,
	projects: (main.projects ?? [])
		.filter((project) => MOUNTS.includes(project.name ?? ''))
		.map((project) => ({ name: project.name, use: project.use }))
});
