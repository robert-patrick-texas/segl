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

import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import {
	FileSync,
	IMAGE_TYPES,
	Refused,
	RETRY_MS,
	isHash,
	parseFileRefs,
	type CanvasFile,
	type FileEditor,
	type FileRef,
	type FileTransport
} from './files.ts';

const A = 'a'.repeat(40);
const B = 'b'.repeat(40);

function file(id: string): CanvasFile {
	return { id, mimeType: 'image/png', dataURL: `data:image/png;base64,${id.slice(0, 4)}` };
}

function ref(id: string, hash = id.padEnd(64, '0')): FileRef {
	return { id, hash, mimeType: 'image/png' };
}

/** A canvas: which file ids its images name, and which of those files it holds. */
class Canvas implements FileEditor {
	named = new Set<string>();
	held = new Map<string, CanvasFile>();
	added: CanvasFile[] = [];

	images(): ReadonlyMap<string, CanvasFile | null> {
		return new Map([...this.named].map((id) => [id, this.held.get(id) ?? null]));
	}

	addFiles(files: readonly CanvasFile[]): void {
		for (const each of files) {
			this.added.push(each);
			if (!this.held.has(each.id)) this.held.set(each.id, each);
		}
	}

	/** The person placed an image: the element and its file. */
	place(id: string): void {
		this.named.add(id);
		this.held.set(id, file(id));
	}

	/** An image arrived from someone else: the element, without its file. */
	receive(id: string): void {
		this.named.add(id);
	}
}

interface Pending<Result> {
	resolve(value: Result): void;
	reject(error: unknown): void;
}

/** A server whose answers the test gives, one transfer at a time. */
class Transport implements FileTransport {
	uploads: { file: CanvasFile; answer: Pending<string> }[] = [];
	downloads: { ref: FileRef; answer: Pending<string> }[] = [];

	upload(sent: CanvasFile): Promise<string> {
		return new Promise((resolve, reject) => {
			this.uploads.push({ file: sent, answer: { resolve, reject } });
		});
	}

	download(asked: FileRef): Promise<string> {
		return new Promise((resolve, reject) => {
			this.downloads.push({ ref: asked, answer: { resolve, reject } });
		});
	}
}

interface Harness {
	canvas: Canvas;
	transport: Transport;
	sync: FileSync;
	changes: { count: number };
	editor: { may: boolean };
}

function start(): Harness {
	const canvas = new Canvas();
	const transport = new Transport();
	const changes = { count: 0 };
	const editor = { may: true };
	const sync = new FileSync({
		editor: canvas,
		transport,
		mayUpload: () => editor.may,
		onChange: () => {
			changes.count += 1;
		}
	});
	return { canvas, transport, sync, changes, editor };
}

/** Let the promises that are settled run their handlers. */
async function settle(): Promise<void> {
	await vi.advanceTimersByTimeAsync(0);
}

beforeEach(() => {
	vi.useFakeTimers();
	vi.spyOn(console, 'warn').mockImplementation(() => {});
});

afterEach(() => {
	vi.useRealTimers();
	vi.restoreAllMocks();
});

describe('parseFileRefs', () => {
	test('a list of files is kept, with only the three fields of each', () => {
		const sent = [{ ...ref(A), dataURL: 'data:,', created: 1 }, ref(B)];

		expect(parseFileRefs(sent)).toEqual([ref(A), ref(B)]);
		expect(parseFileRefs([])).toEqual([]);
	});

	test.each([...IMAGE_TYPES])('%s is a type the editor takes', (mimeType) => {
		expect(parseFileRefs([{ ...ref(A), mimeType }])).toEqual([{ ...ref(A), mimeType }]);
	});

	test.each([
		[null],
		[undefined],
		['files'],
		[{}],
		[[ref(A), null]],
		[[{ id: A, hash: 'a'.repeat(64) }]],
		[[{ ...ref(A), id: '' }]],
		[[{ ...ref(A), id: 'x'.repeat(65) }]],
		[[{ ...ref(A), id: '../x' }]],
		[[{ ...ref(A), id: 7 }]],
		[[{ ...ref(A), hash: 'A'.repeat(64) }]],
		[[{ ...ref(A), hash: 'a'.repeat(63) }]],
		[[{ ...ref(A), hash: `../${'a'.repeat(61)}` }]],
		[[{ ...ref(A), mimeType: 'text/html' }]],
		[[{ ...ref(A), mimeType: 'application/octet-stream' }]],
		[[{ ...ref(A), mimeType: ['image/png'] }]]
	])('%j is not a file list', (value) => {
		expect(parseFileRefs(value)).toBeNull();
	});

	test('a hash is 64 lowercase hex digits and nothing else', () => {
		expect(isHash('0123456789abcdef'.repeat(4))).toBe(true);
		expect(isHash(`${'a'.repeat(64)}\n`)).toBe(false);
		expect(isHash(7)).toBe(false);
	});
});

