from __future__ import annotations

import argparse
import json
from pathlib import Path


def build_import_command(json_path: Path) -> str:
    normalized_path = json_path.expanduser().resolve().as_posix()
    ruby_path = json.dumps(normalized_path, ensure_ascii=False)
    return f"ArchSeed.import_json({ruby_path})"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Print an ArchSeed import command for the SketchUp Ruby Console."
    )
    parser.add_argument("json_path", type=Path, help="ArchSeed JSON file path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    print(build_import_command(args.json_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
