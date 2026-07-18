from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from http.client import HTTPConnection, HTTPException
from pathlib import Path
from typing import Any

try:
    from tools.preview_llm_prompt import DEFAULT_CONFIG_PATH, build_prompt
    from tools.print_sketchup_import_command import build_import_command
    from tools.validate_archseed import ValidationError, validate_archseed
    from tools.validate_llm_config import (
        ConfigValidationError,
        load_json,
        parse_local_base_url,
        validate_llm_config,
    )
except ModuleNotFoundError:
    from preview_llm_prompt import DEFAULT_CONFIG_PATH, build_prompt
    from print_sketchup_import_command import build_import_command
    from validate_archseed import ValidationError, validate_archseed
    from validate_llm_config import (
        ConfigValidationError,
        load_json,
        parse_local_base_url,
        validate_llm_config,
    )


MAX_RESPONSE_BYTES = 2_000_000
DEFAULT_TIMEOUT_SECONDS = 180.0


class LMStudioGenerationError(RuntimeError):
    pass


class JSONExtractionError(ValueError):
    pass


def utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def strip_markdown_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```") or not stripped.endswith("```"):
        return stripped

    lines = stripped.splitlines()
    if len(lines) < 3:
        return stripped
    return "\n".join(lines[1:-1]).strip()


def extract_json_object(text: str) -> dict[str, Any]:
    candidates = [text.strip(), strip_markdown_fence(text)]
    decoder = json.JSONDecoder()

    for candidate in candidates:
        if not candidate:
            continue
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            pass
        else:
            if isinstance(value, dict):
                return value

    for start in (index for index, char in enumerate(text) if char == "{"):
        try:
            value, _end = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value

    raise JSONExtractionError("LM Studio response did not contain a JSON object.")


