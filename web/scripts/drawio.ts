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
 * drawio's editor, for Diagram mode on slot 9 (D2-039).
 *
 * The build fetches the pinned release's `draw.war` from GitHub, checks it by
 * the SHA-256 in versions.toml, and unpacks its web files, unmodified, into
 * the build as `drawio/`. `WEB-INF/` and `META-INF/` stay out: segl runs none
 * of drawio's Java. Git holds none of it. The war and its unpacked files are
 * kept in a cache folder, `~/.cache/segl/drawio` unless `SEGL_DRAWIO_CACHE`
 * names another, so a second build fetches nothing.
 *
 * Two files are segl's own: drawio's settings files, `js/PreConfig.js` and
 * `js/PostConfig.js`, which a site may replace. The build lays `web/drawio/`
 * over the copy. No other file of drawio's changes.
 */
import { createHash } from 'node:crypto';
import {
	cpSync,
	createReadStream,
	existsSync,
	mkdirSync,
	readFileSync,
	renameSync,
	rmSync,
	statSync,
	writeFileSync
} from 'node:fs';
import { homedir } from 'node:os';
import { dirname, extname, join, normalize, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { inflateRawSync } from 'node:zlib';
import type { Plugin } from 'vite';

/** drawio's release, as versions.toml pins it. */
export interface DrawioPin {
	version: string;
	/** The SHA-256 of the release's `draw.war`, in hex. */
	sha256: string;
}

/** The files segl lays over drawio's: its two settings files. */
export const SETTINGS_FILES = ['js/PreConfig.js', 'js/PostConfig.js'] as const;

/** segl's own settings files, at the paths they replace. */
export const SEGL_SETTINGS = fileURLToPath(new URL('../drawio', import.meta.url));

const VERSIONS = new URL('../../versions.toml', import.meta.url);

/** Return the `[drawio]` table of versions.toml's text. */
export function drawioPin(toml: string): DrawioPin {
	const found: Record<string, string> = {};
	let table = '';
	for (const raw of toml.split('\n')) {
		const line = raw.trim();
		const header = /^\[([^\]]+)\]$/.exec(line);
		if (header) {
			table = header[1]!.trim();
			continue;
		}
		const entry = table === 'drawio' ? /^(\w+)\s*=\s*"([^"]+)"\s*(?:#.*)?$/.exec(line) : null;
		if (entry) found[entry[1]!] = entry[2]!;
	}
	const { version, sha256 } = found;
	if (version === undefined || !/^\d+\.\d+\.\d+$/.test(version)) {
		throw new Error('versions.toml has no drawio version, such as version = "32.7.7"');
	}
	if (sha256 === undefined || !/^[0-9a-f]{64}$/.test(sha256)) {
		throw new Error('versions.toml has no SHA-256 of drawio\'s war, as sha256 = "<64 hex>"');
	}
	return { version, sha256 };
}

/** Return where GitHub serves a release's war. */
export function releaseUrl(version: string): string {
	return `https://github.com/jgraph/drawio/releases/download/v${version}/draw.war`;
}

/** Return the cache folder: `SEGL_DRAWIO_CACHE`, or `~/.cache/segl/drawio`. */
export function cacheFolder(env: NodeJS.ProcessEnv = process.env): string {
	return resolve(env['SEGL_DRAWIO_CACHE'] || join(homedir(), '.cache', 'segl', 'drawio'));
}

/** One file of a zip archive, as its central directory names it. */
export interface ZipEntry {
	name: string;
	method: number;
	compressedSize: number;
	size: number;
	/** Where its local header starts. */
	offset: number;
}

/** Return the files a zip archive holds, folders left out. */
export function zipEntries(zip: Buffer): ZipEntry[] {
	// The end record is the last 22 bytes, unless a comment follows it.
	let end = -1;
	for (let at = zip.length - 22; at >= Math.max(0, zip.length - 22 - 0xffff); at -= 1) {
		if (zip.readUInt32LE(at) === 0x06054b50) {
			end = at;
			break;
		}
	}
	if (end < 0) throw new Error('not a zip archive: it has no end record');
	const count = zip.readUInt16LE(end + 10);
	let at = zip.readUInt32LE(end + 16);
	const entries: ZipEntry[] = [];
	for (let index = 0; index < count; index += 1) {
		if (zip.readUInt32LE(at) !== 0x02014b50) throw new Error('a zip entry has no central header');
		const nameLength = zip.readUInt16LE(at + 28);
		const extraLength = zip.readUInt16LE(at + 30);
		const commentLength = zip.readUInt16LE(at + 32);
		const name = zip.toString('utf8', at + 46, at + 46 + nameLength);
		const entry = {
			name,
			method: zip.readUInt16LE(at + 10),
			compressedSize: zip.readUInt32LE(at + 20),
			size: zip.readUInt32LE(at + 24),
			offset: zip.readUInt32LE(at + 42)
		};
		if (!name.endsWith('/')) entries.push(entry);
		at += 46 + nameLength + extraLength + commentLength;
	}
	return entries;
}

/** Return the bytes of one entry. */
export function entryBytes(zip: Buffer, entry: ZipEntry): Buffer {
	const at = entry.offset;
	if (zip.readUInt32LE(at) !== 0x04034b50) throw new Error(`${entry.name}: no local header`);
	const start = at + 30 + zip.readUInt16LE(at + 26) + zip.readUInt16LE(at + 28);
	const stored = zip.subarray(start, start + entry.compressedSize);
	let bytes: Buffer;
	if (entry.method === 0) bytes = Buffer.from(stored);
	else if (entry.method === 8) bytes = inflateRawSync(stored);
	else throw new Error(`${entry.name}: compression method ${entry.method} is not read here`);
	if (bytes.length !== entry.size) throw new Error(`${entry.name}: unpacked to the wrong size`);
	return bytes;
}

