# The reload that ate a label

T17 put drawio's editor on slot 9 as Diagram mode, with people editing one diagram at the same time. The design was simple to say. drawio's diff sync hands out a patch for each edit. The server cannot read a patch, so it numbers them and passes them on, and each browser applies the others' in that order. A browser that finds its checksum wrong loads the whole diagram again.

The tests passed. The measures are what found the problem.

## Nothing was lost

Four browsers drew a rectangle every one to three seconds for five minutes. Every browser ended with every shape, and so did the stored diagram. But each browser loaded the whole diagram again about once every 25 seconds.

The cause was order, not content. drawio's insert patch names the shape the new one goes after. When two people insert at once, each browser has its own shape first and the other's second. The shapes are all there, in a different stacking order. The checksum sees the order, and the next patch whose checksum counts shows the drift. A load puts it right.

## What a load costs

So the next question was what a load does to the person in front of it. A probe zoomed in, scrolled, and then loaded the same diagram. The zoom went from 1.45 back to 1, and the scroll went back to the start.

A second probe opened a shape's label, typed `half-typed`, and loaded. The label editor closed. The text was gone. With four people drawing, that is a real way to lose an edit, and no test had looked for it: every test drew shapes, and none typed while another browser drew.

## Two small reports from inside drawio

drawio's embed messages do not say when a label is being edited, nor where the diagram is scrolled. drawio does let a site replace two settings files, and segl already had its own copies. Its `PostConfig.js` now tells the page when a label editor opens and closes, and adds the scroll to drawio's own answers about the view.

The page holds a repair until the editor closes, so the typed text goes out as an edit first. Then it loads the diagram with the same scale and the same point at the top left. A probe after the change came back to the same view to the last decimal.

Four browsers then drew for five minutes and typed a label on about half their shapes: 434 shapes and 183 labels, every one in every browser and in the stored diagram, and no label cut off. The first such run kept them all too, but every bar stayed at `Saving…`. A browser waiting for the whole diagram had dropped its own patch as it came back, and the whole did not list a patch its copy already held. A test now holds that too.

## What is left

A load still returns to the first page of a diagram with several pages, since drawio's embed messages cannot select another. The next Diagram mode task takes it up. The pen stays beside co-editing for the times one person should draw while the others watch.

Measure the thing people will do, not only the thing the tests do.
