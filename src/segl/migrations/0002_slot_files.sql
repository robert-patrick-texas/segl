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

-- The files of a slot's images (D2-028). The editor keeps an image's bytes
-- outside the scene, under an id of its own, and an image element names that
-- id. The bytes are a file under assets_dir, named by their SHA-256. This
-- table says which bytes a slot's file id means. A row is never changed, so
-- a revision that names a file id still finds its bytes.

CREATE TABLE slot_file (
  slot INTEGER NOT NULL REFERENCES slot(number),
  file_id TEXT NOT NULL,
  hash TEXT NOT NULL,
  media_type TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (slot, file_id)
);
