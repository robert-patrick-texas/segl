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
 * a label editor opening and closing, the scroll, and, for follow mode and
 * cursors (T18), where the person looks and points, and the others' cursors.
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
// where the diagram is scrolled to as well. The page keeps a person's view
// when it loads the whole diagram again to put a drifted copy right.
(function () {
	var createLoadMessage = EditorUi.prototype.createLoadMessage;
	EditorUi.prototype.createLoadMessage = function () {
		var message = createLoadMessage.apply(this, arguments);
		var container = this.editor.graph.container;
		message.scroll = { left: container.scrollLeft, top: container.scrollTop };
		return message;
	};
})();

// segl: tell the page when a label editor opens and closes. The page loads
// nothing in the diagram's place while a person is typing.
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
		tell(true);
		return result;
	};
	mxCellEditor.prototype.stopEditing = function () {
		var result = stopEditing.apply(this, arguments);
		tell(false);
		return result;
	};
})();

// segl: where the person looks and points, and the others' cursors (T18).
//
// The page sends `view` only while someone follows this browser, and a
// `pointer` as the person's pointer moves over the diagram. Both are in
// diagram coordinates, on the page of the diagram named. `looked` says the
// person scrolled, zoomed, or clicked in the frame themselves, which ends a
// follow. The page's own messages come here as objects with a `segl` field,
// from the page on segl's origin: `view` shows another browser's view, and
// `cursors` the others' cursors. drawio's handler never sees them: this
// listener runs before drawio's, which is added when the editor starts.
(function () {
	var ui = null;
	// The others' cursors, by connection id: { box, x, y, page }.
	var cursors = Object.create(null);
	// The newest view to show while this browser follows someone, or null.
	var wanted = null;

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
			// Quiet: no undo step. drawio's autosave skips a page change.
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
		// drawio fires this after each patch and load from the page.
		ui.addListener('embedLoaded', function () {
			if (wanted != null && typeof wanted.page === 'string' && wanted.page !== pageId()) {
				turnAndFit(wanted);
			}
		});
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

	var installMessageHandler = EditorUi.prototype.installMessageHandler;
	EditorUi.prototype.installMessageHandler = function () {
		var result = installMessageHandler.apply(this, arguments);
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
	});
})();
