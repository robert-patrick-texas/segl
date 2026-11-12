# One way into a shared canvas

T09 was three sentences in the task list: use the editor's JSON export, post an import to a route that follows the restore rules, and refuse a body that is too large. The export was already there. Excalidraw's menu has "Save to…", and segl had never turned it off. Most of the task turned out to be about the other direction, and about the ways into a canvas that segl had not known it had.

## The editor already had an import, for one browser

The embedded editor opens a scene file in three ways: "Open" in its menu, Ctrl+O, and a file dropped on the canvas. All three do the same thing. They put the file's scene in this browser's canvas, in place of what was there.

On a canvas one person owns, that is what opening a file means. On a slot, the canvas in a browser is a view of a scene the server holds. Since T06, a file opened this way has gone wrong quietly. The browser that opened it shows the file's drawing, without most of what was there. Its session then sends the new elements to the server as edits, where they are added to the scene everyone else still has. So the others see both drawings at once, and the person who opened the file sees one, until a reload shows them both too. Nobody had tried it, and no test had.

The import route settles what opening a file means on a slot: the file's scene replaces the slot's, for everyone, at a new epoch, and the scene that went is kept in the history. That left the editor's three ways in as three ways around it. The menu entry and its shortcut are one option of the package, `loadScene`, and are off. The drop has no option. The canvas adapter now looks at a dropped file before the editor is given it. An image goes on to the editor, which places it. A library of shapes goes on too. Anything else is handed to the page, which asks the same question the Import button asks: replace the canvas for everyone?

The rule for the drop is "everything but an image or a library", and not "a file named `.excalidraw`". The editor does not go by the name. It tries to read whatever it is given. A rule by name would have left every scene file with another name going the old way.

One way in stayed. The editor can export a PNG or an SVG with the scene embedded in the image, and when such an image is dropped on a canvas it opens the scene, in that browser alone. Telling that image from an ordinary one means reading it first, which the drop does not wait for. It is written down as not done.

That open way was also how the old behavior could still be watched. On a slot where one person had drawn six rectangles, another dropped such an image, with three elements in it. The one who dropped it was left with those three and one of the six. The other had all nine. After a reload, so did the first. The one rectangle that came back early came from the other browser, which sent it again after taking in the file's elements. Why its editor changed that one was not looked into, and nothing in segl sends it.

## What a file holds, and what a slot takes from it

The editor's export is a JSON document with three parts: the elements, an `appState` with the background color and the grid, and `files`, the bytes of each image as a `data:` URL.

segl keeps the bytes of images outside a scene, in files named by their hash (D2-028), so an import takes them out of the document and stores them the way an upload is stored. That was the reason to read the document on the server and not in the page: the route takes the file exactly as the editor wrote it, and `curl` can import one. The file ids join the slot's list in the same transaction that starts the new epoch, so the scene every browser is then sent never names a file the server lacks.

The `appState` is left where it is. A slot does not share its background or its grid, and a stored head has never had its `appState` written. An import that brought a black background would show it to whoever loads the slot next and to nobody who is already there.

Everything the route refuses, it refuses whole. One case came from the size limit. The limit on a slot's elements counts them as segl stores them, which is ASCII, with an escape for every other character. A file of `é` is two bytes a letter on disk and six in a stored scene, so a file under the limit can hold a scene over it. The check is made on the elements as they will be stored.

## A number that Python reads and no browser can

JSON has no infinity. Python's reader refuses the words `NaN` and `Infinity` only when told to, which segl has done since T06. It has another way to make one, though. `1e999` is an ordinary JSON number that is too large for a float, and Python reads it as infinity without complaint. When it writes the value back, it writes `Infinity`, which is not JSON, and a browser that is sent it cannot read the message at all.

An imported document is the first thing segl stores that did not come from a browser's own `JSON.stringify`, which writes `null` for such a number. So the import writes each element with a strict writer first, and a document with `1e999` in it is refused as not a scene document.

Checking the claim on the socket found the same hole there. A hand-made `elements` message with `1e999` is accepted, the other browsers are sent `Infinity`, and the scene route then answers with text no browser can parse, so the slot cannot be opened until an earlier revision is restored from outside the page. No browser sends such a message. That is T06's code and is reported, not changed, in this task.

## The page that scrolled sideways once

The Import control drops a panel from the bar, like the History control, and uses the same helper to move the panel left when its button is near the right edge of a narrow page. At 390 pixels the page still gained a sideways scroll, and the panel sat twelve pixels off. Nothing was sticking out when measured.

The button that confirms an import was marked to take the focus when it appears. It appears with the panel, at the panel's first position, which on a narrow page is partly outside it. The browser scrolled the page to show the focused button, and the helper then measured a page that had moved. History's own confirm button appears a press later, after the panel is in place, so it never met this. The focus is now given once the panel has been placed, and without scrolling. A browser test opens the question at 390 pixels and checks the page's width.

## The sixty seconds, read at last

After T08, one CI run failed on a test from T06: a WebSocket handshake through nginx was not answered. It passed on a second attempt, and twelve local runs found nothing. The harness was then changed to quote the servers' logs when a handshake times out, so that the next one could be read.

The next one came during this task, on the development host, while the browser suite was running beside pytest. The quoted logs said what the first one could not. nginx had accepted the connection and finished TLS, and then logged `client timed out while waiting for request`, sixty seconds later, with nothing in its access log. segl had seen only the health check. The request had never arrived.

That put the fault in front of nginx, in the test's own client. A loop of handshakes through one test nginx, with the processor kept busy, lost 2 in 2,253 the same way. A stack dump at each showed the client's main thread already past sending the request and waiting for the answer, and its reader thread inside a TLS read. The same loop with the client held to TLS 1.2 made 6,000 handshakes and lost none.

The client library starts a thread that reads the socket before the first request is written. Under TLS 1.3 the server has something for that thread to read at once, its session tickets, at the moment the main thread writes. Once in a thousand or so, on a busy machine, the write is lost. segl and the nginx files have no part in it, and the browsers do not use this client.

The fix is a line in the test harness, and the harness belongs to another task, so it waits for a decision. What is settled is the reading of the earlier failure. The entry for it said the cause was not established. It was a test client that lost its first write, on a runner that was busy.
