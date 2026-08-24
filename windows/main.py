from __future__ import annotations

import argparse
import ctypes
import json
import os
from pathlib import Path
import sys

from application.services import LearningService
from infrastructure.catalog import CatalogLoader
from infrastructure.csv_importer import CsvVocabularyImporter
from infrastructure.repository import JsonLearningRepository
from presentation.app import LexiTrackApp, run_gui_smoke


def enable_high_dpi() -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except (AttributeError, OSError):
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except (AttributeError, OSError):
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except (AttributeError, OSError):
                pass


def resource_root() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent


def default_data_dir() -> Path:
    configured = os.environ.get("LEXITRACK_DATA_DIR")
    if configured:
        return Path(configured).expanduser()
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "LexiTrack"
    return Path.home() / "AppData" / "Local" / "LexiTrack"


def build_app(data_dir: Path) -> LexiTrackApp:
    loader = CatalogLoader(resource_root() / "shared" / "content" / "catalog.json")
    catalog = loader.load()
    repository = JsonLearningRepository(data_dir, catalog)
    service = LearningService(repository, CsvVocabularyImporter())
    return LexiTrackApp(
        service=service,
        data_dir=data_dir,
        catalog_count=len(catalog),
        catalog_rejected=loader.rejected_count,
        catalog_error=loader.error,
    )


def parse_args(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description="LexiTrack 词程 Windows 客户端")
    parser.add_argument("--data-dir", type=Path, default=default_data_dir())
    parser.add_argument("--smoke-test", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    enable_high_dpi()
    app = build_app(args.data_dir)
    if args.smoke_test:
        result = run_gui_smoke(app)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result["ok"] and result["studyCardReady"] else 1
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