describe('a file the canvas holds and the list lacks', () => {
	test('it is uploaded, and then waits to be named to the server', async () => {
		const { canvas, transport, sync, changes } = start();
		canvas.place(A);

		sync.sync();

		expect(transport.uploads.map((each) => each.file)).toEqual([file(A)]);
		// Not saved, from the moment it is seen.
		expect(sync.busy()).toBe(true);
		expect(changes.count).toBe(1);
		expect(sync.unannounced()).toEqual([]);

		transport.uploads[0]!.answer.resolve('c'.repeat(64));
		await settle();

		expect(sync.unannounced()).toEqual([ref(A, 'c'.repeat(64))]);
		expect(changes.count).toBe(2);
		// Stored, and not yet in the list: still not saved.
		expect(sync.busy()).toBe(true);
	});

	test('once the session has named it, it counts as listed', async () => {
		const { canvas, transport, sync, changes } = start();
		canvas.place(A);
		sync.sync();
		transport.uploads[0]!.answer.resolve('c'.repeat(64));
		await settle();

		sync.announced(sync.unannounced());

		expect(sync.unannounced()).toEqual([]);
		expect(sync.busy()).toBe(false);
		expect(changes.count).toBe(3);
		// It is not uploaded or fetched again.
		sync.sync();
		expect(transport.uploads).toHaveLength(1);
		expect(transport.downloads).toEqual([]);
	});

	test('it is uploaded once, however often the canvas changes meanwhile', () => {
		const { canvas, transport, sync, changes } = start();
		canvas.place(A);

		for (let count = 0; count < 5; count += 1) sync.sync();

		expect(transport.uploads).toHaveLength(1);
		expect(changes.count).toBe(1);
	});

	test('two images of one file are one upload', () => {
		const { canvas, transport, sync } = start();
		canvas.place(A);
		canvas.place(A);
		canvas.place(B);

		sync.sync();

		expect(transport.uploads.map((each) => each.file.id)).toEqual([A, B]);
	});

	test('a browser that may not edit uploads nothing, until the server says it may', () => {
		const { canvas, transport, sync, editor } = start();
		editor.may = false;
		canvas.place(A);

		sync.sync();
		expect(transport.uploads).toEqual([]);

		// Once the server says this browser may edit, the next look uploads.
		editor.may = true;
		sync.sync();
		expect(transport.uploads).toHaveLength(1);
	});

	test('a file whose image was deleted before the upload ended is not named', async () => {
		const { canvas, transport, sync } = start();
		canvas.place(A);
		sync.sync();
		canvas.named.delete(A);
		sync.sync();
		expect(sync.busy()).toBe(false);

		transport.uploads[0]!.answer.resolve('c'.repeat(64));
		await settle();

		expect(sync.unannounced()).toEqual([]);
		// An undo brings the image back, and the upload is not repeated.
		canvas.named.add(A);
		sync.sync();
		expect(sync.unannounced()).toEqual([ref(A, 'c'.repeat(64))]);
		expect(transport.uploads).toHaveLength(1);
	});

	test('an upload that fails is tried again after a wait', async () => {
		const { canvas, transport, sync } = start();
		canvas.place(A);
		sync.sync();

		transport.uploads[0]!.answer.reject(new TypeError('Failed to fetch'));
		await settle();

		expect(sync.busy()).toBe(true);
		expect(console.warn).toHaveBeenCalledTimes(1);
		// Not at once, however often the canvas changes.
		sync.sync();
		await vi.advanceTimersByTimeAsync(RETRY_MS - 1);
		expect(transport.uploads).toHaveLength(1);

		await vi.advanceTimersByTimeAsync(1);
		expect(transport.uploads).toHaveLength(2);
		transport.uploads[1]!.answer.resolve('c'.repeat(64));
		await settle();
		expect(sync.unannounced()).toEqual([ref(A, 'c'.repeat(64))]);
	});

	test('an upload the server refuses is not tried again, and the file stays unsaved', async () => {
		const { canvas, transport, sync } = start();
		canvas.place(A);
		sync.sync();

		transport.uploads[0]!.answer.reject(new Refused('The body is larger than 10 bytes.'));
		await settle();
		await vi.advanceTimersByTimeAsync(10 * RETRY_MS);
		sync.sync();

		expect(transport.uploads).toHaveLength(1);
		// The bar goes on saying it is not saved, which is true.
		expect(sync.busy()).toBe(true);
		expect(console.warn).toHaveBeenCalledWith(
			'segl: could not store the file of an image: The body is larger than 10 bytes.'
		);
	});
});

