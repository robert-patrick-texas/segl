# The scene goes last

T16 made a slot's history last a week. It keeps the newest 50 revisions, then one a minute, an hour, and a day as they age, and it keeps the board from before a big delete. Revisions are now stored compressed with zstd. Two findings came out of it, and neither came from a failing test.

## A column in the way

The size run measured one slot of 1,024 elements. Its history fell from 24.9 MiB to 7.1 MiB, with nearly three times the revisions. But a flush that added a revision went from 2.0 ms to 5.9 ms. zstd took 1 ms of that. The rest was a surprise.

`cProfile` put the time in the read that applies the new rules. It reads three small columns of each revision: the number, the time, and the mark. The table had the scene as its fourth column, before the time and the mark. SQLite stores a row's columns in order, and a 47 KB scene runs onto pages of its own. To reach the time, SQLite walked each row's pages of scene. With 135 rows, that was every flush.

The new table puts the scene last. The flush fell to 3.2 ms, where the old code took 2.4 ms when measured beside it. Reading the History list fell from 8.1 ms to 0.2 ms: 0.5.0's table had the same order, with scenes ten times bigger, and nobody had measured the list.

A large column goes at the end of its row.

## A mark in the wrong write

A restore is two writes. The first records the board that goes. The second puts the old revision in its place. Each is its own transaction. The plan was to mark the first write's row `Before restore`.

The fault list caught it before any fault ran. A fault needs a test that would fail, and the test for "the second write fails" asked what that row should say. A restore that failed had not happened. Its row said it had, and would have said so for a week.

The mark now goes on in the second write's transaction. If that write fails, nothing says "before restore".

Writing down what each fault should break is a review of the code. It found this, and three behaviours that no test held.
