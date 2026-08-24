# Third-party notices

VF PDF Helper is licensed as a whole under GNU AGPL v3. The following components retain their own copyright notices and license terms.

## Runtime and distributed components

### PyMuPDF / MuPDF 1.28.0

- Purpose: PDF rendering, inspection, forms, annotations and editing
- License used by this project: GNU Affero General Public License v3
- Copyright: Artifex Software, Inc. and contributors
- Source: <https://github.com/pymupdf/PyMuPDF>
- License: the repository root [LICENSE](LICENSE)

PyMuPDF and MuPDF are also available separately under a commercial license from Artifex. VF PDF Helper does not use that commercial option.

### PySide6, PySide6 Essentials, Shiboken6 and Qt 6.11.1

- Purpose: Windows desktop user interface
- License option selected by this project: GNU General Public License v3
- Copyright: The Qt Company Ltd., the Qt Project and contributors
- Source: <https://code.qt.io/cgit/pyside/pyside-setup.git/> and <https://code.qt.io/cgit/qt/qt5.git/>
- License text: [licenses/GPL-3.0.txt](licenses/GPL-3.0.txt)

PySide6 is offered under LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only (and a separate commercial license). Because VF PDF Helper is AGPL v3 software, this project selects the GPL-3.0-only option for the combined open-source application. Qt may include additional permissively licensed third-party components; an official binary release must preserve the notices for the exact files it distributes.

### nanoPRC / nanoprc-py 0.1.2

- Purpose: parsing embedded PRC model streams and exposing their tessellated geometry to the built-in 3D viewer
- License: GNU Affero General Public License v3 or later
- Copyright: 2023-2026 CascadiaVoxel LLC and contributors
- Source: <https://github.com/mvrhel/nanoPRC>
- License: the repository root [LICENSE](LICENSE)

### NumPy 2.4.2

- Purpose: geometry arrays, bounds, normals and lighting calculations for the built-in 3D viewer
- License: BSD-3-Clause, with additional notices for software bundled in the official NumPy wheel
- Copyright: 2005-2025 NumPy Developers
- Source: <https://github.com/numpy/numpy>
- License text: copied from the installed NumPy distribution to `licenses/NumPy-LICENSE.txt` by `build.ps1`

The NumPy wheel may include OpenBLAS and other permissively licensed components. The complete license file from the exact installed wheel must remain beside any distributed Windows binary.

### Intel Universal 3D Sample Software (adapted portions)

- Purpose: ECMA-363 arithmetic decoding and CLOD base-mesh field ordering used by the built-in U3D preview decoder
- License: Apache License 2.0
- Copyright: 1999-2006 Intel Corporation
- Source: <https://github.com/ningfei/u3d>
- License text: [licenses/Apache-2.0.txt](licenses/Apache-2.0.txt)

VF PDF Helper contains a Python adaptation of the relevant decoding behavior rather than redistributing the Intel runtime or viewer. The adaptation retains Intel's copyright and Apache-2.0 attribution in `pdf_helper/u3d.py`.

### Pillow 11.3.0

- Purpose: image support pulled into the packaged runtime and generation of the project-owned PNG/ICO application icon
- License: MIT-CMU
- Source: <https://github.com/python-pillow/Pillow>
- License text: [licenses/Pillow-LICENSE.txt](licenses/Pillow-LICENSE.txt)

### Python 3.12

- Purpose: application runtime included in Windows binary builds
- License: Python Software Foundation License and included third-party notices
- Source: <https://github.com/python/cpython>
- License text: [licenses/Python-LICENSE.txt](licenses/Python-LICENSE.txt)

## Build and development components

### PyInstaller 6.21.0

- Purpose: Windows packaging
- License: GPL v2 or later with a special exception for generated application bundles
- Source: <https://github.com/pyinstaller/pyinstaller>
- License and exception text: [licenses/PyInstaller-COPYING.txt](licenses/PyInstaller-COPYING.txt)

### pytest 9.1.1

- Purpose: development tests; not part of the application runtime
- License: MIT
- Source: <https://github.com/pytest-dev/pytest>
- License text: [licenses/pytest-LICENSE.txt](licenses/pytest-LICENSE.txt)

No Microsoft/Windows font file is included in this repository or intended to be included in an official application package.
