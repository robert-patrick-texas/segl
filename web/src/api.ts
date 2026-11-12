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

/** The HTTP routes this page calls (docs/API.md). Every URL is under segl's root. */

import { isHash, parseFileRefs, type FileRef } from './collab/files.ts';
import { apiUrl, type AppConfig } from './config.ts';
import { parseRevisions, type RevisionInfo } from './history.ts';

export interface SlotInfo {
	number: number;
	title: string;
	epoch: number;
	savedAt: string;
}

export interface SlotScene {
	/** The stored document, as the editor saved it. The canvas adapter reads it. */
	scene: unknown;
	epoch: number;
	savedAt: string;
	editorLabel: string;
	/** Which bytes the file ids of the scene's images mean. */
	files: FileRef[];
}

/** A response segl sent with an error status, or one that is not what docs/API.md says. */
export class ApiError extends Error {
	readonly status: number;
	readonly code: string;
	/** The seconds a `Retry-After` header named, or null. */
	readonly retryAfter: number | null;

	constructor(status: number, code: string, message: string, retryAfter: number | null = null) {
		super(message);
		this.name = 'ApiError';
		this.status = status;
		this.code = code;
		this.retryAfter = retryAfter;
	}
}

/** `Retry-After` as whole seconds. segl never sends its other form, a date. */
function retryAfter(response: Response): number | null {
	const value = response.headers.get('Retry-After');
	return value !== null && /^\d+$/.test(value) ? Number(value) : null;
}

function getJson(url: URL, signal?: AbortSignal): Promise<unknown> {
	return requestJson(url, { signal });
}

async function requestJson(url: URL, init: RequestInit): Promise<unknown> {
	const response = await fetch(url, {
		...init,
		headers: { Accept: 'application/json', ...init.headers }
	});
	let body: unknown;
	try {
		body = await response.json();
	} catch {
		throw new ApiError(response.status, 'not_json', `${url.pathname} did not return JSON`);
	}
	if (!response.ok) {
		const { error, message } = (body ?? {}) as { error?: unknown; message?: unknown };
		throw new ApiError(
			response.status,
			typeof error === 'string' ? error : 'unknown',
			typeof message === 'string' ? message : `${url.pathname} answered ${response.status}`,
			retryAfter(response)
		);
	}
	return body;
}

function isSlotInfo(value: unknown): value is SlotInfo {
	if (typeof value !== 'object' || value === null) return false;
	const slot = value as Record<string, unknown>;
	return typeof slot['number'] === 'number' && typeof slot['title'] === 'string';
}

/** The nine slots in number order. */
export async function fetchSlots(config: AppConfig, signal?: AbortSignal): Promise<SlotInfo[]> {
	const url = apiUrl(config, 'slots');
	const body = (await getJson(url, signal)) as { slots?: unknown };
	if (!Array.isArray(body?.slots) || !body.slots.every(isSlotInfo)) {
		throw new ApiError(200, 'unexpected', `${url.pathname} did not return the slot list`);
	}
	return body.slots;
}

/** The header a mutation carries when this browser has the edit token. */
export const EDIT_TOKEN_HEADER = 'X-Segl-Edit-Token';

/**
 * Give a slot a new title. The server trims it, stores it, and tells every
 * browser on the slot. Returns the slot as stored. `editToken` is this
 * browser's stored token, or `''`. It goes in a header, never in the URL.
 */
export async function renameSlot(
	config: AppConfig,
	slot: number,
	title: string,
	editToken: string,
	signal?: AbortSignal
): Promise<SlotInfo> {
	const url = apiUrl(config, `slots/${slot}`);
	const body = await requestJson(url, {
		method: 'PATCH',
		headers: {
			'Content-Type': 'application/json',
			...(editToken === '' ? {} : { [EDIT_TOKEN_HEADER]: editToken })
		},
		body: JSON.stringify({ title }),
		signal
	});
	if (!isSlotInfo(body)) {
		throw new ApiError(200, 'unexpected', `${url.pathname} did not return the slot`);
	}
	return body;
}

