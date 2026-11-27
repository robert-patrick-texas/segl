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
 * editor starts. It sets what the release's file sets, and adds three
 * things the page needs that drawio's embed messages do not carry.
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
