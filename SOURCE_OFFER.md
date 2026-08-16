# Corresponding source for official binary releases

The GitHub repository at <https://github.com/FFeederR10/vf-pdf-helper> contains the complete preferred form for modifying VF PDF Helper itself, including its tests, icon generator and Windows build script.

For every official Windows binary release published by the project maintainers:

1. The matching Git tag identifies the application source used for that binary.
2. The release must include or link to release assets controlled by this project containing the exact corresponding source for copyleft runtime components distributed in the package, including PyMuPDF/MuPDF, PySide6/Shiboken and the relevant Qt modules.
3. Build instructions, dependency versions, license texts and third-party notices must accompany the binary.

If a required corresponding-source archive is missing, open an issue in this repository titled `Corresponding source request` and identify the binary version. For at least three years after an official binary is distributed, the maintainers offer to provide the applicable machine-readable corresponding source at no charge other than reasonable physical distribution cost.

Locally built or unofficial third-party binaries are not official project releases; their distributors are responsible for satisfying the applicable licenses.

