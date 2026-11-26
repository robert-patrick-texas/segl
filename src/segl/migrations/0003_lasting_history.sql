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

-- History that lasts (T16). A revision's scene is stored compressed with
-- zstd, and a revision can be marked kept: the scene before a big delete, a
-- restore, or an import. segl_zstd() is segl's own function, which
-- segl/repository.py gives the connection that runs the migrations: it
-- returns the text compressed as a revision is stored.
--
-- The old table is renamed out of the way first, so that the new one keeps
-- the CREATE statement as written here, which docs/DATA-MODEL.md lists. The
-- scene is the last column: SQLite then reads a row's other columns without
-- walking the pages of its scene, as the history list and the rules do.

ALTER TABLE revision RENAME TO revision_0002;

CREATE TABLE revision (
  slot INTEGER NOT NULL REFERENCES slot(number),
  revision INTEGER NOT NULL,
  epoch INTEGER NOT NULL,
  author_label TEXT NOT NULL,
  created_at TEXT NOT NULL,
  kept TEXT CHECK (kept IN ('delete', 'restore', 'import')),
  scene_zstd BLOB NOT NULL,
  PRIMARY KEY (slot, revision)
);

INSERT INTO revision (slot, revision, epoch, author_label, created_at, scene_zstd)
SELECT slot, revision, epoch, author_label, created_at, segl_zstd(scene_json)
FROM revision_0002;

DROP TABLE revision_0002;
