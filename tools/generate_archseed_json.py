from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from pathlib import Path
from typing import Any

try:
    from tools.validate_archseed import ValidationError, validate_archseed
except ModuleNotFoundError:
    from validate_archseed import ValidationError, validate_archseed


PRESETS: dict[str, dict[str, Any]] = {
    "simple_house": {
        "project_name": "Generated Simple House",
        "footprint": {"width": 7200, "depth": 5400},
        "levels": [
            {"name": "Level 1", "height": 3000},
            {"name": "Level 2", "height": 2800},
        ],
        "wallThickness": 150,
        "slabThickness": 180,
        "roof": {"type": "flat", "parapetHeight": 300},
    },
    "compact_house": {
        "project_name": "Generated Compact House",
        "footprint": {"width": 4800, "depth": 3600},
        "levels": [{"name": "Ground Floor", "height": 2700}],
        "wallThickness": 140,
        "slabThickness": 160,
        "roof": {"type": "flat", "parapetHeight": 250},
    },
    "small_office": {
        "project_name": "Generated Small Office",
        "footprint": {"width": 9600, "depth": 7200},
        "levels": [{"name": "Office Level", "height": 3300}],
        "wallThickness": 180,
        "slabThickness": 200,
        "roof": {"type": "flat", "parapetHeight": 450},
    },
    "two_story": {
        "project_name": "Generated Two Story Building",
        "footprint": {"width": 6400, "depth": 4800},
        "levels": [
            {"name": "Level 1", "height": 3000},
            {"name": "Level 2", "height": 3000},
        ],
        "wallThickness": 160,
        "slabThickness": 200,
        "roof": {"type": "flat", "parapetHeight": 350},
    },
}

OPENINGS = [
    {
        "type": "window",
        "level": 0,
        "wall": "south",
        "offset_mm": 900,
        "width_mm": 1200,
        "height_mm": 1200,
        "sill_height_mm": 900,
    },
    {
        "type": "door",
        "level": 0,
        "wall": "east",
        "offset_mm": 900,
        "width_mm": 900,
        "height_mm": 2100,
    },
]


def normalize_description(description: str) -> str:
    return re.sub(r"[\s_-]+", " ", description.strip().lower())


def select_preset(description: str) -> tuple[str, bool]:
    normalized = normalize_description(description)
    if "small office" in normalized:
        return "small_office", False
    if "compact house" in normalized:
        return "compact_house", False
    if "two story" in normalized or "two storey" in normalized:
        return "two_story", False
    if "simple house" in normalized:
        return "simple_house", False
    if "openings" in normalized:
        return "simple_house", False
    return "simple_house", True


def generate_draft(description: str) -> tuple[dict[str, Any], bool]:
    preset_name, used_fallback = select_preset(description)
    preset = copy.deepcopy(PRESETS[preset_name])
    normalized = normalize_description(description)

    project_name = preset.pop("project_name")
    if "openings" in normalized:
        project_name += " with Openings"
        preset["openings"] = copy.deepcopy(OPENINGS)

    draft = {
        "schemaVersion": "archseed.v0.1",
        "units": "mm",
        "project": {
            "name": project_name,
            "description": f"Generated from preset keywords: {description}"[:1000],
        },
        "building": preset,
    }
    return draft, used_fallback


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate an ArchSeed v0.1 JSON draft from preset keywords."
    )
    parser.add_argument("description", help="Short building description.")
    parser.add_argument(
        "--output",
        type=Path,
        help="Output JSON path. Prints to stdout when omitted.",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Validate the generated draft before writing it.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    draft, used_fallback = generate_draft(args.description)

    if used_fallback:
        print(
            "WARNING: no known preset matched; using the simple house preset.",
            file=sys.stderr,
        )

    if args.validate:
        try:
            validate_archseed(draft)
        except ValidationError as exc:
            print(f"INVALID: {exc}", file=sys.stderr)
            return 1

    output = json.dumps(draft, indent=2, ensure_ascii=False) + "\n"
    if args.output is None:
        print(output, end="")
        if args.validate:
            print("VALID: generated JSON", file=sys.stderr)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
        print(f"WROTE: {args.output}")
        if args.validate:
            print(f"VALID: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
