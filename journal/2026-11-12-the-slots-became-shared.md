# The slots became shared

T06 made a slot something two browsers draw on together. The server now keeps a room for each slot, with the scene as everyone has edited it and a list of who is connected. That was the point of the task. It also changed three things nobody had asked it to change.

## The tests lost their empty slots

Before T06, nothing a browser test drew went anywhere. Every test opened a slot, found it empty, and left it empty for the next one, because the drawing died with the page. The suite ran its files in parallel, three projects against one server, and none of them could see another.

A room keeps what was drawn until the server stops. The first full run after the change passed in the first project and failed in the other two, in the test that places a text element. The font it waits for had already been fetched, because the room still held the text the first project placed. With that fixed, the next run failed one line later: the press that should have placed a new text landed on the old one and edited it. The test that expected `['text']` had been relying on the slot forgetting.

The fix was to stop pretending the slots are private. The browser tests now run one at a time. A test asserts on what it drew, by element id, and never on a slot being empty. `web/e2e/pages.ts` names which slot each kind of test may change, and slot 9 is never drawn on, for the tests that are about an empty slot. The run takes about three minutes.

## A cancellation lost its name

Each connection runs two tasks, one reading the socket and one writing to it, and when either ends the handler cancels both and waits for them. The first version waited with `asyncio.gather`. Once in the first dozen runs, a test failed while closing a socket, with a bare `CancelledError`.

The test client cancels the handler from inside a cancel scope, and the scope recognizes its own cancellation by the message on the exception. When a task is cancelled while it waits on `gather`, `gather` raises a child's `CancelledError` in its place, and the child had been cancelled by the handler, with no message. The scope saw a cancellation it did not know and let it through. `asyncio.wait` does not do that: the waiting task gets its own cancellation back, message and all. One call changed, and 25 runs in a row passed.

Whether a running server could hit the same thing depends on how uvicorn cancels a handler, which was not looked into. The test was right to fail either way: the handler was passing on a cancellation that no longer said whose it was.

## The cursor already had a color

The protocol in `docs/API.md` gave every participant a `color`, and the first version had the server hand them out from a palette, so that the list in the bar could show a swatch beside each name. The first screenshot of two browsers showed a blue swatch beside Bea and a green cursor labelled Bea on the canvas.

The pinned editor draws a remote cursor in a color it computes from the collaborator's id, and ignores any color it is given. Every browser therefore already agrees on each connection's color, without segl saying anything, and no color segl chose could match it. The palette, the field, and the swatch came out again (D2-027). The lesson is the one from the canvas fonts in T04: look at what the embedded editor actually does with a value before building a contract around it.
