# A restore that can be undone

T08 gave each slot a History control. It lists the slot's revisions, and one of them can be put back for everyone on the slot. The routes had been in `docs/API.md` since the first draft, the revisions had been written since T07, and a browser already replaced its canvas when it was sent a scene of another epoch. What was left to decide was what a restore owes the scene it replaces.

## The scene that goes has to be somewhere

The requirement, S-005, says a restore "can itself be restored". The test plan says it plainly: restore an older revision, then restore the one from before the restore, and the later drawing returns.

That only works if the later drawing is in the history at the moment it is replaced, and usually it is not. The history is a sample. A slot gets at most one revision a second while people draw, so the head is often ahead of the newest revision, and the room in memory is ahead of the head by up to a fifth of a second. A restore that only wrote the old scene over the new one would lose whatever was drawn in the last second, with no way back.

So a restore starts by writing what the room holds, and keeping it as a revision whatever the age of the newest one. Then it writes the restored scene, at the next epoch, as a revision of its own. Afterwards the two newest rows of the list are always the scene that went and the scene that came, and undoing a restore is one more restore, of the row under it.

Three cases came out of that one rule before any code was run.

The first is a full history. The server keeps 50 revisions, and the 51st drops the oldest. Keeping the scene that is going adds a row. If the row being restored is the oldest of 50, that addition is the one that drops it, and the restore would then look for a revision it had just deleted. The revision is therefore read first, before anything is written. A test with a history of three rows restores the oldest and gets it.

The second is a crash. After a kill, the head may hold a scene that no revision holds, and the new process does not know that: what it had learned about the history was in memory. A restore that kept the room's scene only "when something is owed" would skip it. It asks the database every time instead, which compares the scene with the newest revision in the transaction that writes. A test kills a server, restores on the next one, and finds the head the crash left as a revision, under the name of the person who saved it and not `System`. That name took a small change to the flush: a revision for a head that an earlier write stored carries the head's own label.

The third is the saver. A slot's head flushes run on a timer, in a worker thread, and each names the epoch it is for. A restore moves the epoch. A flush that started before a restore and reached the database after it would be refused, logged, and tried again. The restore is therefore the saver's own work, under one lock with the flushes: the slot is written by one of them at a time.

## A test that did not force the overlap

The first test of that lock held a flush in its worker thread, started a restore, and checked that the restore waited. It passed. It also passed with the lock taken out of the restore.

Both writes went through the same wrapped function, and the test held that function. So the restore waited at the test's own gate, not at the lock, and when the gate opened the two happened to run in the right order. The deliberate breakage that removed the lock was caught, but by the neighbouring test, where a flush waits for a restore. The test now holds only the first write and checks that nothing else has reached the database meanwhile. With the lock removed it fails.

T06 had the same lesson with the lock that orders two title changes. A test of a lock has to make the thing the lock prevents possible, and then show it did not happen.

## What a hand run saw that the tests did not

The first real run, two browsers and the real editor, worked: the later rectangle left both canvases, and the row under the restore brought it back. The run printed the rows of the list, and one of them read `segl 0.0.0`.

The history rows had been given the class `segl-bar__version`. The bar already has an element of that class, the application version at its right end, so the rows took its small gray type, and it took their layout. No test would have said so. The rows are `segl-bar__revision` now.

A screenshot at 390 pixels found the next one. The list hangs from the left edge of its button, and a narrow bar puts that button near the right edge of the page, so the list ran 200 pixels past it and the whole page scrolled sideways. A long slot title does the same at any width. The list now moves left by as much as it has to, worked out from the button's place when it opens, and a browser test opens it at 390 pixels and checks that the page is no wider than before.

Neither was a failure of logic, and each took a minute to see once the page was on a screen.
