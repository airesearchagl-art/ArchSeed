from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any


MAX_OUTPUT_TOKENS = 4096
ALLOWED_ROOT_KEYS = {
    "config_version",
    "provider",
    "model",
    "allow_external_api",
    "max_output_tokens",
    "temperature",
    "output_contract",
}
ALLOWED_CONTRACT_KEYS = {
    "format",
    "content",
    "allow_markdown",
    "allow_executable_code",
}
SENSITIVE_FIELD_NAMES = {
    "api_key",
    "apikey",
    "access_token",
    "auth_token",
    "authorization",
    "credential",
    "credentials",
    "password",
    "secret",
    "token",
}
SENSITIVE_FIELD_SUFFIXES = (
    "_api_key",
    "_access_token",
    "_auth_token",
    "_password",
    "_secret",
)
SENSITIVE_VALUE_PATTERNS = (
    re.compile(r"\b(?:sk|rk|pk)-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bBearer\s+\S+", re.IGNORECASE),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)


class ConfigValidationError(ValueError):
    pass


def _require_object(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigValidationError(f"{path} must be an object")
    return value


def _reject_unknown_keys(
    value: dict[str, Any],
    path: str,
    allowed: set[str],
) -> None:
    unknown = set(value) - allowed
    if unknown:
        joined = ", ".join(sorted(unknown))
        raise ConfigValidationError(f"{path} has unknown key(s): {joined}")


def _check_for_credentials(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized_key = re.sub(
                r"[^a-z0-9]+",
                "_",
                key.strip().lower(),
            ).strip("_")
            if (
                normalized_key in SENSITIVE_FIELD_NAMES
                or normalized_key.endswith(SENSITIVE_FIELD_SUFFIXES)
            ):
                raise ConfigValidationError(
                    f"{path}.{key} is a credential field and is not allowed"
                )
            _check_for_credentials(child, f"{path}.{key}")
        return

    if isinstance(value, list):
        for index, child in enumerate(value):
            _check_for_credentials(child, f"{path}[{index}]")
        return

    if isinstance(value, str):
        for pattern in SENSITIVE_VALUE_PATTERNS:
            if pattern.search(value):
                raise ConfigValidationError(
                    f"{path} contains a credential-like value"
                )


def validate_llm_config(data: Any) -> dict[str, Any]:
    root = _require_object(data, "$")
    _check_for_credentials(root)
    _reject_unknown_keys(root, "$", ALLOWED_ROOT_KEYS)

    if root.get("config_version") != "archseed.llm_config.v0.1":
        raise ConfigValidationError(
            "$.config_version must be 'archseed.llm_config.v0.1'"
        )
    if root.get("provider") != "none":
        raise ConfigValidationError(
            "$.provider must be 'none'; LLM providers are not supported yet"
        )
    if root.get("model") not in {"", "disabled"}:
        raise ConfigValidationError("$.model must be empty or 'disabled'")
    if root.get("allow_external_api") is not False:
        raise ConfigValidationError(
            "$.allow_external_api must be false; external APIs are not supported"
        )

    max_output_tokens = root.get("max_output_tokens")
    if (
        not isinstance(max_output_tokens, int)
        or isinstance(max_output_tokens, bool)
        or not 1 <= max_output_tokens <= MAX_OUTPUT_TOKENS
    ):
        raise ConfigValidationError(
            f"$.max_output_tokens must be an integer from 1 to {MAX_OUTPUT_TOKENS}"
        )

    temperature = root.get("temperature")
    if (
        not isinstance(temperature, (int, float))
        or isinstance(temperature, bool)
        or not 0 <= float(temperature) <= 1
    ):
        raise ConfigValidationError("$.temperature must be from 0 to 1")

    contract = _require_object(root.get("output_contract"), "$.output_contract")
    _reject_unknown_keys(
        contract,
        "$.output_contract",
        ALLOWED_CONTRACT_KEYS,
    )
    if contract.get("format") != "archseed.v0.1":
        raise ConfigValidationError(
            "$.output_contract.format must be 'archseed.v0.1'"
        )
    if contract.get("content") != "ArchSeed JSON only":
        raise ConfigValidationError(
            "$.output_contract.content must be 'ArchSeed JSON only'"
        )
    if contract.get("allow_markdown") is not False:
        raise ConfigValidationError(
            "$.output_contract.allow_markdown must be false"
        )
    if contract.get("allow_executable_code") is not False:
        raise ConfigValidationError(
            "$.output_contract.allow_executable_code must be false"
        )

    return root


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(
            "Usage: python tools/validate_llm_config.py <path-to-config-json>",
            file=sys.stderr,
        )
        return 2

    path = Path(argv[1])
    try:
        validate_llm_config(load_json(path))
    except (OSError, json.JSONDecodeError, ConfigValidationError) as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 1

    print(f"VALID: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
