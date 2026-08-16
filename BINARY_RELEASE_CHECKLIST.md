# Binary release checklist

Do not publish a Windows binary until every item below is complete.

- Build from a clean, signed or documented Git tag.
- Run the complete automated test suite.
- Confirm the executable reports the expected product name and version.
- Inspect the generated directory and record every distributed DLL, plugin and Python package.
- Attach the exact corresponding source archives for PyMuPDF/MuPDF, PySide6/Shiboken and all distributed Qt modules to the GitHub release.
- Include `LICENSE`, `THIRD_PARTY_NOTICES.md`, `SOURCE_OFFER.md` and the `licenses` directory beside the executable.
- Confirm no Windows font file, user PDF, test output, credential, token or local path is included.
- Scan the package with current malware scanners and publish a SHA-256 checksum.
- Test the ZIP on a clean Windows 10/11 machine before publishing it.

