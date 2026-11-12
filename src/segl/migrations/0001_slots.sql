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

-- The P0 tables, as docs/DATA-MODEL.md lists them. A test compares the two.
-- segl/repository.py runs this file inside one transaction and then records
-- the file's number, so the file has no BEGIN or COMMIT of its own.

CREATE TABLE slot (
  number INTEGER PRIMARY KEY CHECK (number BETWEEN 1 AND 9),
  title TEXT NOT NULL,
  epoch INTEGER NOT NULL DEFAULT 1,
  updated_at TEXT NOT NULL
);

CREATE TABLE slot_head (
  slot INTEGER PRIMARY KEY REFERENCES slot(number),
  epoch INTEGER NOT NULL,
  scene_json TEXT NOT NULL,
  editor_label TEXT NOT NULL,
  saved_at TEXT NOT NULL
);

CREATE TABLE revision (
  slot INTEGER NOT NULL REFERENCES slot(number),
  revision INTEGER NOT NULL,
  epoch INTEGER NOT NULL,
  scene_json TEXT NOT NULL,
  author_label TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (slot, revision)
);

CREATE TABLE name_counter (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  next_value INTEGER NOT NULL
);
