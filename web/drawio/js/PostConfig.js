// Copyright 2026 segl contributors
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

/*
 * The lines kept from drawio's file are
 * Copyright (c) 2006-2024, JGraph Holdings Ltd
 * Copyright (c) 2006-2024, draw.io AG
 * under the same license.
 *
 * segl's copy of drawio's js/PostConfig.js, a settings file a site may
 * replace (D2-039). drawio loads it after its own code, and before the
 * editor starts. It sets what the release's file sets, and adds what the
 * page needs that drawio's embed messages do not carry: the read-only view,
 * a label editor opening and closing, the scroll and the page, and, for
 * follow mode and cursors (T18), where the person looks and points, and the
 * others' cursors. For T19 it also tells the page when a press starts and
 * ends, and what this browser selects; it outlines the others' selections,
 * and it keeps the page, the view, and the selection across a load.
 */
// null'ing of global vars need to be after init.js
window.ICONSEARCH_PATH = null;
window.ICON_SERVICE_PATH = null;

// segl: tell the page each time this window's read-only view turns on or
// off, by segl's `load` or `readOnly` action or by the View menu. The page
// sets it while someone else holds the pen, and needs to know where it is.
(function () {
	var setReadOnly = EditorUi.prototype.setReadOnly;
	EditorUi.prototype.setReadOnly = function () {
		setReadOnly.apply(this, arguments);
		var page = this.embedMessageSource || window.opener || window.parent;
		page.postMessage(
			JSON.stringify({ event: 'readOnly', readOnly: this.readOnly === true }),
			window.location.origin
		);
	};
})();

// segl: drawio's answers that carry the view (to load, export, and zoom) say
// where the diagram is scrolled to, and the id of the page shown, as well.
// drawio names the page only by its place in the list. The page keeps a
// person's view and page when it loads the whole diagram again to put a
// drifted copy right.
(function () {
	var createLoadMessage = EditorUi.prototype.createLoadMessage;
	EditorUi.prototype.createLoadMessage = function () {
		var message = createLoadMessage.apply(this, arguments);
		var container = this.editor.graph.container;
		message.scroll = { left: container.scrollLeft, top: container.scrollTop };
		message.pageId = this.currentPage != null ? this.currentPage.getId() : null;
		return message;
	};
})();

// segl: tell the page when a label editor opens and closes. The page loads
// nothing in the diagram's place while a person is typing. drawio opens no
// editor for a cell it does not show, and a focus handler may close it at
// once: the page is told whether one is open after the call, or a load
// would wait for an editor that is not there.
(function () {
	var startEditing = mxCellEditor.prototype.startEditing;
	var stopEditing = mxCellEditor.prototype.stopEditing;
	function tell(editing) {
		window.parent.postMessage(
			JSON.stringify({ event: 'editing', editing: editing }),
			window.location.origin
		);
	}
	mxCellEditor.prototype.startEditing = function () {
		var result = startEditing.apply(this, arguments);
		tell(this.getEditingCell() != null);
		return result;
	};
	mxCellEditor.prototype.stopEditing = function () {
		var result = stopEditing.apply(this, arguments);
		tell(false);
		return result;
	};
})();