describe('a file the list names and the canvas lacks', () => {
	test('it is fetched and handed to the editor', async () => {
		const { canvas, transport, sync, changes } = start();
		canvas.receive(A);

		// The image is there. Nothing can be done until the list names its file.
		sync.sync();
		expect(transport.downloads).toEqual([]);
		expect(sync.busy()).toBe(false);

		sync.learn([ref(A)]);
		expect(transport.downloads.map((each) => each.ref)).toEqual([ref(A)]);
		transport.downloads[0]!.answer.resolve('data:image/png;base64,AAAA');
		await settle();

		expect(canvas.added).toEqual([
			{ id: A, mimeType: 'image/png', dataURL: 'data:image/png;base64,AAAA' }
		]);
		// Nothing of it is this browser's to save or to name.
		sync.sync();
		expect(sync.busy()).toBe(false);
		expect(sync.unannounced()).toEqual([]);
		expect(transport.uploads).toEqual([]);
		expect(transport.downloads).toHaveLength(1);
		expect(changes.count).toBe(0);
	});

	test('the list can come first, and the image later', () => {
		const { canvas, transport, sync } = start();
		sync.learn([ref(A), ref(B)]);
		expect(transport.downloads).toEqual([]);

		canvas.receive(B);
		sync.sync();

		// Only the file an image on the canvas names.
		expect(transport.downloads.map((each) => each.ref)).toEqual([ref(B)]);
	});

	test('it is fetched once, however often the canvas changes meanwhile', () => {
		const { canvas, transport, sync } = start();
		canvas.receive(A);
		sync.learn([ref(A)]);

		for (let count = 0; count < 5; count += 1) sync.sync();

		expect(transport.downloads).toHaveLength(1);
	});

	test('a viewer fetches too', () => {
		const { canvas, transport, sync, editor } = start();
		editor.may = false;
		canvas.receive(A);

		sync.learn([ref(A)]);

		expect(transport.downloads).toHaveLength(1);
	});

	test('a fetch that fails is tried again after a wait', async () => {
		const { canvas, transport, sync } = start();
		canvas.receive(A);
		sync.learn([ref(A)]);

		transport.downloads[0]!.answer.reject(new TypeError('Failed to fetch'));
		await settle();
		await vi.advanceTimersByTimeAsync(RETRY_MS - 1);
		expect(transport.downloads).toHaveLength(1);
		await vi.advanceTimersByTimeAsync(1);

		expect(transport.downloads).toHaveLength(2);
		transport.downloads[1]!.answer.resolve('data:image/png;base64,AAAA');
		await settle();
		expect(canvas.held.has(A)).toBe(true);
	});

	test('a file the server does not have is not asked for again', async () => {
		const { canvas, transport, sync } = start();
		canvas.receive(A);
		sync.learn([ref(A)]);

		transport.downloads[0]!.answer.reject(new Refused('Not Found.'));
		await settle();
		await vi.advanceTimersByTimeAsync(10 * RETRY_MS);
		sync.sync();

		expect(transport.downloads).toHaveLength(1);
		expect(console.warn).toHaveBeenCalledWith(
			'segl: could not fetch the file of an image: Not Found.'
		);
	});

	test('a file id keeps the bytes it was first given', () => {
		const { canvas, transport, sync } = start();
		sync.learn([ref(A, '1'.repeat(64))]);

		sync.learn([ref(A, '2'.repeat(64))]);
		canvas.receive(A);
		sync.sync();

		expect(transport.downloads.map((each) => each.ref.hash)).toEqual(['1'.repeat(64)]);
	});
});

