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
 * JSON export and import as the page words them (S-011, D2-031): which
 * dropped file is a scene to import, what an exported file is called, and
 * what to say when an import is refused. No React and no editor here.
 *
 * The export is the editor's own, in its menu. The import is segl's: the file
 * goes to `POST api/v1/slots/{n}/import`, and the server puts its scene in
 * place of the slot's for everyone.
 */
import { IMAGE_TYPES } from './collab/files.ts';

/** What the control says where a viewer would find the way to import. */
export const IMPORT_NEEDS_TOKEN = 'Importing needs the edit token.';

/** What the control says while this browser is not in the slot's room. */
export const IMPORT_NEEDS_CONNECTION = 'Importing waits for the connection.';

/** The name and the type of a file, as a `File` has them. */
export interface FileLike {
	name: string;
	type: string;
}

const LIBRARY_TYPE = 'application/vnd.excalidrawlib+json';

/**
 * How the files of the editor's image types are named. A browser gives a
 * file no type when the system does not know its extension, and the editor
 * then tells an image by its first bytes. A drop is decided before the file
 * can be read, so here the name has to do.
 */
const IMAGE_NAME = /\.(png|jpe?g|jfif|gif|webp|svg|bmp|ico|avif)$/;

/**
 * Whether a file dropped on the canvas goes to the import, and not to the
 * editor. The editor would open a scene file in this browser's canvas alone,
 * which on a shared slot shows one person a drawing nobody else has.
 *
 * The editor keeps two kinds: an image, which it places on the canvas, and a
 * library of shapes, which it adds to this browser's library. Anything else
 * is taken for a scene, and the server says so when it is not one.
 */
export function goesToImport(file: FileLike): boolean {
	const type = file.type.toLowerCase();
	const name = file.name.toLowerCase();
	if (IMAGE_TYPES.has(type) || (type === '' && IMAGE_NAME.test(name))) return false;
	return type !== LIBRARY_TYPE && !name.endsWith('.excalidrawlib');
}

/** Where something dropped on the canvas goes. */
export type DropGoesTo = 'editor' | 'import' | 'nowhere';

/**
 * Decide a drop on the canvas, before the editor is given it. `file` is the
 * first file of the drop, or null when it carries none, as a dragged link or
 * a shape from the library does.
 *
 * A scene file goes to the import whoever drops it: the Import control then
 * tells a viewer that importing needs the edit token. Everything else is the
 * editor's, unless this browser is view-only. The editor's own drop handler
 * does not ask about its view mode, and would place an image, or a link, on
 * a canvas that then shows one person a drawing nobody else has (S-008).
 */
export function dropGoesTo(file: FileLike | null, viewOnly: boolean): DropGoesTo {
	if (file !== null && goesToImport(file)) return 'import';
	return viewOnly ? 'nowhere' : 'editor';
}

/** Characters a file name does not have on one system or another, and controls. */
const NOT_IN_A_NAME = /[<>:"/\\|?*\p{Cc}]+/gu;

/**
 * Return the name the editor gives an exported file, without its extension:
 * the slot's title, or `slot-4` while the title is not known or has nothing a
 * file name can keep. The editor's own default is `Untitled` and the date,
 * the same for every slot.
 */
export function exportName(title: string | undefined, slot: number): string {
	const name = (title ?? '')
		.replace(NOT_IN_A_NAME, ' ')
		.replace(/\s+/g, ' ')
		.trim()
		// A name that starts with a dot is hidden, and one that ends with one
		// loses it on Windows.
		.replace(/^[.\s]+|[.\s]+$/g, '');
	return name === '' ? `slot-${slot}` : name;
}

/**
 * Return a display name as the `X-Segl-Display-Name` header carries it. A
 * header is ASCII and a name is not, so it is percent-encoded.
 */
export function nameHeader(displayName: string): string {
	return encodeURIComponent(displayName);
}

/**
 * Return what to tell a person whose import failed. `error` is what the call
 * threw: an `ApiError` carries the server's code.
 */
export function importProblem(error: unknown): string {
	const code =
		typeof error === 'object' && error !== null && 'code' in error
			? (error as { code: unknown }).code
			: null;
	if (code === 'view_only') return IMPORT_NEEDS_TOKEN;
	if (code === 'payload_too_large') return 'That file is larger than this segl takes.';
	if (code === 'invalid_document' || code === 'bad_request') {
		return 'That is not an Excalidraw file.';
	}
	if (error instanceof Error && error.message !== '') return error.message;
	return 'segl could not import that file.';
}
