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

import { describe, expect, test } from 'vitest';
import {
	apiUrl,
	collabUrl,
	isInjectedConfig,
	loadConfig,
	resolveConfig,
	routerBasename,
	storageKey
} from './config.ts';

// The same build, on the pages docs/ARCHITECTURE.md names.
const board = resolveConfig(
	{ root: '../', editRequired: false },
	'https://dev.example.com/board/s/1'
);
const hostRoot = resolveConfig(
	{ root: '../', editRequired: true },
	'https://board.example.com/s/1'
);

describe('resolveConfig', () => {
	test('a slot page under /board/ finds the root one level up', () => {
		expect(board.rootUrl.href).toBe('https://dev.example.com/board/');
		expect(board.basePath).toBe('/board/');
		expect(board.editRequired).toBe(false);
	});

	test('the root page finds the root beside itself', () => {
		const config = resolveConfig(
			{ root: './', editRequired: false },
			'https://dev.example.com/board/'
		);

		expect(config.rootUrl.href).toBe('https://dev.example.com/board/');
	});

	test('at a host root the base path is /', () => {
		expect(hostRoot.rootUrl.href).toBe('https://board.example.com/');
		expect(hostRoot.basePath).toBe('/');
		expect(hostRoot.editRequired).toBe(true);
	});

	test('a deeper mount and a port are kept', () => {
		const config = resolveConfig(
			{ root: '../', editRequired: false },
			'https://dev.example.com:8443/tools/board/s/7'
		);

		expect(config.rootUrl.href).toBe('https://dev.example.com:8443/tools/board/');
		expect(config.basePath).toBe('/tools/board/');
	});

	test('a query and a fragment on the page are not part of the root', () => {
		const config = resolveConfig(
			{ root: '../', editRequired: false },
			'https://dev.example.com/board/s/1?x=1#e=token'
		);

		expect(config.rootUrl.href).toBe('https://dev.example.com/board/');
	});
});

describe('what comes from the root', () => {
	test('API URLs are under the mount', () => {
		expect(apiUrl(board, 'slots/4/scene').href).toBe(
			'https://dev.example.com/board/api/v1/slots/4/scene'
		);
		expect(apiUrl(hostRoot, 'config').href).toBe('https://board.example.com/api/v1/config');
	});

	test('the WebSocket follows the page: wss under https, ws under http', () => {
		expect(collabUrl(board, 3).href).toBe('wss://dev.example.com/board/collab?slot=3');
		const plain = resolveConfig({ root: '../', editRequired: false }, 'http://127.0.0.1:8888/s/3');
		expect(collabUrl(plain, 3).href).toBe('ws://127.0.0.1:8888/collab?slot=3');
	});

	test('the router basename has no trailing slash, except at a host root', () => {
		expect(routerBasename(board)).toBe('/board');
		expect(routerBasename(hostRoot)).toBe('/');
	});

	test('storage keys carry the base path, so two mounts stay separate', () => {
		expect(storageKey(board, 'lastSlot')).toBe('segl:/board/:lastSlot');
		expect(storageKey(hostRoot, 'lastSlot')).toBe('segl:/:lastSlot');
	});
});

describe('isInjectedConfig', () => {
	test.each([
		{ root: './', editRequired: false },
		{ root: '../', editRequired: true },
		{ root: '../../', editRequired: false }
	])('accepts %j', (value) => {
		expect(isInjectedConfig(value)).toBe(true);
	});

	test.each([
		undefined,
		null,
		'../',
		{},
		{ root: '../' },
		{ root: '../', editRequired: 'no' },
		{ root: '/board/', editRequired: false },
		{ root: 'https://elsewhere.example/', editRequired: false },
		{ root: '//elsewhere.example/', editRequired: false },
		{ root: '..', editRequired: false },
		{ root: '', editRequired: false }
	])('refuses %j', (value) => {
		expect(isInjectedConfig(value)).toBe(false);
	});
});

describe('loadConfig', () => {
	const never: typeof fetch = () => {
		throw new Error('the injected config needs no request');
	};

	test('uses what Python injected, without a request', async () => {
		const config = await loadConfig(
			{ root: '../', editRequired: true },
			'https://dev.example.com/board/s/2',
			never
		);

		expect(config.rootUrl.href).toBe('https://dev.example.com/board/');
		expect(config.editRequired).toBe(true);
	});

	test('on the dev server, the root is the host root and the API says whether a token is needed', async () => {
		const asked: string[] = [];
		const fetcher: typeof fetch = async (input) => {
			asked.push(String(input));
			return new Response(JSON.stringify({ editRequired: true }));
		};

		const config = await loadConfig(undefined, 'http://127.0.0.1:5173/s/1', fetcher);

		expect(asked).toEqual(['http://127.0.0.1:5173/api/v1/config']);
		expect(config.rootUrl.href).toBe('http://127.0.0.1:5173/');
		expect(config.basePath).toBe('/');
		expect(config.editRequired).toBe(true);
	});

	test('on the dev server, an error from Python is an error here', async () => {
		const fetcher: typeof fetch = async () => new Response('bad gateway', { status: 502 });

		await expect(loadConfig(undefined, 'http://127.0.0.1:5173/s/1', fetcher)).rejects.toThrow(
			'502'
		);
	});
});
