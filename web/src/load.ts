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

/** A slot's scene on its way from the server to the canvas. */

export type Load<Scene> =
	| { state: 'loading' }
	| { state: 'ready'; slot: number; scene: Scene }
	| { state: 'failed'; message: string };

/**
 * Return the scene to mount for `slot`, or null while there is none.
 *
 * A loaded scene is kept with its slot. On the way from one slot to another
 * there is one render that has the new slot and still the old slot's scene.
 * That scene is not the new slot's: it must not be mounted as it, and a
 * canvas that held it must never be connected to the new slot's room.
 */
export function loadedScene<Scene>(load: Load<Scene>, slot: number): Scene | null {
	return load.state === 'ready' && load.slot === slot ? load.scene : null;
}
