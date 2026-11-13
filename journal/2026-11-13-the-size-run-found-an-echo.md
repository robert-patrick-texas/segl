# The size run found an echo

T11 put the test plan in the dev container as one command. Two smaller jobs came with it: try ten editors on one slot, and load a slot of a thousand elements. Both passed. The second one showed something the ordinary tests could not.

## One line for each row

"The suite passed" does not say that T-013 passed. Someone has to know which tests are T-013. Until now that was in comments and in the status log.

`tests/testplan.toml` now names the tests of each row. `scripts/testplan.py` runs pytest and the browser tests whole, reads their reports, and prints one line for each row. A row passes when every test it names ran and passed. A skipped test fails its row. So does a browser test that missed a mount: T-013 is about `/board/` and a host root, and a run of the `direct` project alone proves neither.

A table like that goes stale the day a test is renamed. So pytest holds it to the test plan's rows and to the tests' names. A renamed test fails the suite until the table follows.

## Chromium needed no help

The task allowed a fallback: if Chromium would not run in the Ubuntu 26.04 container, use Playwright's own image. It ran. Playwright 1.65 lists Ubuntu 26.04 and installs the libraries, and it starts Chromium without the sandbox and without `/dev/shm`, the two things that stop a browser in a plain container. `docker run` needs no extra flag.

Rootless Docker built the same file and ran the same command. The daemon was started by hand for the try, with rootlesskit's built-in network driver, and stopped afterwards.

## The echo

The thousand elements are made the way a person would make them: one rectangle, then select all and duplicate, ten times. That is 1,024. A second browser watches. A third opens the slot afterwards, and the run prints how long it took and what it sent.

It should send nothing. It had drawn nothing. In five loads of twelve it sent 462,000 characters: every element of the scene, back to the server that had just served them.

The cause is a gap of a tenth of a second. The page loads the scene over HTTP and puts it on the canvas. Then it opens the socket. The server answers `welcome`, and then `scene`, which is what the room holds. The page keeps a list of what the server is known to have, and that list is empty until `scene` arrives. If the canvas reports a change in between, every element looks new, and the page sends them all. With 1,024 elements `scene` is 464,000 characters and came 66 to 130 milliseconds after `welcome`. The page's 30-millisecond send timer fits inside that. The ordinary tests use scenes of a few elements. If the same thing happens there, nothing shows it.

Nothing is lost. Every browser still ended with the same scene, and the server answered `saved`. The cost is an upload of half a megabyte that says nothing new.

T11 recorded it and did not change it: the session is T06's code, and the fix is the owner's call. It is small. The page already has the scene it loaded, and can start its list from that.

The owner said yes the same day. The list now starts with the loaded scene, as the session's list of image files already did. A browser test holds `scene` back for a whole second, so the gap is certain, and fails if the page sends anything it did not draw. Before the fix it failed at every mount. After it, twelve loads of the 1,024-element slot sent nothing.

## The numbers

In the dev container, on a four-core host, with a browser that draws without a GPU:

- Ten browsers were in one room 3 seconds after they opened the slot. Ten rectangles drawn at once were in all ten browsers within 100 milliseconds. Two hundred moves, twenty from each browser at once, ended with the same scene everywhere within 400 milliseconds.
- The slowest doubling was in the other browser 0.5 to 0.6 seconds after the key. A new browser had all 1,024 elements 1.1 to 1.2 seconds after it opened the slot. One rectangle drawn then reached the others in about 30 milliseconds, as a message of 500 characters. A move of all 1,025 at once was the same in three browsers within 0.8 seconds, as one message of 463,000 characters.

Two editors are the gate. Ten were no strain.