/** One slot's head scene. */
export async function fetchScene(
	config: AppConfig,
	slot: number,
	signal?: AbortSignal
): Promise<SlotScene> {
	const url = apiUrl(config, `slots/${slot}/scene`);
	const body = (await getJson(url, signal)) as Partial<SlotScene> | null;
	if (typeof body !== 'object' || body === null || typeof body.epoch !== 'number') {
		throw new ApiError(200, 'unexpected', `${url.pathname} did not return a scene`);
	}
	return {
		scene: body.scene,
		epoch: body.epoch,
		savedAt: String(body.savedAt ?? ''),
		editorLabel: String(body.editorLabel ?? ''),
		// A list this page cannot read leaves the images without their files,
		// and the rest of the scene still loads.
		files: parseFileRefs(body.files) ?? []
	};
}

/** A slot's history, newest first, without the scenes (S-005). */
export async function fetchRevisions(
	config: AppConfig,
	slot: number,
	signal?: AbortSignal
): Promise<RevisionInfo[]> {
	const url = apiUrl(config, `slots/${slot}/revisions`);
	const body = (await getJson(url, signal)) as { revisions?: unknown } | null;
	const revisions = parseRevisions(body?.revisions);
	if (revisions === null) {
		throw new ApiError(200, 'unexpected', `${url.pathname} did not return the history`);
	}
	return revisions;
}

/**
 * Put one of a slot's revisions in place of its scene. The server keeps the
 * scene that is replaced as a revision first, and then sends the restored one
 * to every browser on the slot, this one included, over the socket.
 * `displayName` is who restored, for the history. `editToken` is this
 * browser's stored token, or `''`. It goes in a header, never in the URL.
 */
export async function restoreRevision(
	config: AppConfig,
	slot: number,
	revision: number,
	displayName: string | null,
	editToken: string,
	signal?: AbortSignal
): Promise<{ revision: number; epoch: number }> {
	const url = apiUrl(config, `slots/${slot}/restore`);
	const body = (await requestJson(url, {
		method: 'POST',
		headers: {
			'Content-Type': 'application/json',
			...(editToken === '' ? {} : { [EDIT_TOKEN_HEADER]: editToken })
		},
		body: JSON.stringify({ revision, displayName }),
		signal
	})) as { revision?: unknown; epoch?: unknown } | null;
	if (!Number.isInteger(body?.revision) || !Number.isInteger(body?.epoch)) {
		throw new ApiError(200, 'unexpected', `${url.pathname} did not return the new revision`);
	}
	return { revision: body!.revision as number, epoch: body!.epoch as number };
}

/**
 * Store the bytes of an image's file and return their SHA-256, the name they
 * are fetched by. `mimeType` is the kind of image the editor says it is.
 */
export async function uploadAsset(
	config: AppConfig,
	slot: number,
	bytes: Uint8Array,
	mimeType: string,
	editToken: string,
	signal?: AbortSignal
): Promise<string> {
	const url = apiUrl(config, `slots/${slot}/assets`);
	const body = (await requestJson(url, {
		method: 'POST',
		headers: {
			'Content-Type': mimeType,
			...(editToken === '' ? {} : { [EDIT_TOKEN_HEADER]: editToken })
		},
		// A copy in a buffer of its own: `bytes` may be a view into a larger one.
		body: new Blob([bytes.slice()]),
		signal
	})) as { hash?: unknown };
	if (!isHash(body?.hash)) {
		throw new ApiError(200, 'unexpected', `${url.pathname} did not return a hash`);
	}
	return body.hash;
}

/** The bytes stored under a hash. The server sends them as bytes and nothing else. */
export async function fetchAsset(
	config: AppConfig,
	hash: string,
	signal?: AbortSignal
): Promise<Uint8Array> {
	const url = apiUrl(config, `assets/${hash}`);
	const response = await fetch(url, { signal });
	if (!response.ok) {
		throw new ApiError(response.status, 'not_found', `${url.pathname} answered ${response.status}`);
	}
	return new Uint8Array(await response.arrayBuffer());
}

/**
 * Take the next display name from the server, such as `Alpha1`. Each call
 * takes one, and an address may make 30 calls a minute, so call it only for a
 * browser that has no label (`assignName` in names.ts).
 */
export async function allocateDisplayName(
	config: AppConfig,
	signal?: AbortSignal
): Promise<string> {
	const url = apiUrl(config, 'display-name');
	const body = (await requestJson(url, { method: 'POST', signal })) as { displayName?: unknown };
	if (typeof body?.displayName !== 'string' || body.displayName === '') {
		throw new ApiError(200, 'unexpected', `${url.pathname} did not return a display name`);
	}
	return body.displayName;
}
