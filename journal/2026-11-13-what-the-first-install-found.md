# What the first install found

T12 built the `.deb` and installed it for the first time, in an Ubuntu 26.04 container that boots systemd. The build followed Sunstone's, file for file, and worked on the second try. The install is where the lessons were.

## The unit locked its operator out

The first run of the install test passed 83 of 94 checks. Most of the eleven failures had one cause: `start of the service was attempted too often`.

The unit had come from Sunstone with a start limit of five in ten minutes. The comment said "five failed starts". systemd counts every start, a start by hand too. The test restarts segl about nine times in a minute. So would a person who is trying out settings: edit, restart, look, edit, restart. The sixth restart fails, and the message does not say why in words that person would guess.

The limit is now five in a minute. A crash loop still ends, and a person at a keyboard does not reach it. The operator notes name the message and the command that clears it.

## A bad setting should stop once

segl exits with status 2 for a setting it cannot use. A restart cannot fix a file. The unit now has `RestartPreventExitStatus=2`: segl stops once, and `systemctl status segl` shows the line that names the key. The test writes `base_path = "/board"` into the file and checks all three: failed, named, not started again.

## The test image hid the documents

Two checks said the operator notes were not installed. They were in the package. Docker's Ubuntu image tells dpkg to leave out everything under `/usr/share/doc` but the copyright files. A real host does not. The test image now removes that setting, as it already removed the `policy-rc.d` that keeps a package from stopping its service.

A test container is not the machine. Each place it differs is a place a check can pass or fail for the wrong reason.

## The machine trusts its own snakeoil

One check was meant to show that nginx serves the snakeoil certificate: curl without `--cacert` should refuse it. curl took it. Ubuntu's `make-ssl-cert` links the certificate into `/etc/ssl/certs`, so the machine trusts it. The check now compares the fingerprint of the certificate nginx shows with the file's.

The container's host name is `dev.example.com`, the name in `site-board.example.conf`. So the snakeoil certificate Ubuntu makes there is for that name, and curl can check it in full. No `-k` anywhere.

## lintian reads everything

The build ends with lintian, and an error fails it. It found three things worth knowing.

- The editor's bundle names `platform.twitter.com` and `embed.reddit.com`. That is the editor's own tool for embedding a web page, which D2-026 already records. The page itself asks no other host for anything. The override says so.
- One npm package ships its `LICENSE` with mode `0755`. The build now sets every document to `0644`.
- The `websockets` wheel has an unstripped extension module. It ships as PyPI has it, the file whose hash the lockfile holds.

## Nine fonts and no license text

The web build is minified, so it keeps no license comments. The package has to carry the texts. For npm packages that was a list and a copy: a build plugin writes the packages whose code is in the build, 128 versions of 109 packages, and a script copies each one's license file. Thirty-six of the 128 ship none, 33 of them from one project, and segl keeps those texts.

The fonts were the surprise. The editor ships nine families and no license text for any. So each one's license was read from the font file itself: the `name` table holds a copyright record and often a license record. Seven are under the Open Font License and one is MIT.

The ninth is Liberation Sans. Its records say version 1.05, from 2009. Liberation moved to the Open Font License with version 2. Version 1 is under the GNU General Public License version 2, with an exception for a document that embeds the font. Nobody would have guessed that from the folder's name. The package carries that license, and the notice names it.

The script fails when a package or a font has no text, and pytest runs it against the real build. A new editor version that adds a font fails the suite until someone has read its license.

## One group in the lockfile

The package is built "from the lockfiles". The `segl` wheel is built by hatchling, and hatchling has dependencies of its own that no lockfile held. Sunstone keeps a hashed constraints file for them, made by hand.

segl has a `build` dependency group instead: the same line as `[build-system] requires`. `uv.lock` then holds hatchling and its dependencies with their hashes, the package build exports them, and `scripts/release.py upgrade` moves both lines at once. No new file, and nothing to remember.

## Two builds, one file

Two builds of one tree gave the same bytes: the same SHA-256. Every packaged file carries the commit's time, bytecode is compiled in one process with one hash seed, and uv's own record of the install time is removed.
