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
import { prepareEditor } from './environment.ts';

test('the editor is pointed at segl for its fonts, under the mount', () => {
	const target: Record<string, unknown> = {};

	prepareEditor(new URL('https://dev.example.com/board/'), target);

	// The editor asks for `fonts/<family>/<file>.woff2` under this URL.
	expect(target['EXCALIDRAW_ASSET_PATH']).toBe('https://dev.example.com/board/');
});

test('a scene document names segl as its source, not the host it was drawn on', () => {
	const target: Record<string, unknown> = {};

	prepareEditor(new URL('https://dev.example.com/board/'), target);

	expect(target['EXCALIDRAW_EXPORT_SOURCE']).toBe('segl');
});
