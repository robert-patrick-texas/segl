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
 * An image's bytes as the editor keeps them, a `data:` URL, and as segl
 * stores them, bytes (D2-028). Done by hand, without `fetch` or a
 * `FileReader`, so that it is the same in a browser and in a unit test, and
 * asks the network for nothing.
 */

export interface DataUrl {
	/** The type the URL names, in lower case, or `''` when it names none. */
	mimeType: string;
	bytes: Uint8Array;
}

const CHUNK = 0x8000;

/** Return what a `data:` URL holds, or null when the text is not one. */
export function dataUrlToBytes(url: string): DataUrl | null {
	if (!url.startsWith('data:')) return null;
	const comma = url.indexOf(',');
	if (comma === -1) return null;
	const [type = '', ...parameters] = url.slice(5, comma).split(';');
	const payload = url.slice(comma + 1);
	try {
		const binary = parameters.includes('base64') ? atob(payload) : unescaped(payload);
		const bytes = new Uint8Array(binary.length);
		for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
		return { mimeType: type.trim().toLowerCase(), bytes };
	} catch {
		// Not base64, or a percent sign that starts no byte.
		return null;
	}
}

/** The bytes of percent-encoded text, one character to a byte. */
function unescaped(payload: string): string {
	const utf8 = new TextEncoder().encode(decodeURIComponent(payload));
	let binary = '';
	for (const byte of utf8) binary += String.fromCharCode(byte);
	return binary;
}

/** Return bytes as a base64 `data:` URL of this type, which is what the editor makes. */
export function bytesToDataUrl(mimeType: string, bytes: Uint8Array): string {
	let binary = '';
	// In pieces: one call with every byte as an argument overflows the stack.
	for (let start = 0; start < bytes.length; start += CHUNK) {
		binary += String.fromCharCode(...bytes.subarray(start, start + CHUNK));
	}
	return `data:${mimeType};base64,${btoa(binary)}`;
}
