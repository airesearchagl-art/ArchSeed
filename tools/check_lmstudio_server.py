from __future__ import annotations

import argparse
import json
import sys
from http.client import HTTPConnection, HTTPException
from pathlib import Path
from typing import Any

try:
    from tools.validate_llm_config import (
        ConfigValidationError,
        load_json,
        parse_local_base_url,
        validate_llm_config,
    )
except ModuleNotFoundError:
    from validate_llm_config import (
        ConfigValidationError,
        load_json,
        parse_local_base_url,
        validate_llm_config,
    )


MAX_RESPONSE_BYTES = 1_000_000


class ServerCheckError(RuntimeError):
    pass


def check_lmstudio_server(
    config: dict[str, Any],
    timeout: float = 3.0,
) -> list[str]:
    validated = validate_llm_config(config)
    host, port, base_path = parse_local_base_url(validated["base_url"])
    models_path = f"{base_path.rstrip('/')}/models"
    connection = HTTPConnection(host, port, timeout=timeout)

    try:
        connection.request("GET", models_path, headers={"Accept": "application/json"})
        response = connection.getresponse()
        payload_bytes = response.read(MAX_RESPONSE_BYTES + 1)
    except (OSError, HTTPException) as exc:
        raise ServerCheckError(
            "LM Studio local server is unavailable. Start Local Server in "
            "LM Studio and try again."
        ) from exc
    finally:
        connection.close()

    if response.status != 200:
        raise ServerCheckError(
            f"LM Studio models endpoint returned HTTP {response.status}."
        )
    if len(payload_bytes) > MAX_RESPONSE_BYTES:
        raise ServerCheckError("LM Studio response exceeded the safety limit.")

    try:
        payload = json.loads(payload_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ServerCheckError(
            "LM Studio models endpoint did not return valid JSON."
        ) from exc

    models = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(models, list):
        raise ServerCheckError(
            "LM Studio models endpoint response has no model list."
        )

    return [
        model["id"]
        for model in models
        if isinstance(model, dict)
        and isinstance(model.get("id"), str)
        and model["id"].strip()
    ]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check the local LM Studio models endpoint."
    )
    parser.add_argument(
        "--config",
        type=Path,
        required=True,
        help="Path to the local-only LLM config JSON.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=3.0,
        help="Local server timeout in seconds.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not 0 < args.timeout <= 30:
        print(
            "INVALID: --timeout must be greater than 0 and at most 30.",
            file=sys.stderr,
        )
        return 2

    try:
        models = check_lmstudio_server(load_json(args.config), args.timeout)
    except (
        OSError,
        json.JSONDecodeError,
        ConfigValidationError,
        ServerCheckError,
    ) as exc:
        print(f"LM Studio check failed: {exc}", file=sys.stderr)
        return 1

    print("LM Studio local server is reachable.")
    if models:
        print(f"Models ({len(models)}):")
        for model_id in models:
            print(f"- {model_id}")
    else:
        print("Models endpoint is valid, but no loaded models were reported.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
