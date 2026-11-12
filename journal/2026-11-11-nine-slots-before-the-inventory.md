# Nine slots before the inventory

The first write-up of segl was a network-planning suite: accounts, PostgreSQL, a separate Node collaboration process, and boards people could create and delete. That is a real product, and it is not the first one this repository should ship.

A meeting needs a blank board that a second browser can mark up without an account. The MVP is nine persistent slots. Slot 1 is the door. A return visit can reopen the last slot from local storage. A shared link opens the slot in the URL, including when nginx mounts the app under a prefix such as `/whiteboard`. Cookies are out of the design, including for the later login. An optional site-wide edit token can freeze writes while viewers still watch the board live. An empty token means a fresh install is editable by anyone who can open the URL.

The boundary that has to stay sharp: those slots never gain a way to read the later named workspaces. Inventory, and the login that protects it, belong under `/{team}/{project}/{board-slug}`. The slot URLs stay `/s/1` through `/s/9`. Mixing those trees would turn a meeting scratchpad into an unauthenticated view of network data.

Apache License 2.0 is the grant for work written here. Excalidraw stays under its own license and is embedded, not forked.

Releases will try the newest versions of the components we directly depend on, run the tests, and publish to GitHub Releases and PyPI when that succeeds. A component that breaks the tests stays on the known-good version, with the reason written in the release notes, until a later version of that component is worth trying again. `versions.toml` is the list the program and the notes both use. This journal is for the reasoning. The changelog is the short record of what actually changed.