def request_json(
    host: str,
    port: int,
    path: str,
    *,
    method: str,
    payload: dict[str, Any] | None = None,
    timeout: float,
) -> dict[str, Any]:
    connection = HTTPConnection(host, port, timeout=timeout)
    headers = {"Accept": "application/json"}
    body = None
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    try:
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        payload_bytes = response.read(MAX_RESPONSE_BYTES + 1)
    except (OSError, HTTPException) as exc:
        raise LMStudioGenerationError(
            "LM Studio local server is unavailable. Start Local Server in "
            "LM Studio and try again."
        ) from exc
    finally:
        connection.close()

    if len(payload_bytes) > MAX_RESPONSE_BYTES:
        raise LMStudioGenerationError("LM Studio response exceeded the safety limit.")
    if not 200 <= response.status < 300:
        error_detail = payload_bytes.decode("utf-8", "replace").strip()
        if len(error_detail) > 500:
            error_detail = f"{error_detail[:500]}..."
        suffix = f": {error_detail}" if error_detail else "."
        raise LMStudioGenerationError(
            f"LM Studio endpoint returned HTTP {response.status}{suffix}"
        )

    try:
        value = json.loads(payload_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LMStudioGenerationError(
            "LM Studio endpoint did not return valid JSON."
        ) from exc
    if not isinstance(value, dict):
        raise LMStudioGenerationError("LM Studio endpoint returned non-object JSON.")
    return value


def score_model_id(model_id: str) -> int:
    lowered = model_id.lower()
    if "embedding" in lowered or "embed" in lowered:
        return -100

    score = 0
    for keyword, weight in (
        ("instruct", 30),
        ("coder", 20),
        ("chat", 10),
    ):
        if keyword in lowered:
            score += weight
    return score


def select_model_from_list(models: list[Any]) -> str:
    candidates = [
        model["id"].strip()
        for model in models
        if isinstance(model, dict)
        and isinstance(model.get("id"), str)
        and model["id"].strip()
    ]
    candidates = [
        model_id
        for model_id in candidates
        if score_model_id(model_id) >= 0
    ]
    if not candidates:
        raise LMStudioGenerationError(
            "No local LM Studio chat model was reported. Load a chat model and "
            "try again."
        )

    return max(
        enumerate(candidates),
        key=lambda indexed: (score_model_id(indexed[1]), -indexed[0]),
    )[1]


def select_model(
    validated_config: dict[str, Any],
    *,
    host: str,
    port: int,
    base_path: str,
    timeout: float,
    model_override: str | None = None,
) -> str:
    requested_model = (model_override or "").strip()
    if requested_model:
        return requested_model

    configured_model = str(validated_config.get("model", "")).strip()
    if configured_model and configured_model != "placeholder":
        return configured_model

    models_payload = request_json(
        host,
        port,
        f"{base_path.rstrip('/')}/models",
        method="GET",
        timeout=timeout,
    )
    models = models_payload.get("data")
    if not isinstance(models, list):
        raise LMStudioGenerationError("LM Studio models response has no model list.")

    return select_model_from_list(models)


def extract_chat_content(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise LMStudioGenerationError("LM Studio response has no choices.")

    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        raise LMStudioGenerationError("LM Studio choice is not an object.")

    message = first_choice.get("message")
    if not isinstance(message, dict) or not isinstance(message.get("content"), str):
        raise LMStudioGenerationError("LM Studio response has no message content.")
    return message["content"]


def build_session(
    *,
    description: str,
    output_json: Path,
    validation_status: str,
    validation_message: str,
    model: str | None,
    notes: str,
) -> dict[str, Any]:
    return {
        "user_prompt": description,
        "generator_mode": "lmstudio_local_chat_completion",
        "generated_archseed_json_path": output_json.expanduser()
        .resolve()
        .as_posix(),
        "validation_status": validation_status,
        "validation_message": validation_message,
        "sketchup_import_command": build_import_command(output_json),
        "created_at": utc_now(),
        "notes": notes if model is None else f"{notes} Model: {model}.",
    }


def generate_with_lmstudio(
    description: str,
    *,
    config_path: Path,
    output_json: Path,
    output_session: Path,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    model_override: str | None = None,
) -> dict[str, Any]:
    config = load_json(config_path)
    validated_config = validate_llm_config(config)
    host, port, base_path = parse_local_base_url(validated_config["base_url"])
    prompt = build_prompt(description, validated_config)
    model = select_model(
        validated_config,
        host=host,
        port=port,
        base_path=base_path,
        timeout=timeout,
        model_override=model_override,
    )

    request_payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": prompt,
            }
        ],
        "temperature": validated_config["temperature"],
        "max_tokens": validated_config["max_output_tokens"],
        "stream": False,
    }

    try:
        response_payload = request_json(
            host,
            port,
            f"{base_path.rstrip('/')}/chat/completions",
            method="POST",
            payload=request_payload,
            timeout=timeout,
        )
        content = extract_chat_content(response_payload)
        generated = extract_json_object(content)
    except (LMStudioGenerationError, JSONExtractionError) as exc:
        session = build_session(
            description=description,
            output_json=output_json,
            validation_status="INVALID",
            validation_message=f"INVALID: {exc}",
            model=model,
            notes=(
                "Local LM Studio generation failed before a valid ArchSeed JSON "
                "candidate could be saved. No external cloud API or API key was used."
            ),
        )
        write_json(output_session, session)
        raise

    write_json(output_json, generated)
    try:
        validate_archseed(generated)
    except ValidationError as exc:
        session = build_session(
            description=description,
            output_json=output_json,
            validation_status="INVALID",
            validation_message=f"INVALID: {exc}",
            model=model,
            notes=(
                "Local LM Studio response was saved but failed ArchSeed validation. "
                "Treat it as data only; it is not executable code."
            ),
        )
        write_json(output_session, session)
        raise

    session = build_session(
        description=description,
        output_json=output_json,
        validation_status="VALID",
        validation_message=f"VALID: {output_json}",
        model=model,
        notes=(
            "Generated by LM Studio local server and validated as ArchSeed JSON. "
            "No external cloud API or API key was used."
        ),
    )
    write_json(output_session, session)
    return session


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate and validate ArchSeed JSON with local LM Studio."
    )
    parser.add_argument("description", help="Short building description.")
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help="Local-only LLM config JSON path.",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        required=True,
        help="Generated ArchSeed JSON output path.",
    )
    parser.add_argument(
        "--output-session",
        type=Path,
        required=True,
        help="Draft session JSON output path.",
    )
    parser.add_argument(
        "--model",
        help=(
            "Optional LM Studio model id override. The value must name a local "
            "model exposed by the local server."
        ),
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="Local server timeout in seconds.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not 0 < args.timeout <= 300:
        print("INVALID: --timeout must be greater than 0 and at most 300.", file=sys.stderr)
        return 2

    try:
        session = generate_with_lmstudio(
            args.description,
            config_path=args.config,
            output_json=args.output_json,
            output_session=args.output_session,
            timeout=args.timeout,
            model_override=args.model,
        )
    except (
        OSError,
        json.JSONDecodeError,
        ConfigValidationError,
        ValidationError,
        LMStudioGenerationError,
        JSONExtractionError,
    ) as exc:
        print(f"LM Studio generation failed: {exc}", file=sys.stderr)
        return 1

    print(f"WROTE JSON: {args.output_json}")
    print(f"WROTE SESSION: {args.output_session}")
    print(session["validation_message"])
    print(session["sketchup_import_command"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
