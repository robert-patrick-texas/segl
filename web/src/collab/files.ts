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
 * The files of the images on a canvas (D2-028; docs/ARCHITECTURE.md,
 * "Collaboration").
 *
 * The editor keeps an image's bytes outside the scene, as a `data:` URL under
 * a file id, and an image element names that id. segl stores the bytes once,
 * under the SHA-256 the upload route answers with, and each slot has a list
 * that says which hash a file id means.
 *
 * `FileSync` keeps a canvas and that list together. A file the canvas holds
 * and the list lacks is uploaded, and then named to the server by the session.
 * A file the list names and the canvas lacks is fetched and handed to the
 * editor. It knows nothing of sockets or of `fetch`: the session and a
 * `FileTransport` do those.
 */

/** The image types the pinned editor takes. `src/segl/assets.py` has the same list. */
export const IMAGE_TYPES: ReadonlySet<string> = new Set([
	'image/svg+xml',
	'image/png',
	'image/jpeg',
	'image/gif',
	'image/webp',
	'image/bmp',
	'image/x-icon',
	'image/avif',
	'image/jfif'
]);

/** Which bytes a slot's file id means, as the server's messages carry it. */
export interface FileRef {
	/** The editor's id for the file, which an image element names. */
	id: string;
	/** The SHA-256 of the bytes: their name at `api/v1/assets/`. */
	hash: string;
	mimeType: string;
}

/** A file as the canvas holds it. */
export interface CanvasFile {
	id: string;
	mimeType: string;
	dataURL: string;
}

const FILE_ID = /^[A-Za-z0-9_-]{1,64}$/;
const HASH = /^[0-9a-f]{64}$/;

export function isHash(value: unknown): value is string {
	return typeof value === 'string' && HASH.test(value);
}

function fileRef(value: unknown): FileRef | null {
	if (typeof value !== 'object' || value === null) return null;
	const { id, hash, mimeType } = value as Record<string, unknown>;
	if (typeof id !== 'string' || !FILE_ID.test(id) || !isHash(hash)) return null;
	if (typeof mimeType !== 'string' || !IMAGE_TYPES.has(mimeType)) return null;
	return { id, hash, mimeType };
}

/** Return a file list the server sent, or null when it is not one. */
export function parseFileRefs(value: unknown): FileRef[] | null {
	if (!Array.isArray(value)) return null;
	const refs = value.map(fileRef);
	return refs.includes(null) ? null : (refs as FileRef[]);
}

/**
 * The server will not take, or does not have, this file, and asking again
 * would get the same answer. Any other failure is tried again.
 */
export class Refused extends Error {}

/** How the bytes travel. `collab/transport.ts` does it over HTTP. */
export interface FileTransport {
	/** Store a file's bytes on the server, and return their hash. */
	upload(file: CanvasFile): Promise<string>;
	/** Fetch the bytes a file id means, as the `data:` URL the editor keeps. */
	download(ref: FileRef): Promise<string>;
}

/** What `FileSync` needs of the canvas. `SceneEditor` has both. */
export interface FileEditor {
	/**
	 * The file of every image on the canvas that is not deleted, by file id:
	 * the file when the canvas holds its bytes, and null when it does not.
	 */
	images(): ReadonlyMap<string, CanvasFile | null>;
	/** Give the editor files it lacks. One it already holds is left alone. */
	addFiles(files: readonly CanvasFile[]): void;
}

export interface FileSyncOptions {
	editor: FileEditor;
	transport: FileTransport;
	/** Whether this browser may upload now: the server has said it is an editor. */
	mayUpload(): boolean;
	/** Called when `busy()` or `unannounced()` may have changed. */
	onChange(): void;
}

/** How long after a transfer failed it is tried again. */
export const RETRY_MS = 5000;

type Timer = ReturnType<typeof setTimeout>;

export class FileSync {
	private readonly options: FileSyncOptions;
	/** What the slot's file list is known to hold, by file id. */
	private readonly listed = new Map<string, FileRef>();
	/** What this browser uploaded. The bytes are stored. The list may not name them yet. */
	private readonly uploaded = new Map<string, FileRef>();
	/** Named to the server by this browser, and not yet seen in a list from it. */
	private readonly named = new Set<string>();
	/** Uploaded a second time, after the server had lost the bytes once. */
	private readonly again = new Set<string>();
	private readonly uploading = new Set<string>();
	private readonly downloading = new Set<string>();
	/** When a failed transfer may be tried again, in `Date.now()` time. Never, for a refusal. */
	private readonly uploadAfter = new Map<string, number>();
	private readonly downloadAfter = new Map<string, number>();
	/** The files the canvas holds that the list does not name. */
	private unsaved: ReadonlySet<string> = new Set();
	private retryTimer: Timer | undefined;
	private stopped = false;

