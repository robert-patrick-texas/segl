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
| Liberation | GPL-2 with exceptions | `fonts/Liberation/License.txt`, `fonts/Liberation/COPYING` | `License.txt` and `COPYING` in <https://github.com/liberationfonts/liberation-1.7-fonts> |
| Lilita | OFL-1.1 | `fonts/Lilita/OFL.txt` | `ofl/lilitaone/OFL.txt` in <https://github.com/google/fonts> |
| Nunito | OFL-1.1 | `fonts/Nunito/OFL.txt` | `ofl/nunito/OFL.txt` in <https://github.com/google/fonts> |
| Virgil | OFL-1.1 | `fonts/Virgil/OFL.txt` | `LICENSE.md` in <https://github.com/excalidraw/virgil> |
| Xiaolai | OFL-1.1 | `fonts/Xiaolai/OFL.txt` | `OFL.txt` in <https://github.com/lxgw/kose-font> |

Liberation is the one to know about. The file the editor ships is Liberation Sans 1.05, from 2009. That version is under Red Hat's license agreement: the GNU General Public License version 2, with an exception for a document that embeds the font. Liberation moved to the OFL with version 2. The Liberation Fonts project publishes the 1.x fonts and their sources in the repository above.

## When the editor moves

A new `@excalidraw/excalidraw` can bundle a package with no license file, or ship another font. `collect-licenses.ts` then fails and names it. Add the text here, with its source in the tables above. For a font, read the `name` table of the shipped file first: records 0 (copyright), 13 (license), and 14 (license address).
