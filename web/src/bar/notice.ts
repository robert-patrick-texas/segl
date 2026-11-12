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

/** What every slot states: who can see it, and who can change it (S-016). */
export function sharedNotice(editRequired: boolean): string {
	return editRequired
		? 'Shared workspace. Anyone who can open this page can see it. Editing needs the edit token.'
		: 'Shared workspace. Anyone who can open this page can see it and edit it.';
}
