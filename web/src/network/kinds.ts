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
 * The kinds of network object and their states (N-001, N-002, N-004; D2-038).
 * Nothing here knows the editor.
 */

/** The 12 device kinds. `other` is a device of none of the other kinds. */
export const DEVICE_KINDS = [
	'router',
	'switch',
	'firewall',
	'wireless_ap',
	'server',
	'workstation',
	'printer',
	'voip_phone',
	'mobile',
	'host',
	'cloud',
	'other'
] as const;

/** The 5 link kinds. Each is a line style. */
export const LINK_KINDS = ['cable', 'circuit', 'neighbor', 'relationship', 'connector'] as const;

/** What a person drew: it exists, it is planned, or it is to be removed. */
export const STATES = ['existing', 'planned', 'remove'] as const;

export type DeviceKind = (typeof DEVICE_KINDS)[number];
export type LinkKind = (typeof LINK_KINDS)[number];
export type ObjectType = DeviceKind | LinkKind;
export type State = (typeof STATES)[number];

/** What the library and the panel call each kind. */
export const KIND_NAMES: Readonly<Record<ObjectType, string>> = {
	router: 'Router',
	switch: 'Switch',
	firewall: 'Firewall',
	wireless_ap: 'Wi-Fi AP',
	server: 'Server',
	workstation: 'Workstation',
	printer: 'Printer',
	voip_phone: 'VoIP phone',
	mobile: 'Mobile',
	host: 'Host',
	cloud: 'Cloud',
	other: 'Other',
	cable: 'Cable',
	circuit: 'Circuit',
	neighbor: 'Neighbor',
	relationship: 'Relationship',
	connector: 'Connector'
};

export const STATE_NAMES: Readonly<Record<State, string>> = {
	existing: 'Existing',
	planned: 'Planned',
	remove: 'To remove'
};

/** The tag of each state. Existing has none. Never a color: color is the team's. */
export const TAG_LETTERS: Readonly<Record<State, string>> = {
	existing: '',
	planned: 'P',
	remove: 'R'
};

export function isDeviceKind(value: unknown): value is DeviceKind {
	return (DEVICE_KINDS as readonly unknown[]).includes(value);
}

export function isLinkKind(value: unknown): value is LinkKind {
	return (LINK_KINDS as readonly unknown[]).includes(value);
}

export function isState(value: unknown): value is State {
	return (STATES as readonly unknown[]).includes(value);
}
