from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

try:
    from tools.validate_archseed import ValidationError, load_json, validate_archseed
except ModuleNotFoundError:
    from validate_archseed import ValidationError, load_json, validate_archseed


CORRUPTION_MODES = (
    "missing-required",
    "invalid-dimension",
    "invalid-opening-wall",
)


class InvalidFixtureError(ValueError):
    pass


def corrupt_archseed_json(
    source: dict[str, Any],
    corruption: str,
) -> dict[str, Any]:
    validate_archseed(source)
    corrupted = copy.deepcopy(source)

    if corruption == "missing-required":
        corrupted.pop("units")
    elif corruption == "invalid-dimension":
        corrupted["building"]["footprint"]["width"] = -1
    elif corruption == "invalid-opening-wall":
        openings = corrupted["building"].setdefault("openings", [])
        if openings:
            openings[0]["wall"] = "invalid-wall"
        else:
            openings.append(
                {
                    "type": "window",
                    "level": 0,
                    "wall": "invalid-wall",
                    "offset_mm": 0,
                    "width_mm": 1000,
                    "height_mm": 1000,
                    "sill_height_mm": 900,
                }
            )
    else:
        raise InvalidFixtureError(f"unsupported corruption mode: {corruption}")

    try:
        validate_archseed(corrupted)
    except ValidationError:
        return corrupted
    raise InvalidFixtureError("corruption did not make the ArchSeed JSON invalid")


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create intentionally invalid ArchSeed JSON for repair testing."
    )
    parser.add_argument("source", type=Path, help="Valid ArchSeed JSON source path.")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--corruption",
        choices=CORRUPTION_MODES,
        default="invalid-dimension",
        help="Intentional validation failure to introduce.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        source = load_json(args.source)
        if not isinstance(source, dict):
            raise InvalidFixtureError("source JSON must contain one object")
        corrupted = corrupt_archseed_json(source, args.corruption)
        write_json(args.output, corrupted)
        try:
            validate_archseed(corrupted)
        except ValidationError as exc:
            validation_message = str(exc)
        else:
            raise InvalidFixtureError("output unexpectedly passed validation")
    except (OSError, json.JSONDecodeError, ValidationError, InvalidFixtureError) as exc:
        print(f"Invalid fixture creation failed: {exc}", file=sys.stderr)
        return 1

    print(f"WROTE INVALID JSON: {args.output}")
    print(f"EXPECTED INVALID: {validation_message}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