	constructor(options: FileSyncOptions) {
		this.options = options;
	}

	/** Forget everything, and let transfers under way end unheard. */
	stop(): void {
		this.stopped = true;
		clearTimeout(this.retryTimer);
	}

	/** True while the canvas holds a file the slot's list does not name. */
	busy(): boolean {
		return this.unsaved.size > 0;
	}

	/** The slot's whole list, as the server sent it with a scene. It replaces what was known. */
	reset(refs: readonly FileRef[]): void {
		this.listed.clear();
		this.named.clear();
		this.learn(refs);
	}

	/** Files the server says the list holds. A file id keeps the bytes it was first given. */
	learn(refs: readonly FileRef[]): void {
		for (const ref of refs) {
			if (!this.listed.has(ref.id)) this.listed.set(ref.id, ref);
		}
		this.sync();
	}

	/** The files this browser uploaded that the server has still to be told of. */
	unannounced(): FileRef[] {
		return Array.from(this.uploaded.values()).filter((ref) => this.unsaved.has(ref.id));
	}

	/** The session told the server of these. They count as listed from now on. */
	announced(refs: readonly FileRef[]): void {
		for (const ref of refs) {
			this.listed.set(ref.id, ref);
			this.named.add(ref.id);
		}
		this.sync();
	}

	/**
	 * The server did not have the bytes of a file it was told of
	 * (`unknown_file`): it lost them, or is another server. They are uploaded
	 * once more, and after a second loss the file is left alone.
	 */
	lost(): void {
		for (const id of this.named) {
			this.listed.delete(id);
			this.uploaded.delete(id);
			if (this.again.has(id)) this.uploadAfter.set(id, Infinity);
			this.again.add(id);
		}
		this.named.clear();
		this.sync();
	}

	/** Look at the canvas: upload what the list lacks, and fetch what the canvas lacks. */
	sync(): void {
		if (this.stopped) return;
		const now = Date.now();
		const unsaved = new Set<string>();
		let retryAt = Infinity;
		for (const [id, file] of this.options.editor.images()) {
			const ref = this.listed.get(id);
			if (file === null) {
				if (ref !== undefined) retryAt = Math.min(retryAt, this.fetch(ref, now));
			} else if (ref === undefined) {
				unsaved.add(id);
				if (!this.uploaded.has(id)) retryAt = Math.min(retryAt, this.store(file, now));
			}
		}
		clearTimeout(this.retryTimer);
		if (retryAt !== Infinity) {
			this.retryTimer = setTimeout(() => this.sync(), Math.max(0, retryAt - now));
		}
		const before = this.unsaved;
		this.unsaved = unsaved;
		if (unsaved.size !== before.size || [...unsaved].some((id) => !before.has(id))) {
			this.options.onChange();
		}
	}

	/** Upload a file, unless that is under way or has to wait. Returns when to look again. */
	private store(file: CanvasFile, now: number): number {
		const { id } = file;
		if (this.uploading.has(id) || !this.options.mayUpload()) return Infinity;
		const after = this.uploadAfter.get(id) ?? 0;
		if (after > now) return after;
		this.uploading.add(id);
		this.options.transport.upload(file).then(
			(hash) => {
				this.uploading.delete(id);
				this.uploadAfter.delete(id);
				if (this.stopped) return;
				this.uploaded.set(id, { id, hash, mimeType: file.mimeType });
				this.options.onChange();
			},
			(error: unknown) => {
				this.uploading.delete(id);
				if (this.stopped) return;
				this.failed(this.uploadAfter, id, error, 'store');
			}
		);
		return Infinity;
	}

	/** Fetch a file the canvas lacks, unless that is under way or has to wait. */
	private fetch(ref: FileRef, now: number): number {
		const { id } = ref;
		if (this.downloading.has(id)) return Infinity;
		const after = this.downloadAfter.get(id) ?? 0;
		if (after > now) return after;
		this.downloading.add(id);
		this.options.transport.download(ref).then(
			(dataURL) => {
				this.downloading.delete(id);
				this.downloadAfter.delete(id);
				if (this.stopped) return;
				this.options.editor.addFiles([{ id, mimeType: ref.mimeType, dataURL }]);
			},
			(error: unknown) => {
				this.downloading.delete(id);
				if (this.stopped) return;
				this.failed(this.downloadAfter, id, error, 'fetch');
			}
		);
		return Infinity;
	}

	private failed(after: Map<string, number>, id: string, error: unknown, what: string): void {
		const refused = error instanceof Refused;
		after.set(id, refused ? Infinity : Date.now() + RETRY_MS);
		const reason = error instanceof Error ? error.message : String(error);
		console.warn(
			`segl: could not ${what} the file of an image${refused ? '' : ', and will try again'}: ${reason}`
		);
		this.sync();
	}
}
