# Copyright 2026 segl contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""``segl update``: install a newer signed release, and go back if it fails.

A release is three files on GitHub: the ``.deb``, ``SHA256SUMS``, and an SSH
signature over it. The update checks them against the signers the installed
package ships before it changes anything. Then it stops segl, saves the
settings, the nginx files, and the database, installs the package with apt,
merges new statements into the settings and the nginx files, checks both,
and starts segl. If a step fails, the previous package and what was saved go
back (docs/DEPLOY.md, updates).

The order follows Sunstone's updater, and the merge of settings follows
texas2step's ``config merge``.
"""
