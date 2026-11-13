# A code buys a pass

T10 finished the edit token, with a link that carried it. Later the same day both were gone. The site's owner read the recap and asked for something else: codes a person types, as texas2step has them, a pass with a time on it, and a list of internal networks. T10b built that, and took the link out again the same day. No release had shipped with it.

## What the token could not do

One static token is one secret for everyone, for ever. To take one group's editing away, the site had to change the token and send a new link to everyone else. Nothing ended by itself, and a link in an old chat worked until someone remembered to rotate.

A code is still a shared secret, and segl still knows nobody. What changes is what the browser holds. It does not hold the code. It holds a pass: the second it was issued at, and a signature over that second and the code under the server's secret. The server keeps no list of passes. It takes one if a code that is still in the list signed it, if it is not older than the site allows, and if it was issued after a time the site may set. So the site has three ways to end access without touching a browser: take a code out, shorten the hours, or set that time to now.

## Why there is a secret at all

The code goes into what is signed, so that taking a code out of the list ends its passes. That raises a question: if a pass is a signature over the code, why does the server need a secret besides?

Because a pass is left lying in a browser's storage. Without a secret it would be a hash of the time and the code, and anyone who read one could try codes against it on their own machine, as fast as they liked, past the count of five wrong tries. A code is a phrase a person can type, with as few as eight letters and digits. With the secret in the signature, a pass says nothing about the code to someone who does not have the secret. That is why segl does not start with codes and no secret, or with a secret under 32 characters.

## The pass that ends under an open page

A connection is an editor or a viewer from its `hello`, and the server never asks again. A pass with twelve hours on it would then edit for as long as its socket stayed open, which for a tab left on a wall screen is until the next deploy. So the connection keeps the time its pass ends, and the first edit after that time is answered as a viewer's is.

The page learns it then, and not before. What a person draws in that moment stays on their canvas alone, and is gone when they come back from the access page. The browser test for it had to say so: it draws after the end, finds the rectangle on no other browser and not in the stored scene, and after a reload finds the canvas as the server has it. That is one stroke, lost once in twelve hours. Telling the page ahead of time would take a new field in `welcome` and a timer, and it was left out.

## Five pixels

The bar got a link, `Enter access code`, beside the notice of a browser that may not edit. The test that measures the page's width at 390 pixels passed. I added the same test at 800, because a note from T08 says to measure anything new in the bar at three widths, and it failed by five pixels.

Five pixels is a small overflow. The screenshot showed what was behind it. Between 721 and about 1,100 pixels the bar did not wrap, and the notice was the one part allowed to shrink, so it had been squeezed into a column one word wide. At 800 pixels the bar was 203 pixels tall on an open slot and 284 on a locked one, and the slot's title was cut to its first letter. The new link could not break in the middle, and stuck out of that column.

It was like that on the commit before this task, without the link. Every width test had passed, because the page was never wider than the window. Nothing measured how tall the bar was.

The bar now wraps at any width, and the notice takes a line of its own when less than its basis is left for it. At 800 pixels the bar is 79 pixels tall with the link in it.

## Half a day of pytest

The first full browser run failed four tests, each with `Target crashed`. The kernel's log had the reason: the host was out of memory, and it had killed six Chrome processes in three minutes. Another project's job was running on the same machine. That was not segl's fault, and the four tests passed when run again.

Looking for what else was using the machine turned up four pytest processes of segl's own, eleven and a half hours old, with no parent. By their command line they were left over from the deliberate breakages of an earlier task. A breakage had made a test hang, the runner had given up after its time limit and killed the command it started, and that command was `uv run`, not the pytest under it. The runner now starts each case in a process group of its own and kills the group.
