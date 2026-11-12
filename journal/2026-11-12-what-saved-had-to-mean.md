# What "saved" had to mean

T07 made segl keep what is drawn. The server writes each slot's scene to SQLite a fifth of a second after an edit, when the last browser leaves, and when it is stopped. The bar says `Saving…` and then `Saved`. Images are stored as files and come back after a restart. Most of that went as the documents had planned it. Three parts did not.

## Saved had to be an answer to something

The plan was one message: after a flush, the server tells the browsers whose edits it held that they are `saved`. The requirement behind it is S-004: once the bar says saved, the process can be killed and the scene comes back.

A message that says only "saved" cannot keep that promise. A browser sends an edit, and the server starts writing it. While the write is in a worker thread, the browser sends a second edit. The write ends, the server says `saved`, and the bar shows `Saved` over an edit that is still only in memory. It would be wrong for a fifth of a second, which is exactly long enough for a test that kills the server "once the UI says saved" to fail one run in some number, and for a person to close a laptop on.

So a browser numbers the messages that change what is stored, and `saved` carries the number of the newest one that is on the disk. The bar says `Saved` only when that number has caught up with the last one sent. The other half is in the browser: the status turns to `Saving…` the moment the canvas holds something the server has not seen, before the edit is sent, because edits are gathered for 30 ms first. And after a reconnect, a browser that never heard `saved` for something it sent asks, with an empty numbered batch, since the answer may have been lost with the socket.

The same number covers images. The file of a placed image is uploaded over HTTP and then named on the socket, and the bar stays on `Saving…` until the message that names it is saved too. An image whose element is on the disk and whose bytes are not is not a saved image.

## The editor does not keep your file

The first version of the image test dropped a PNG on the canvas and expected the server to hold those bytes: the SHA-256 of the file the test made. It held other bytes. The pinned editor re-encodes an image when it is placed, even one of 160 by 100 pixels, and keeps its own encoding as a `data:` URL. The file id it gives the image is the SHA-1 of the file it was handed, and the bytes behind that id are not that file.

Nothing in segl was wrong, and the test now says what is true: the stored bytes are a PNG, named by their own hash. But the first expectation had also been on its way into `DECISIONS.md` as a sentence about storing "the file the person chose". D2-028 says instead that the bytes are the editor's own encoding. It is the lesson of the cursor colors in T06 a third time: what the embedded editor does with a value is found by running it, not by reading the name of the field.

One more thing follows from "whatever a browser sent". segl does not look inside an upload, so an uploaded file is served as `application/octet-stream`, with `nosniff` and a sandboxing policy, and never under an image type. An SVG can carry a script, the edit token lives in `localStorage` on the same origin, and a file opened by its URL would otherwise be a page of the site.

## A slot emptied while it was being written

The flush after the last browser leaves also adds a history row, whatever the age of the newest one, so that the history always has the scene a slot was left with. Whether a row is owed depends on whether the head holds a scene the history lacks, and the saver learns that from each write.

A test held a write in its worker thread and let the last connection leave meanwhile. The history row never came. The leave had asked "is anything owed?" while the write that would make the answer yes was still running, got no, and forgot that it had asked. The fix is small: while a write is under way, a leave is kept, and the saver looks again when the write ends.

It was found by a test written the same hour as the code, with the write held open on purpose. So were a `files` message that crashed its parser when a type was a list instead of text, and a stored scene whose keys changed places on the first flush, which would have made every head look changed. Then the deliberate breakages, each run against the tests that should catch it, found the tests' own gaps. Nine of the first 84 changes to the browser's logic failed nothing, and each got an assertion. Three of 102 changes to the server failed nothing: one was a value handed to a room that nothing ever read, which was removed, and two got a test.

One breakage did more than fail a test. With the leave's history row turned off, the saver's last flush at a stop never reported the history as caught up, and the stop asked again without end. No real database answers that way, but a stop that can spin is a stop that can hang a restart. The saver now asks once for a row it was told to add, and a test holds it to that.
