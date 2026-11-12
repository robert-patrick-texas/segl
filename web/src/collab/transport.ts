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
 * How the files of images travel: the two HTTP routes in docs/API.md,
 * "Uploaded files". The editor keeps a file as a `data:` URL, and the
 * server keeps its bytes, so each way goes through `dataurl.ts`.
 */
import { ApiError, fetchAsset, uploadAsset } from '../api.ts';
import type { AppConfig } from '../config.ts';
import { bytesToDataUrl, dataUrlToBytes } from './dataurl.ts';
import { Refused, type FileTransport } from './files.ts';

/**
 * Whether asking again could get another answer. A refusal, such as a file
 * that is too large, or a hash the server does not have, will not change. A
 * busy or failing server may.
 */
export function isFinal(error: unknown): boolean {
	if (!(error instanceof ApiError)) return false;
	const { status } = error;
	return status >= 400 && status < 500 && status !== 408 && status !== 429;
}

async function unlessFinal<Result>(work: () => Promise<Result>): Promise<Result> {
	try {
		return await work();
	} catch (error) {
		if (isFinal(error)) throw new Refused((error as ApiError).message);
		throw error;
	}
}

/**
 * The transport for one slot. `editToken` is read at each upload, so a token
 * stored after the page loaded is used.
 */
export function httpTransport(
	config: AppConfig,
	slot: number,
	editToken: () => string
): FileTransport {
	return {
		upload(file) {
			const decoded = dataUrlToBytes(file.dataURL);
			if (decoded === null) return Promise.reject(new Refused('the file is not a data URL'));
			return unlessFinal(() =>
				uploadAsset(config, slot, decoded.bytes, file.mimeType, editToken())
			);
		},
		async download(ref) {
			const bytes = await unlessFinal(() => fetchAsset(config, ref.hash));
			return bytesToDataUrl(ref.mimeType, bytes);
		}
	};
}
