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

/** The HTTP routes this page reads (docs/API.md). Every URL is under segl's root. */

import { apiUrl, type AppConfig } from './config.ts';

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
	files: unknown[];
}

/** A response segl sent with an error status, or one that is not what docs/API.md says. */
export class ApiError extends Error {
	readonly status: number;
	readonly code: string;

	constructor(status: number, code: string, message: string) {
		super(message);
		this.name = 'ApiError';
		this.status = status;
		this.code = code;
	}
}

async function getJson(url: URL, signal?: AbortSignal): Promise<unknown> {
	const response = await fetch(url, { headers: { Accept: 'application/json' }, signal });
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
			typeof message === 'string' ? message : `${url.pathname} answered ${response.status}`
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
		files: Array.isArray(body.files) ? body.files : []
	};
}
