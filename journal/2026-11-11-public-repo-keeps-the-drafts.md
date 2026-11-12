# What stays in the public repository

The repository is the public project, not a private drafting room with a cleaned export. `draft1/` keeps the earlier plan, including choices that were later withdrawn, so a reader can see why the open slots are not an authenticated inventory tool. `draft2/` keeps the live task queue. People who want the product, rather than the next task, read `docs/`.

Nothing in those folders is a secret. The files that stay off GitHub are the ones already ignored: a local `segl.toml` that may hold the edit token, virtualenvs, dependency trees, build output, and databases. PyPI publishing waits until there is a build worth installing. GitHub Releases are the destination from the first real release. The Python pin is 3.15, the newest patch on that minor line.