describe('a new scene from the server', () => {
	test('its list replaces what was known, and an uploaded file it lacks is named again', async () => {
		const { canvas, transport, sync } = start();
		canvas.place(A);
		sync.sync();
		transport.uploads[0]!.answer.resolve('c'.repeat(64));
		await settle();
		sync.announced(sync.unannounced());
		expect(sync.busy()).toBe(false);

		// The server was restarted before it had written the list.
		sync.reset([]);

		expect(sync.busy()).toBe(true);
		expect(sync.unannounced()).toEqual([ref(A, 'c'.repeat(64))]);
		// The bytes are still there, so there is no second upload.
		expect(transport.uploads).toHaveLength(1);
	});

	test('a file its list names needs no naming', async () => {
		const { canvas, transport, sync } = start();
		canvas.place(A);
		sync.sync();
		transport.uploads[0]!.answer.resolve('c'.repeat(64));
		await settle();

		sync.reset([ref(A, 'c'.repeat(64))]);

		expect(sync.unannounced()).toEqual([]);
		expect(sync.busy()).toBe(false);
	});
});

describe('bytes the server lost', () => {
	async function named(harness: Harness): Promise<void> {
		harness.canvas.place(A);
		harness.sync.sync();
		harness.transport.uploads[0]!.answer.resolve('c'.repeat(64));
		await settle();
		harness.sync.announced(harness.sync.unannounced());
	}

	test('they are uploaded once more', async () => {
		const harness = start();
		await named(harness);

		harness.sync.lost();

		expect(harness.sync.busy()).toBe(true);
		expect(harness.transport.uploads).toHaveLength(2);
		harness.transport.uploads[1]!.answer.resolve('c'.repeat(64));
		await settle();
		expect(harness.sync.unannounced()).toEqual([ref(A, 'c'.repeat(64))]);
	});

	test('after a second loss the file is left alone, and stays unsaved', async () => {
		const harness = start();
		await named(harness);
		harness.sync.lost();
		harness.transport.uploads[1]!.answer.resolve('c'.repeat(64));
		await settle();
		harness.sync.announced(harness.sync.unannounced());

		harness.sync.lost();
		await vi.advanceTimersByTimeAsync(10 * RETRY_MS);

		expect(harness.transport.uploads).toHaveLength(2);
		expect(harness.sync.busy()).toBe(true);
	});

	test('a file a later scene listed is not uploaded again', async () => {
		const harness = start();
		await named(harness);
		// The server's own list, after a reconnect, has the file this browser named.
		harness.sync.reset([ref(A, 'c'.repeat(64))]);

		// Some other file's bytes were lost.
		harness.sync.lost();

		expect(harness.transport.uploads).toHaveLength(1);
		expect(harness.sync.busy()).toBe(false);
	});

	test('a file that was listed by the server itself is not touched', async () => {
		const harness = start();
		harness.sync.learn([ref(B)]);
		harness.canvas.receive(B);
		await named(harness);

		harness.sync.lost();

		expect(harness.transport.uploads.map((each) => each.file.id)).toEqual([A, A]);
	});
});

describe('stopping', () => {
	test('transfers under way end unheard, and nothing more is started', async () => {
		const { canvas, transport, sync, changes } = start();
		const C = 'c'.repeat(40);
		canvas.place(A);
		canvas.receive(B);
		canvas.receive(C);
		sync.learn([ref(B), ref(C)]);
		const before = changes.count;

		sync.stop();
		transport.uploads[0]!.answer.resolve('c'.repeat(64));
		// One fetch fails and one arrives, for a canvas that is being taken down.
		transport.downloads[0]!.answer.reject(new TypeError('Failed to fetch'));
		transport.downloads[1]!.answer.resolve('data:image/png;base64,AAAA');
		await settle();
		await vi.advanceTimersByTimeAsync(10 * RETRY_MS);
		sync.sync();

		expect(canvas.added).toEqual([]);
		expect(changes.count).toBe(before);
		expect(transport.uploads).toHaveLength(1);
		expect(transport.downloads).toHaveLength(2);
		expect(console.warn).not.toHaveBeenCalled();
	});
});
