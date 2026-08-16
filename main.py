from __future__ import annotations

import ctypes
import os
import sys
import traceback
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from pdf_helper.app_info import APP_ID, APP_NAME
from pdf_helper.ui import MainWindow, configure_application


def _set_windows_app_id() -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(  # type: ignore[attr-defined]
            APP_ID
        )
    except Exception:
        pass


def _initial_pdf(arguments: list[str]) -> str | None:
    for argument in arguments[1:]:
        path = Path(argument.strip('"')).expanduser()
        if path.is_file() and path.suffix.lower() == ".pdf":
            return str(path.resolve())
    return None


def _install_exception_handler() -> None:
    def handle_exception(exc_type, exc_value, exc_traceback) -> None:
        details = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
        try:
            log_dir = Path(os.environ.get("LOCALAPPDATA", str(Path.cwd()))) / APP_NAME
            log_dir.mkdir(parents=True, exist_ok=True)
            (log_dir / "error.log").write_text(details, encoding="utf-8")
        except Exception:
            pass
        QMessageBox.critical(
            None,
            f"{APP_NAME} 遇到错误",
            "程序遇到未预期的错误。\n\n"
            f"错误记录已保存到本机 AppData 的 {APP_NAME} 文件夹。",
        )

    sys.excepthook = handle_exception


def _resource_path(relative: str) -> Path:
    bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return bundle_root / relative


def main() -> int:
    _set_windows_app_id()
    app = QApplication(sys.argv)
    configure_application(app)
    icon_path = _resource_path("assets/vf-pdf-helper.ico")
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    _install_exception_handler()
    window = MainWindow(_initial_pdf(sys.argv))
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
