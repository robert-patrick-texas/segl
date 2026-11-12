# The first real upgrade

The browser application arrived in T04, and with it the first web dependencies the release script had ever checked for real. Until then `scripts/release.py upgrade` had only moved web packages inside tests, against a fake `npm`. Prettier published 3.10.1 about an hour after T04 pinned 3.10.0, so the script got its first real web move the same day.

It held Prettier back, and the hold was wrong. The suite ran every Python command first and every web command after, so `uv run pytest` ran before `npm install`. T04 had just added a test that holds `web/package-lock.json` to `versions.toml`. After the move, `versions.toml` and `package.json` said 3.10.1, the lockfile still said 3.10.0, and that test failed. The script did what it was built to do with a failing suite: it restored the files and wrote `[held.prettier]` with the test's name as the reason. Nothing was wrong with Prettier.

The fix is the order CI already used: bring both environments to the pins first (`uv sync`, then `npm install`), and only then check anything. The web build now also comes before pytest, and the browser tests come last. The second run moved Prettier and passed.

The fakes had been faithful, which is why they missed it. Each fake command succeeded or failed on its own, and the bug was in what one real command leaves on disk for the next.

Two smaller surprises from the same task:

- Playwright 1.65's `run-server` drops the client's browser launch arguments unless it is started with `--unsafe`. The first plan mapped the example site names to `127.0.0.1` with a Chromium argument, and the browser in the container never received it. The browser tests now give each nginx site example its own loopback port and reach it by address, so they need no argument and no `/etc/hosts` entry.
- A helper folder named `web/build/` never showed up in `git status`. `.gitignore` has `build/`, for Python's build output, and it matches at any depth. The folder is `web/scripts/` now. `git add -n` on a new folder is a cheap check before the first push.