/** Whether a war entry is one of drawio's web files: not its Java, and a plain path. */
export function isWebFile(name: string): boolean {
	if (name.startsWith('WEB-INF/') || name.startsWith('META-INF/')) return false;
	const parts = name.split('/');
	return (
		!name.startsWith('/') && !parts.includes('..') && !parts.includes('') && !name.includes('\\')
	);
}

/** Unpack a war's web files into `target`. Return how many there were. */
export function unpackWar(zip: Buffer, target: string): number {
	let count = 0;
	for (const entry of zipEntries(zip)) {
		if (!isWebFile(entry.name)) continue;
		const file = join(target, ...entry.name.split('/'));
		mkdirSync(dirname(file), { recursive: true });
		writeFileSync(file, entryBytes(zip, entry));
		count += 1;
	}
	return count;
}

/** Return the SHA-256 of some bytes, in hex. */
export function sha256(bytes: Buffer): string {
	return createHash('sha256').update(bytes).digest('hex');
}

/**
 * Return the folder of the pinned release's web files, fetching and
 * unpacking it first when the cache lacks it.
 *
 * A war whose hash is not the pin's is refused, and nothing is unpacked.
 */
export async function ensureDrawio(
	pin: DrawioPin,
	cache: string = cacheFolder(),
	download: (url: string) => Promise<Buffer> = fetchBytes
): Promise<string> {
	const folder = join(cache, pin.version);
	const done = join(folder, '.segl-sha256');
	if (existsSync(done) && readFileSync(done, 'utf8').trim() === pin.sha256) return folder;
	mkdirSync(cache, { recursive: true });
	const war = join(cache, `draw-${pin.version}.war`);
	let bytes: Buffer = existsSync(war) ? readFileSync(war) : Buffer.alloc(0);
	if (sha256(bytes) !== pin.sha256) {
		console.log(`drawio: fetching ${releaseUrl(pin.version)}`);
		bytes = await download(releaseUrl(pin.version));
		const found = sha256(bytes);
		if (found !== pin.sha256) {
			throw new Error(`drawio ${pin.version}: the war's SHA-256 is ${found}, not ${pin.sha256}`);
		}
		writeFileSync(war, bytes);
	}
	// Unpacked beside its place and then moved, so a stopped build leaves no half.
	const partial = `${folder}.partial`;
	rmSync(partial, { recursive: true, force: true });
	const count = unpackWar(bytes, partial);
	for (const path of SETTINGS_FILES) {
		if (!existsSync(join(partial, path))) {
			throw new Error(`drawio ${pin.version} has no ${path}, which segl replaces`);
		}
	}
	writeFileSync(join(partial, '.segl-sha256'), `${pin.sha256}\n`);
	rmSync(folder, { recursive: true, force: true });
	renameSync(partial, folder);
	console.log(`drawio: ${count} web files of ${pin.version} in ${folder}`);
	return folder;
}

async function fetchBytes(url: string): Promise<Buffer> {
	const response = await fetch(url);
	if (!response.ok) throw new Error(`${url}: HTTP ${response.status}`);
	return Buffer.from(await response.arrayBuffer());
}

/** Copy drawio's web files into `target`, with segl's settings files over drawio's. */
export function copyDrawio(source: string, target: string, settings: string = SEGL_SETTINGS): void {
	cpSync(source, target, {
		recursive: true,
		filter: (path) => !path.endsWith(`${sep}.segl-sha256`)
	});
	for (const path of SETTINGS_FILES) cpSync(join(settings, path), join(target, path));
}

/** Return the file a dev-server request under `drawio/` names, or null. */
export function drawioFile(requestPath: string, folders: readonly string[]): string | null {
	let path: string;
	try {
		path = decodeURIComponent(requestPath.split('?')[0] ?? '');
	} catch {
		return null;
	}
	for (const folder of folders) {
		const file = normalize(join(folder, path));
		if (!file.startsWith(folder + sep)) return null;
		if (statSync(file, { throwIfNoEntry: false })?.isFile()) return file;
	}
	return null;
}

const DEV_TYPES: Record<string, string> = {
	'.html': 'text/html; charset=utf-8',
	'.js': 'text/javascript; charset=utf-8',
	'.css': 'text/css; charset=utf-8',
	'.svg': 'image/svg+xml',
	'.png': 'image/png',
	'.gif': 'image/gif',
	'.json': 'application/json',
	'.xml': 'application/xml',
	'.txt': 'text/plain; charset=utf-8'
};

export function drawio(): Plugin {
	let outDir = '';
	let building = false;
	let folder = '';
	return {
		name: 'segl:drawio',
		configResolved(config) {
			outDir = resolve(config.root, config.build.outDir);
			building = config.command === 'build';
		},
		async buildStart() {
			// Vitest runs this config's plugins too: it needs no editor.
			if (process.env['VITEST']) return;
			folder = await ensureDrawio(drawioPin(readFileSync(VERSIONS, 'utf8')));
		},
		configureServer(server) {
			server.middlewares.use('/drawio', (request, response, next) => {
				// segl's settings files first, then drawio's own.
				const file = drawioFile(request.url ?? '', [SEGL_SETTINGS, folder]);
				if (!file || folder === '') return next();
				response.setHeader('Content-Type', DEV_TYPES[extname(file)] ?? 'application/octet-stream');
				createReadStream(file).pipe(response);
			});
		},
		writeBundle() {
			if (!building) return;
			copyDrawio(folder, join(outDir, 'drawio'));
		}
	};
}
