# License texts segl keeps

The web build bundles npm packages and carries the editor's fonts. Whoever passes the build on must pass their license texts on too. Most npm packages ship their own text, and `web/scripts/collect-licenses.ts` copies it. This folder holds the texts for what ships none.

`collect-licenses.ts` fails when a bundled package or a font has no text, and when a text here is for nothing in the build. pytest runs it against the real build (`tests/test_package.py`), and the package build runs it (`deploy/debian/build.sh`). The `.deb` installs the result under `/usr/share/doc/segl/`.

Each text is copied as its source has it. Fetched on 2026-11-13.

## Packages

These npm packages have no license file in their npm files. Each names MIT in its `package.json`.

| Package | File | Source of the text |
|---|---|---|
| `@excalidraw/excalidraw` | `packages/excalidraw.txt` | `LICENSE` in <https://github.com/excalidraw/excalidraw>, at tag `v0.18.0` |
| every `@radix-ui/` package | `packages/radix-ui.txt` | `LICENSE` in <https://github.com/radix-ui/primitives> |
| `fastdom` | `packages/fastdom.txt` | The License section of `README.md` in <https://github.com/wilsonpage/fastdom>. The repository has no license file. |
| `react-remove-scroll-bar` | `packages/react-remove-scroll-bar.txt` | `LICENSE` in <https://github.com/theKashey/react-remove-scroll-bar> |

## Fonts

`@excalidraw/excalidraw` ships nine font families in `dist/prod/fonts` and no license text for any. The license of each was read from the font file segl ships (its `name` table) and checked against the font's own project.

| Font | License | Files | Source of the text |
|---|---|---|---|
| Assistant | OFL-1.1 | `fonts/Assistant/OFL.txt` | `ofl/assistant/OFL.txt` in <https://github.com/google/fonts> |
| Cascadia | OFL-1.1 | `fonts/Cascadia/LICENSE` | `LICENSE` in <https://github.com/microsoft/cascadia-code> |
| ComicShanns | MIT | `fonts/ComicShanns/LICENSE` | The copyright record of the shipped font file, which holds the whole text |
| Excalifont | OFL-1.1 | `fonts/Excalifont/OFL.txt` | The font's copyright, trademark, and license records, as Excalidraw's `packages/excalidraw/fonts/Excalifont/index.ts` lists them. The shipped file has the copyright record and no license record. |
| Liberation | OFL-1.1 | `fonts/Liberation/OFL.txt` | `LICENSE` in `liberation-fonts-ttf-2.1.5.tar.gz`, the same text as `LICENSE` in <https://github.com/liberationfonts/liberation-fonts>. This is the license of the file segl ships, not of the editor's (below). |
| Lilita | OFL-1.1 | `fonts/Lilita/OFL.txt` | `ofl/lilitaone/OFL.txt` in <https://github.com/google/fonts> |
| Nunito | OFL-1.1 | `fonts/Nunito/OFL.txt` | `ofl/nunito/OFL.txt` in <https://github.com/google/fonts> |
| Virgil | OFL-1.1 | `fonts/Virgil/OFL.txt` | `LICENSE.md` in <https://github.com/excalidraw/virgil> |
| Xiaolai | OFL-1.1 | `fonts/Xiaolai/OFL.txt` | `OFL.txt` in <https://github.com/lxgw/kose-font> |

## The font segl replaces

The editor's Liberation Sans is version 1.05, from 2009. That version is under Red Hat's license agreement: the GNU General Public License version 2, with an exception for a document that embeds the font. Liberation moved to the SIL Open Font License with version 2.

segl does not ship the editor's file. `web/fonts/Liberation/LiberationSans-Regular.woff2` is Liberation Sans 2.1.5, and the build lays it over the copy of the editor's fonts at the same path (`web/scripts/editor-fonts.ts`, D2-026). The editor's code is not changed: it asks for `fonts/Liberation/LiberationSans-Regular.woff2` and gets this file.

Where the file comes from:

| | |
|---|---|
| Release | Liberation Fonts 2.1.5, <https://github.com/liberationfonts/liberation-fonts/releases/tag/2.1.5> |
| Archive | `liberation-fonts-ttf-2.1.5.tar.gz`, SHA-256 `7191c669bf38899f73a2094ed00f7b800553364f90e2637010a69c0e268f25d0` |
| Font | `LiberationSans-Regular.ttf` in it, SHA-256 `76d04c18ea243f426b7de1f3ad208e927008f961dc5945e5aad352d0dfde8ee8` |
| Shipped file | `web/fonts/Liberation/LiberationSans-Regular.woff2`, SHA-256 `169d0ac29ae2d1073342aa0434d309043484bae4abd3f721ab4a04aebb8a2c0e` |

The shipped file is that font, compressed to WOFF2 and not changed otherwise, with fontTools 4.68.0 and brotli 1.2.1:

```python
from fontTools.ttLib import TTFont

font = TTFont("LiberationSans-Regular.ttf")
font.flavor = "woff2"
font.save("LiberationSans-Regular.woff2")
```

Its own records say `Version 2.1.5` and `Licensed under the SIL Open Font License, Version 1.1`.

What changes for a drawing:

- The metrics the editor works with are the same: 2048 units per em, ascender 1854, descender -434.
- The new file has 2,620 glyphs where the old had 675, and is 147 kB where the old was 71 kB.
- Two characters both files have differ in width: the middle dot (U+00B7) and the figure dash (U+2012).
- Four characters of the old file are not in the new one: the non-breaking hyphen (U+2011) and three private-use code points (U+F001, U+F002, U+F005). A browser draws a missing character in another font.
- The editor does not offer this family in its font list, and a page does not fetch the file until some text uses it. `web/e2e/fonts.spec.ts` asks the page to load it and compares the bytes.

`tests/test_package.py` holds the shipped file to the SHA-256 above and to the file in the real web build.

To move to a newer Liberation Sans: fetch the release, check the license record of the font (`name` record 13), compress it as above, replace the file, and put the new hashes here.

## When the editor moves

A new `@excalidraw/excalidraw` can bundle a package with no license file, ship another font, or move the font segl replaces. The build stops when `web/fonts/` holds a file the editor no longer ships. `collect-licenses.ts` then fails and names it. Add the text here, with its source in the tables above. For a font, read the `name` table of the shipped file first: records 0 (copyright), 13 (license), and 14 (license address).
