# A link that proves itself

T10 was the last piece of the edit gate. The server had refused a browser without the token since T06, and the page had sent a stored token since then too. What was missing was the way a token gets into a browser: a link that ends in `#e=` and the token. The task said to store it and strip the fragment. Three things about tokens and links turned up on the way, and one about what a view mode covers.

## A link stores what anyone puts in it

The plain reading is two lines: read the fragment, write it to `localStorage`. The trouble is who can make a browser open a link. Anyone can. A page on any site can send a visitor's browser to `https://dev.example.com/board/s/1#e=nonsense`, with a link, a redirect, or a window it opens itself. If the page stored whatever the fragment held, that visit would write `nonsense` over the token the browser had, and the person would be a viewer until someone sent them the right link again. A stranger could do that to every editor of a segl, one by one, and nobody would see how it happened.

So a link's token has to prove itself first. The page takes the fragment out of the address at once, keeps the token in memory, and says `hello` with it. The server's `welcome` says whether that connection may edit. If it may, the token is written to `localStorage`. If it may not, nothing is written, and when the browser already has a stored token the page goes back to that one and says `hello` again. A browser test opens a wrong link in a browser that holds the right token and reads the two `hello` messages the page sent: the link's token, and then the stored one.

That needed one thing from the collaboration session that it did not have. The session's state says whether the connection is view-only, and that value stays as it was while a new `hello` is on its way. A page that looked at it right after changing its token would read the answer to the old token as the answer to the new one. The session now reports each `welcome` together with the token its `hello` carried.

## A token a browser cannot say

The server took any text as a token. The token reaches it two ways: inside `hello`, which is JSON and carries anything, and in the `X-Segl-Edit-Token` header on a title change, a restore, an import, and an upload. A header does not carry anything. In Chromium, a `fetch` with a `€` in a header's value fails before a request leaves, with `String contains non ISO-8859-1 code point`, and a line break fails the same way. A space at either end is dropped on the way.

A segl with such a token would have looked half broken. A browser with the right token would be an editor on the socket, and draw, and then fail at every title and every restore with an error that says nothing about tokens. No test had a token like that, and nobody had tried one.

The token is now what a header carries whole: 1 to 256 printable ASCII characters, with no space at either end. segl does not start with any other, and says why. The page applies the same rule to a link and to what it finds stored, and one table of cases holds the Python and the TypeScript to the same answers, as the display names already do.

## What a view mode covers

The editor has a view mode, and segl has used it for viewers since T06: no toolbar, no shortcuts, nothing to select. A viewer's canvas looked safe from its own owner. Writing the browser test for "cannot change elements" meant trying what a person might try, and one of those was dragging a picture in from a folder.

It was placed. The editor's drop handler does not ask about view mode. The server had refused the upload all along and no other browser saw the image, so the gate held. But the viewer was now looking at a canvas with a picture on it that nobody else had, under a bar that said `Live`. It is the same kind of fault as the editor's own Open in T09: one browser shows a drawing the slot does not hold.

The canvas adapter already looked at every drop before the editor, to send a scene file to the import. It now also stops everything else when the browser is view-only. A scene file still goes to the Import control, which tells a viewer what importing needs.

## What a test can see of another site's request

T-012 asks that a request from another site is refused with `bad_origin`. pytest can send any `Origin` header it likes, and has since T06. The point of a browser test is that a browser writes that header itself, and a script cannot.

The three projects of the browser tests reach one segl at three origins: directly, through nginx at a host root, and through nginx at `/board/`. So a page of one project is a page of another site to the next, with no second site to set up. From such a page, a plain `POST` to the import route goes out, and segl answers `403`.

Reading that answer was the hard part. The browser keeps the body of a cross-site answer from the page, which is the rule that protects the answer. It keeps it from the test too, and the test's view of the request does not show the `Origin` header the browser added. What the test can see is the status. On a segl with no edit token, the origin is the only reason there is for a `403`, so the status is the evidence, and the test then sends the same request itself, with the same `Origin`, to read the code. The socket is simpler: from the other site's page it closes without ever opening, and from the site's own page the same address opens.

## One thing the sweep found and left

The Origin rule compares the host and the port. It does not compare the scheme. `http://dev.example.com` passes for a request to `dev.example.com`, since a browser leaves the default port out of both. So a page served over plain http under the site's own name counts as the site's page. The shipped nginx example answers on port 80 only to redirect, and sends HSTS, so that page has to come from someone who can answer in the site's place on the network, to a browser that has not yet learned to insist on https.

The rule is T06's, and `docs/SECURITY.md` states it as host and port. Comparing the scheme would lean on `X-Forwarded-Proto`, and a site whose proxy does not send it would refuse its own pages. That is a decision about a locked rule, so it is in the status log as a question and not in the code.
