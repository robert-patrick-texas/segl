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

import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { deflateRawSync } from 'node:zlib';
import { afterEach, beforeEach, describe, expect, test } from 'vitest';
import {
	cacheFolder,
	copyDrawio,
	drawioFile,
	drawioPin,
	ensureDrawio,
	isWebFile,
	releaseUrl,
	SEGL_SETTINGS,
	SETTINGS_FILES,
	sha256,
	unpackWar,
	zipEntries
} from './drawio.ts';

/** A zip archive of these files, folders listed too, as a war has them. */
function zip(files: Record<string, string>, deflate = true): Buffer {
	const locals: Buffer[] = [];
	const centrals: Buffer[] = [];
	let offset = 0;
	const names = new Set<string>();
	for (const path of Object.keys(files)) {
		const parts = path.split('/');
		for (let i = 1; i < parts.length; i += 1) names.add(`${parts.slice(0, i).join('/')}/`);
		names.add(path);
	}
	for (const name of [...names].sort()) {
		const data = Buffer.from(name.endsWith('/') ? '' : files[name]!, 'utf8');
		const stored = deflate && data.length > 0 ? deflateRawSync(data) : data;
		const method = deflate && data.length > 0 ? 8 : 0;
		const nameBytes = Buffer.from(name, 'utf8');
		const local = Buffer.alloc(30);
		local.writeUInt32LE(0x04034b50, 0);
		local.writeUInt16LE(method, 8);
		local.writeUInt32LE(stored.length, 18);
		local.writeUInt32LE(data.length, 22);
		local.writeUInt16LE(nameBytes.length, 26);
		const central = Buffer.alloc(46);
		central.writeUInt32LE(0x02014b50, 0);
		central.writeUInt16LE(method, 10);
		central.writeUInt32LE(stored.length, 20);
		central.writeUInt32LE(data.length, 24);
		central.writeUInt16LE(nameBytes.length, 28);
		central.writeUInt32LE(offset, 42);
		locals.push(local, nameBytes, stored);
		centrals.push(central, nameBytes);
		offset += local.length + nameBytes.length + stored.length;
	}
	const directory = Buffer.concat(centrals);
	const end = Buffer.alloc(22);
	end.writeUInt32LE(0x06054b50, 0);
	end.writeUInt16LE(names.size, 10);
	end.writeUInt32LE(directory.length, 12);
	end.writeUInt32LE(offset, 16);
	return Buffer.concat([...locals, directory, end]);
}

const WAR = {
	'index.html': '<!doctype html>',
	'js/app.min.js': 'var app;',
	'js/PreConfig.js': '// drawio pre',
	'js/PostConfig.js': '// drawio post',
	'WEB-INF/web.xml': '<web-app/>',
	'META-INF/MANIFEST.MF': 'Manifest-Version: 1.0'
};

let root = '';

beforeEach(() => {
	root = mkdtempSync(join(tmpdir(), 'segl-drawio-'));
});

afterEach(() => {
	rmSync(root, { recursive: true, force: true });
});

describe('the pin', () => {
	const sha = 'e'.repeat(64);

	test('is read from versions.toml’s [drawio] table', () => {
		const toml = `[project]\nversion = "1.0.0"\n\n[drawio]\nversion = "32.7.7" # comment\nsha256 = "${sha}"\n`;

		expect(drawioPin(toml)).toEqual({ version: '32.7.7', sha256: sha });
	});

	test.each([
		['no table', '[project]\nversion = "1.0.0"\n'],
		['no hash', '[drawio]\nversion = "32.7.7"\n'],
		['a short hash', '[drawio]\nversion = "32.7.7"\nsha256 = "abc"\n'],
		['a range', `[drawio]\nversion = "^32.7"\nsha256 = "${sha}"\n`]
	])('is refused with %s', (_, toml) => {
		expect(() => drawioPin(toml)).toThrow();
	});

	test('is the repository’s own', () => {
		const pin = drawioPin(readFileSync(new URL('../../versions.toml', import.meta.url), 'utf8'));

		expect(pin.version).toMatch(/^\d+\.\d+\.\d+$/);
		expect(releaseUrl(pin.version)).toBe(
			`https://github.com/jgraph/drawio/releases/download/v${pin.version}/draw.war`
		);
	});
});

test('the cache is SEGL_DRAWIO_CACHE, or under the home folder', () => {
	expect(cacheFolder({ SEGL_DRAWIO_CACHE: '/srv/cache' })).toBe('/srv/cache');
	expect(cacheFolder({})).toMatch(/\.cache\/segl\/drawio$/);
});

describe('the war', () => {
	test('its files are read, folders left out, stored or deflated', () => {
		for (const deflate of [true, false]) {
			const entries = zipEntries(zip(WAR, deflate));

			expect(entries.map((entry) => entry.name).sort()).toEqual(Object.keys(WAR).sort());
		}
	});

	test('only the web files are unpacked, as they were', () => {
		const target = join(root, 'out');

		expect(unpackWar(zip(WAR), target)).toBe(4);

		expect(readFileSync(join(target, 'js/app.min.js'), 'utf8')).toBe('var app;');
		expect(existsSync(join(target, 'WEB-INF'))).toBe(false);
		expect(existsSync(join(target, 'META-INF'))).toBe(false);
	});

	test.each([
		['WEB-INF/classes/A.class', false],
		['META-INF/MANIFEST.MF', false],
		['../evil.js', false],
		['js/../../evil.js', false],
		['/etc/passwd', false],
		['js//x.js', false],
		['js\\x.js', false],
		['js/app.min.js', true],
		['index.html', true]
	])('%s is a web file: %s', (name, expected) => {
		expect(isWebFile(name)).toBe(expected);
	});

	test('a file that is not a zip archive is refused', () => {
		expect(() => zipEntries(Buffer.from('not a zip'))).toThrow(/no end record/);
	});
});

