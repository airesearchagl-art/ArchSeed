from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from tools.generate_archseed_json import generate_draft
    from tools.print_sketchup_import_command import build_import_command
    from tools.validate_archseed import ValidationError, validate_archseed
except ModuleNotFoundError:
    from generate_archseed_json import generate_draft
    from print_sketchup_import_command import build_import_command
    from validate_archseed import ValidationError, validate_archseed


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def create_session(
    description: str,
    output_json: Path,
    output_session: Path,
) -> tuple[dict[str, Any], bool]:
    draft, used_fallback = generate_draft(description)
    write_json(output_json, draft)

    try:
        validate_archseed(draft)
        validation_status = "VALID"
        validation_message = f"VALID: {output_json}"
    except ValidationError as exc:
        validation_status = "INVALID"
        validation_message = f"INVALID: {exc}"

    generator_mode = (
        "fixed_preset_fallback" if used_fallback else "fixed_preset"
    )
    notes = (
        "Generated locally from fixed preset keywords. "
        "No LLM API or external API was used."
    )
    if used_fallback:
        notes += " Unknown input used the simple house fallback."

    session = {
        "user_prompt": description,
        "generator_mode": generator_mode,
        "generated_archseed_json_path": output_json.expanduser()
        .resolve()
        .as_posix(),
        "validation_status": validation_status,
        "validation_message": validation_message,
        "sketchup_import_command": build_import_command(output_json),
        "created_at": datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        "notes": notes,
    }
    write_json(output_session, session)
    return session, used_fallback


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create a local ArchSeed JSON draft session."
    )
    parser.add_argument("description", help="Short building description.")
    parser.add_argument(
        "--output-session",
        type=Path,
        required=True,
        help="Draft session JSON path.",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        required=True,
        help="Generated ArchSeed JSON path.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    session, used_fallback = create_session(
        args.description,
        args.output_json,
        args.output_session,
    )

    if used_fallback:
        print("WARNING: no known preset matched; used simple house fallback.")
    print(f"WROTE JSON: {args.output_json}")
    print(f"WROTE SESSION: {args.output_session}")
    print(session["validation_message"])
    return 0 if session["validation_status"] == "VALID" else 1


if __name__ == "__main__":
    raise SystemExit(main())
