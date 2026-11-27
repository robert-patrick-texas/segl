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
 * segl's copy of drawio's js/PreConfig.js, a settings file a site may
 * replace (D2-039). drawio loads it before its own code. The build lays it
 * over the release's file (web/scripts/drawio.ts). It sets what the
 * release's file sets, and one thing more: the shape sets shown at first.
 */
// Overrides of global vars need to be pre-loaded
window.DRAWIO_PUBLIC_BUILD = true;
// With null, export to PDF uses the browser's print dialog.
window.EXPORT_URL = null;
window.DRAWIO_BASE_URL = null;
window.DRAWIO_VIEWER_URL = null;
window.DRAWIO_LIGHTBOX_URL = null;
window.DRAW_MATH_URL = 'math4/es5';
// segl: drawio's default sets, with Network and Cisco among them. More
// Shapes adds others, and drawio remembers a person's choice.
window.DRAWIO_CONFIG = {
	defaultLibraries: 'general;basic;arrows2;flowchart;network;cisco19'
};
urlParams['sync'] = 'manual';
