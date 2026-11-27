-- Copyright 2026 segl contributors
--
-- Licensed under the Apache License, Version 2.0 (the "License");
-- you may not use this file except in compliance with the License.
-- You may obtain a copy of the License at
--
--     http://www.apache.org/licenses/LICENSE-2.0
--
-- Unless required by applicable law or agreed to in writing, software
-- distributed under the License is distributed on an "AS IS" BASIS,
-- WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
-- See the License for the specific language governing permissions and
-- limitations under the License.

-- Slot 9 becomes Diagram mode, drawio's editor (T17, D2-039). Its
-- whiteboard scene, its revisions, and its file rows go, and it starts a new
-- epoch with the empty diagram. Its title stays. A migration changes only
-- the database: no file under assets_dir is removed, so bytes another slot
-- still names stay, and so do bytes that only slot 9 named.
-- segl_empty_diagram() is segl's own function (segl.diagram.empty_diagram).

DELETE FROM revision WHERE slot = 9;

DELETE FROM slot_file WHERE slot = 9;

UPDATE slot
SET epoch = epoch + 1, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
WHERE number = 9;

UPDATE slot_head
SET epoch = (SELECT epoch FROM slot WHERE number = 9),
    scene_json = segl_empty_diagram(),
    editor_label = 'System',
    saved_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
WHERE slot = 9;