// segl: where the person looks and points, and the others' cursors (T18);
// the press, the selections, and a load that keeps the page (T19).
//
// The page sends `view` only while someone follows this browser, and a
// `pointer` as the person's pointer moves over the diagram. Both are in
// diagram coordinates, on the page of the diagram named. `looked` says the
// person scrolled, zoomed, or clicked in the frame themselves, which ends a
// follow. `press` says a press started or ended, and `selection` what this
// browser has selected. The page's own messages come here as objects with a
// `segl` field, from the page on segl's origin: `view` shows another
// browser's view, `cursors` the others' cursors, `selections` the others'
// selections, and `keep` the view to come back to after the next load.
// drawio's handler never sees them: this listener runs before drawio's,
// which is added when the editor starts.
(function () {
	var ui = null;
	// The others' cursors, by connection id: { box, x, y, page }.
	var cursors = Object.create(null);
	// The newest view to show while this browser follows someone, or null.
	var wanted = null;
	// drawio's own sessions send no cells when more than this many are selected.
	var SELECTION_LIMIT = 50;
	// The others' selections, each { id, color, page, cells }, and their outlines.
	var selections = [];
	var outlines = [];
	// This browser's selection as last told, as JSON text.
	var told = 'null';
	// The view and the selection to come back to after the next load, or null.
	var keeping = null;
	// The presses held in drawio's document: each pointer id's press number.
	var pressing = Object.create(null);
	var presses = 0;
	var pressed = false;

	function tell(message) {
		window.parent.postMessage(JSON.stringify(message), window.location.origin);
	}

	function pageId() {
		return ui.currentPage != null ? ui.currentPage.getId() : null;
	}

	function viewNow() {
		var graph = ui.editor.graph;
		var container = graph.container;
		var scale = graph.view.scale;
		var translate = graph.view.translate;
		return {
			x: container.scrollLeft / scale - translate.x,
			y: container.scrollTop / scale - translate.y,
			width: container.clientWidth / scale,
			height: container.clientHeight / scale,
			page: pageId()
		};
	}

	function viewChanged() {
		tell({ event: 'view', view: viewNow() });
		place();
	}

	function looked() {
		wanted = null;
		tell({ event: 'looked' });
	}

	// Another browser's view, or null when the follow ended.
	function show(view) {
		wanted = view;
		if (view != null) turnAndFit(view);
	}

	// Turn to the view's page, then fit its area in this frame, centred, at
	// the exact scale: drawio's own fit rounds the scale. A page this diagram
	// does not have yet comes in a patch after the view: see embedLoaded.
	function turnAndFit(view) {
		var graph = ui.editor.graph;
		if (typeof view.page === 'string' && view.page !== pageId()) {
			var page = ui.getPageById(view.page);
			if (page == null) return;
			// Quiet: no undo step. drawio's autosave sends no patch for a page
			// change, but the first turn to a page after a load sends the whole
			// diagram once: drawio then writes the page's settings into it.
			ui.selectPage(page, true);
		}
		var container = graph.container;
		var width = container.clientWidth;
		var height = container.clientHeight;
		var scale = Math.min(width / view.width, height / view.height);
		if (!(scale > 0) || !isFinite(scale)) return;
		graph.zoomTo(scale, null, null, mxUtils.hasScrollbars(container));
		var translate = graph.view.translate;
		var s = graph.view.scale;
		container.scrollLeft = (view.x + translate.x) * s - Math.max((width - view.width * s) / 2, 0);
		container.scrollTop = (view.y + translate.y) * s - Math.max((height - view.height * s) / 2, 0);
	}

	// A cursor as the whiteboards' editor draws one: its arrow, outlined in
	// white, and the name in a box beside it, in the connection's color.
	function makeCursor(name, color) {
		var box = document.createElement('div');
		box.className = 'segl-cursor';
		box.style.cssText =
			'position:absolute;pointer-events:none;z-index:3;display:none;' +
			'left:0;top:0;width:11px;height:14px;white-space:nowrap';
		var svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
		svg.setAttribute('width', '15');
		svg.setAttribute('height', '18');
		svg.setAttribute('viewBox', '-2 -2 15 18');
		svg.style.cssText = 'position:absolute;left:-2px;top:-2px;overflow:visible';
		var arrow = document.createElementNS('http://www.w3.org/2000/svg', 'path');
		arrow.setAttribute('d', 'M0 0L0 14L4 9L11 8Z');
		arrow.setAttribute('stroke-linejoin', 'round');
		var outline = arrow.cloneNode(false);
		outline.setAttribute('fill', 'white');
		outline.setAttribute('stroke', 'white');
		outline.setAttribute('stroke-width', '6');
		arrow.setAttribute('fill', color);
		arrow.setAttribute('stroke', color);
		arrow.setAttribute('stroke-width', '2');
		svg.appendChild(outline);
		svg.appendChild(arrow);
		var label = document.createElement('div');
		label.className = 'segl-cursor__name';
		label.style.cssText =
			'position:absolute;left:5px;top:16px;padding:3px 6px;border-radius:8px;' +
			'border:1px solid white;font:600 12px sans-serif;max-width:160px;' +
			'overflow:hidden;text-overflow:ellipsis';
		label.style.background = color;
		label.style.setProperty('color', 'black');
		label.textContent = name;
		box.appendChild(svg);
		box.appendChild(label);
		return box;
	}

	// The cursors the page sent, each `{ id, name, color, x, y, page }`.
	// The list is all of them: one it leaves out has gone.
	function draw(list) {
		var container = ui.editor.graph.container;
		var kept = Object.create(null);
		for (var i = 0; i < list.length; i++) {
			var given = list[i];
			var held = cursors[given.id];
			if (held == null || held.name !== given.name || held.color !== given.color) {
				if (held != null) held.box.remove();
				held = { box: makeCursor(given.name, given.color), name: given.name, color: given.color };
				container.appendChild(held.box);
			}
			held.x = given.x;
			held.y = given.y;
			held.page = given.page;
			kept[given.id] = held;
		}
		for (var id in cursors) {
			if (kept[id] == null) cursors[id].box.remove();
		}
		cursors = kept;
		place();
	}

	// Each cursor on its point of the diagram, and only on its own page.
	function place() {
		var graph = ui.editor.graph;
		var scale = graph.view.scale;
		var translate = graph.view.translate;
		var page = pageId();
		for (var id in cursors) {
			var held = cursors[id];
			var box = held.box;
			if (held.page !== page) {
				box.style.display = 'none';
				continue;
			}
			box.style.left = (held.x + translate.x) * scale + 'px';
			box.style.top = (held.y + translate.y) * scale + 'px';
			box.style.display = '';
		}
	}

	// Run a function once, after the change at hand: a load clears the
	// selection and sets it again in one go, and the page needs only the end.
	function soon(run) {
		var queued = false;
		return function () {
			if (queued) return;
			queued = true;
			Promise.resolve().then(function () {
				queued = false;
				run();
			});
		};
	}

	function idOf(cell) {
		return cell.getId();
	}

	// This browser's selection: the page and the cell ids, or null for none
	// or for more than drawio's own sessions send.
	function selectionNow() {
		var graph = ui.editor.graph;
		var count = graph.getSelectionCount();
		if (count === 0 || count > SELECTION_LIMIT) return null;
		return { page: pageId(), cells: graph.getSelectionCells().map(idOf) };
	}

	// Put the model's own cell in place of each selected cell it no longer
	// holds, or leave the cell out when the model has none with its id. A
	// shape inserted from the panel is selected again by drawio's pop
	// animation some 200 ms later, by the cell object it had (Sidebar.js
	// itemClicked). A load in between replaces that object: the selection
	// would then hold a cell of the old diagram, and F2 would open no label
	// editor until the selection changed.
	function freshSelection() {
		var graph = ui.editor.graph;
		var cells = graph.getSelectionCells();
		var fresh = [];
		var stale = false;
		for (var i = 0; i < cells.length; i++) {
			var cell = graph.model.getCell(cells[i].getId());
			if (cell !== cells[i]) stale = true;
			if (cell != null) fresh.push(cell);
		}
		if (stale) graph.setSelectionCells(fresh);
	}

	var tellSelection = soon(function () {
		freshSelection();
		var selection = selectionNow();
		var text = JSON.stringify(selection);
		if (text === told) return;
		told = text;
		tell({ event: 'selection', selection: selection });
	});

	function isText(value) {
		return typeof value === 'string' && value !== '';
	}

	// The others' selections the page sent. The list is all of them.
	function takeSelections(list) {
		selections = list.filter(function (given) {
			return (
				given != null &&
				isText(given.id) &&
				isText(given.color) &&
				(given.page === null || isText(given.page)) &&
				Array.isArray(given.cells)
			);
		});
		drawOutlines();
	}

	// Outline each cell the others have selected, on this page, with drawio's
	// mxCellHighlight as its highlightCell builds one (Editor.js), but kept:
	// no fade. An outline is drawn over the diagram, in drawio's overlay, and
	// is never part of it. It follows its cell as the cell moves and goes
	// when the cell does; each patch, load, and page turn draws them again.
	function drawOutlines() {
		for (var i = 0; i < outlines.length; i++) outlines[i].destroy();
		outlines = [];
		var graph = ui.editor.graph;
		var page = pageId();
		for (var j = 0; j < selections.length; j++) {
			var given = selections[j];
			if (given.page !== page) continue;
			for (var k = 0; k < given.cells.length; k++) {
				var id = given.cells[k];
				var cell = typeof id === 'string' ? graph.model.getCell(id) : null;
				var state = cell != null ? graph.view.getState(cell) : null;
				if (state == null) continue;
				var width = Math.max(
					4,
					Number(mxUtils.getValue(state.style, mxConstants.STYLE_STROKEWIDTH, 1)) + 3
				);
				var highlight = new mxCellHighlight(graph, given.color, width, false);
				highlight.opacity = 70;
				highlight.highlight(state);
				if (highlight.shape != null) {
					var node = highlight.shape.node;
					node.classList.add('segl-selection');
					node.setAttribute('data-segl-id', given.id);
					node.setAttribute('data-segl-cell', id);
				}
				outlines.push(highlight);
			}
		}
	}

	var drawOutlinesSoon = soon(drawOutlines);

	// Set the scale, then scroll the diagram's point to the top left, as
	// drawio's own load does with its `scale` and `scroll`.
	function scaleAndScroll(scale, x, y) {
		var graph = ui.editor.graph;
		var container = graph.container;
		if (scale > 0 && isFinite(scale)) graph.zoomTo(scale, null, null);
		var translate = graph.view.translate;
		var s = graph.view.scale;
		if (mxUtils.hasScrollbars(container)) {
			container.scrollLeft = (x + translate.x) * s;
			container.scrollTop = (y + translate.y) * s;
		} else {
			graph.view.setTranslate(-x, -y);
		}
	}

	// The view to come back to after the next load, and what is selected now.
	// The page sends it just before the load.
	function keep(view) {
		var ok =
			view != null &&
			typeof view.scale === 'number' &&
			isFinite(view.x) &&
			isFinite(view.y) &&
			(view.page === null || isText(view.page));
		keeping = ok
			? { view: view, page: pageId(), cells: ui.editor.graph.getSelectionCells().map(idOf) }
			: null;
	}

	// drawio has just put a loaded diagram in place, on its first page, and
	// has not yet taken the copy its autosave compares with, nor set the
	// load's scale and scroll. Turn here, quietly, to the page of the view
	// kept, or of the view this browser follows: the turn is part of the
	// load, so it sends no autosave, and drawio then sets the scale and the
	// point on that page. A turn after the load would send one: drawio
	// writes a page's settings into the diagram the first time it shows it.
	// A page another browser deleted leaves this one on the first page.
	function turnBack() {
		var target = null;
		if (wanted != null && typeof wanted.page === 'string') target = wanted.page;
		else if (keeping != null) target = keeping.view.page;
		if (target === null || target === pageId()) return;
		var page = ui.getPageById(target);
		// Quiet: no undo step.
		if (page != null) ui.selectPage(page, true);
	}

	// After the load: set the view kept, if drawio did not (it sets no
	// scale on an empty page), and select again the cells still on the
	// page. A selection is not part of the diagram: it sends no patch. A
	// read-only view selects nothing, as drawio's own read-only view does.
	function comeBack(kept) {
		var view = kept.view;
		var graph = ui.editor.graph;
		if (view.page !== null && view.page !== pageId()) return;
		if (graph.view.scale !== view.scale) scaleAndScroll(view.scale, view.x, view.y);
		if (kept.page !== pageId() || kept.cells.length === 0 || !graph.isEnabled()) return;
		var cells = [];
		for (var i = 0; i < kept.cells.length; i++) {
			var cell = graph.model.getCell(kept.cells[i]);
			if (cell != null) cells.push(cell);
		}
		if (cells.length > 0) graph.setSelectionCells(cells);
	}

	// A press, anywhere in drawio's document: the canvas, the shape panel,
	// a menu. The page loads nothing in the diagram's place while one is held.
	function pressChanged() {
		var now = Object.keys(pressing).length > 0;
		if (now === pressed) return;
		pressed = now;
		tell({ event: 'press', pressed: now });
	}

	// The end of a press, told once drawio has handled the release. drawio
	// takes the release in its own pointerup and pointercancel listeners,
	// after this window's capture listener: a drop from the shape panel or
	// a move of a shape posts its autosave there. The page must hear that
	// edit before the end of the press, or a load it then asks for would
	// not hold the edit. Timers run after the whole event, so the end is
	// told from one. Only the press the release belongs to ends: a new
	// press may come before the timer.
	function lift(event) {
		var id = event.pointerId;
		var held = pressing[id];
		if (held === undefined) return;
		window.setTimeout(function () {
			if (pressing[id] !== held) return;
			delete pressing[id];
			pressChanged();
		}, 0);
	}

	function watchPresses() {
		window.addEventListener(
			'pointerdown',
			function (event) {
				presses += 1;
				pressing[event.pointerId] = presses;
				pressChanged();
			},
			true
		);
		window.addEventListener('pointerup', lift, true);
		window.addEventListener('pointercancel', lift, true);
		// A release this window did not see: a move with no button down.
		window.addEventListener(
			'pointermove',
			function (event) {
				if (event.buttons === 0 && pressing[event.pointerId]) lift(event);
			},
			true
		);
		// The window lost the focus: whatever was held is let go.
		window.addEventListener('blur', function (event) {
			if (event.target !== window) return;
			pressing = Object.create(null);
			pressChanged();
		});
	}

	function watch(given) {
		ui = given;
		var graph = ui.editor.graph;
		var container = graph.container;
		container.addEventListener('scroll', viewChanged);
		window.addEventListener('resize', viewChanged);
		graph.view.addListener(mxEvent.SCALE, viewChanged);
		graph.view.addListener(mxEvent.TRANSLATE, viewChanged);
		graph.view.addListener(mxEvent.SCALE_AND_TRANSLATE, viewChanged);
		ui.editor.addListener('pageSelected', viewChanged);
		ui.editor.addListener('pageSelected', tellSelection);
		ui.editor.addListener('pageSelected', drawOutlinesSoon);
		graph.getSelectionModel().addListener(mxEvent.CHANGE, tellSelection);
		graph.getModel().addListener(mxEvent.CHANGE, drawOutlinesSoon);
		// drawio fires this after each patch and load from the page.
		ui.addListener('embedLoaded', function (sender, event) {
			if (keeping != null && event.getProperty('action') === 'load') {
				var kept = keeping;
				keeping = null;
				comeBack(kept);
			}
			if (wanted != null && typeof wanted.page === 'string' && wanted.page !== pageId()) {
				turnAndFit(wanted);
			}
			drawOutlines();
		});
		watchPresses();
		container.addEventListener('pointermove', function (event) {
			var bounds = container.getBoundingClientRect();
			var scale = graph.view.scale;
			var translate = graph.view.translate;
			var left = event.clientX - bounds.left - container.clientLeft + container.scrollLeft;
			var top = event.clientY - bounds.top - container.clientTop + container.scrollTop;
			tell({
				event: 'pointer',
				x: left / scale - translate.x,
				y: top / scale - translate.y,
				page: pageId()
			});
		});
		// The person's own scroll, zoom, or click. A zoom from the keyboard
		// takes Ctrl, Cmd, or Alt.
		document.addEventListener('wheel', looked, { capture: true, passive: true });
		document.addEventListener('pointerdown', looked, true);
		document.addEventListener(
			'keydown',
			function (event) {
				if (event.ctrlKey || event.metaKey || event.altKey) looked();
			},
			true
		);
	}

	// drawio's embed handler takes the function that puts a loaded diagram
	// in place. segl turns the page right after it (see turnBack).
	var installMessageHandler = EditorUi.prototype.installMessageHandler;
	EditorUi.prototype.installMessageHandler = function (load) {
		var args = Array.prototype.slice.call(arguments);
		if (typeof load === 'function') {
			args[0] = function () {
				var result = load.apply(this, arguments);
				if (ui != null) turnBack();
				return result;
			};
		}
		var result = installMessageHandler.apply(this, args);
		if (ui == null) watch(this);
		return result;
	};

	window.addEventListener('message', function (event) {
		var data = event.data;
		if (event.source !== window.parent || event.origin !== window.location.origin) return;
		if (data == null || typeof data !== 'object' || typeof data.segl !== 'string') return;
		event.stopImmediatePropagation();
		if (ui == null) return;
		if (data.segl === 'view') show(data.view != null ? data.view : null);
		else if (data.segl === 'cursors' && Array.isArray(data.cursors)) draw(data.cursors);
		else if (data.segl === 'selections' && Array.isArray(data.selections))
			takeSelections(data.selections);
		else if (data.segl === 'keep') keep(data.view);
	});
})();
