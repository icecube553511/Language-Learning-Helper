"""Validate and prepare the optional Bingzi appearance asset set.

The source directory is intentionally separate from platform resources. This
tool is the only supported path from developer-provided PNGs to runtime
assets, and its manifest gives both clients the same ordered happy group.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shutil


CONTRACT_VERSION = "pet-appearance-v1"
DEFAULT_SOURCE = Path("shared/assets/branding/pet_states")
DEFAULT_RUNTIME = Path("shared/assets/pets/states")
STATE_FILES = {
    "pain": "pain.png",
    "scared": "scared.png",
    "sleep": "sleep.png",
    "hungry": "hungry.png",
}
HAPPY_PATTERN = re.compile(r"^happy([1-9][0-9]*)\.png$")
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _happy_sort_key(name: str) -> tuple[int, str]:
    match = HAPPY_PATTERN.fullmatch(name)
    return (int(match.group(1)), name) if match else (0, name)


def discover(source: Path) -> dict[str, object]:
    """Return a deterministic asset inventory without importing platform APIs."""
    if source.is_dir():
        unknown_state_assets = sorted(
            path.name
            for path in source.iterdir()
            if path.is_file() and path.suffix.casefold() == ".png" and path.name not in STATE_FILES.values()
        )
        if unknown_state_assets:
            raise ValueError(f"unsupported state asset filename(s): {', '.join(unknown_state_assets)}")

    state_assets: dict[str, str | None] = {}
    for key, filename in STATE_FILES.items():
        path = source / filename
        state_assets[key] = filename if path.is_file() else None

    happy_directory = source / "happy"
    if happy_directory.is_dir():
        unknown_happy_assets = sorted(
            path.name
            for path in happy_directory.iterdir()
            if path.is_file() and path.suffix.casefold() == ".png" and not HAPPY_PATTERN.fullmatch(path.name)
        )
        if unknown_happy_assets:
            raise ValueError(f"unsupported happy asset filename(s): {', '.join(unknown_happy_assets)}")
    happy_assets = (
        sorted(
            (path.name for path in happy_directory.iterdir() if path.is_file() and HAPPY_PATTERN.fullmatch(path.name)),
            key=_happy_sort_key,
        )
        if happy_directory.is_dir()
        else []
    )
    complete = all(value is not None for value in state_assets.values()) and bool(happy_assets)
    return {
        "contractVersion": CONTRACT_VERSION,
        "stateAssets": state_assets,
        "happyAssets": happy_assets,
        "enabled": complete,
        "disabledReason": None if complete else "appearance PNG set is incomplete",
    }


def _validate_png(path: Path) -> None:
    with path.open("rb") as stream:
        if stream.read(len(PNG_SIGNATURE)) != PNG_SIGNATURE:
            raise ValueError(f"not a PNG file: {path}")


def _clear_generated_assets(runtime: Path) -> None:
    """Remove only PNGs previously owned by this generator."""
    for filename in STATE_FILES.values():
        generated_path = runtime / filename
        if generated_path.is_file():
            generated_path.unlink()
    happy_directory = runtime / "happy"
    if happy_directory.is_dir():
        for generated_path in happy_directory.iterdir():
            if generated_path.is_file() and HAPPY_PATTERN.fullmatch(generated_path.name):
                generated_path.unlink()


def prepare(source: Path, runtime: Path, manifest_path: Path | None = None) -> dict[str, object]:
    """Copy valid source assets and write the generated runtime manifest."""
    source = source.resolve()
    runtime = runtime.resolve()
    inventory = discover(source)
    runtime.mkdir(parents=True, exist_ok=True)
    _clear_generated_assets(runtime)
    for filename in STATE_FILES.values():
        path = source / filename
        if path.is_file():
            _validate_png(path)
            shutil.copy2(path, runtime / filename)
    happy_assets = inventory["happyAssets"]
    if isinstance(happy_assets, list):
        for filename in happy_assets:
            path = source / "happy" / filename
            _validate_png(path)
            target = runtime / "happy" / filename
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)

    output = dict(inventory)
    output["sourceDirectory"] = "shared/assets/branding/pet_states"
    output["runtimeDirectory"] = "shared/assets/pets/states"
    destination = manifest_path.resolve() if manifest_path is not None else runtime / "manifest.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare optional Bingzi appearance assets")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--runtime", type=Path, default=DEFAULT_RUNTIME)
    parser.add_argument("--manifest", type=Path, default=None)
    args = parser.parse_args()
    output = prepare(args.source, args.runtime, args.manifest)
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