describe('ensureDrawio', () => {
	test('fetches the war once, checks it, and unpacks it', async () => {
		const war = zip(WAR);
		const pin = { version: '1.2.3', sha256: sha256(war) };
		const fetched: string[] = [];
		const download = async (url: string) => {
			fetched.push(url);
			return war;
		};

		const folder = await ensureDrawio(pin, root, download);
		const again = await ensureDrawio(pin, root, download);

		expect(folder).toBe(join(root, '1.2.3'));
		expect(again).toBe(folder);
		expect(fetched).toEqual([releaseUrl('1.2.3')]);
		expect(readFileSync(join(folder, 'index.html'), 'utf8')).toBe('<!doctype html>');
	});

	test('a war whose hash is not the pin’s is refused, and nothing is unpacked', async () => {
		const pin = { version: '1.2.3', sha256: 'a'.repeat(64) };

		await expect(ensureDrawio(pin, root, async () => zip(WAR))).rejects.toThrow(/SHA-256/);

		expect(existsSync(join(root, '1.2.3'))).toBe(false);
		expect(existsSync(join(root, 'draw-1.2.3.war'))).toBe(false);
	});

	test('a war kept in the cache is used again without a fetch', async () => {
		const war = zip(WAR);
		writeFileSync(join(root, 'draw-1.2.3.war'), war);

		const folder = await ensureDrawio({ version: '1.2.3', sha256: sha256(war) }, root, () => {
			throw new Error('no fetch');
		});

		expect(existsSync(join(folder, 'js/app.min.js'))).toBe(true);
	});

	test('a release without the settings files segl replaces is refused', async () => {
		const { 'js/PostConfig.js': _gone, ...rest } = WAR;
		const war = zip(rest);

		await expect(
			ensureDrawio({ version: '1.2.3', sha256: sha256(war) }, root, async () => war)
		).rejects.toThrow(/PostConfig/);
	});
});

test('the copy has segl’s settings files over drawio’s, and no cache mark', async () => {
	const war = zip(WAR);
	const folder = await ensureDrawio(
		{ version: '1.2.3', sha256: sha256(war) },
		root,
		async () => war
	);
	const target = join(root, 'dist', 'drawio');

	copyDrawio(folder, target);

	for (const path of SETTINGS_FILES) {
		expect(readFileSync(join(target, path), 'utf8')).toBe(
			readFileSync(join(SEGL_SETTINGS, path), 'utf8')
		);
	}
	expect(readFileSync(join(target, 'js/app.min.js'), 'utf8')).toBe('var app;');
	expect(existsSync(join(target, '.segl-sha256'))).toBe(false);
});

test('segl’s settings files keep drawio’s settings and add segl’s', () => {
	const pre = readFileSync(join(SEGL_SETTINGS, 'js/PreConfig.js'), 'utf8');
	const post = readFileSync(join(SEGL_SETTINGS, 'js/PostConfig.js'), 'utf8');

	expect(pre).toContain("urlParams['sync'] = 'manual';");
	expect(pre).toContain('window.EXPORT_URL = null;');
	expect(pre).toMatch(/defaultLibraries: '[^']*network[^']*cisco19/);
	expect(post).toContain('window.ICONSEARCH_PATH = null;');
	expect(post).toContain("event: 'readOnly'");
	// segl's files set no color on the diagram: drawio's shapes keep drawio's
	// (D2-039). A cursor's color comes from the page, worked out from the
	// connection id as the whiteboards' editor does (T18).
	expect(`${pre}${post}`).not.toMatch(
		/(fill|stroke|font|gradient|labelBackground|labelBorder|image)Color|#[0-9a-f]{3,6}\b/i
	);
	expect(post).toContain("arrow.setAttribute('fill', color);");
});

test('a dev-server path is a file in one of the folders, or nothing', () => {
	const first = join(root, 'segl');
	const second = join(root, 'drawio');
	mkdirSync(join(first, 'js'), { recursive: true });
	mkdirSync(join(second, 'js'), { recursive: true });
	writeFileSync(join(first, 'js/PreConfig.js'), 'segl');
	writeFileSync(join(second, 'js/PreConfig.js'), 'drawio');
	writeFileSync(join(second, 'index.html'), 'page');

	expect(drawioFile('/js/PreConfig.js?v=1', [first, second])).toBe(join(first, 'js/PreConfig.js'));
	expect(drawioFile('/index.html', [first, second])).toBe(join(second, 'index.html'));
	expect(drawioFile('/missing.js', [first, second])).toBeNull();
	expect(drawioFile('/../../etc/passwd', [first, second])).toBeNull();
	expect(drawioFile('/%E0%A4%A', [first, second])).toBeNull();
});
