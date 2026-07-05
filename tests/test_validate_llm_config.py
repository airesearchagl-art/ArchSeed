from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from tools.validate_llm_config import (
    ConfigValidationError,
    validate_llm_config,
)


ROOT = Path(__file__).resolve().parents[1]
CONFIG_KEEP_PATH = ROOT / "config" / ".gitkeep"
EXAMPLE_CONFIG_PATH = ROOT / "config" / "llm_config.example.json"
CONFIG_VALIDATOR_PATH = ROOT / "tools" / "validate_llm_config.py"


def load_example_config() -> dict:
    return json.loads(EXAMPLE_CONFIG_PATH.read_text(encoding="utf-8"))


def test_llm_config_workspace_and_example_exist() -> None:
    assert CONFIG_KEEP_PATH.is_file()
    assert EXAMPLE_CONFIG_PATH.is_file()
    assert CONFIG_VALIDATOR_PATH.is_file()


def test_example_llm_config_is_valid_and_disabled() -> None:
    config = load_example_config()
    assert validate_llm_config(config) == config
    assert config["provider"] == "none"
    assert config["model"] in {"", "disabled"}
    assert config["allow_external_api"] is False
    assert config["output_contract"]["content"] == "ArchSeed JSON only"


def test_external_api_enablement_is_rejected() -> None:
    config = load_example_config()
    config["allow_external_api"] = True

    with pytest.raises(ConfigValidationError, match="must be false"):
        validate_llm_config(config)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("api_key", "placeholder"),
        ("api-key", "placeholder"),
        ("provider_secret", "placeholder"),
        ("token", "placeholder"),
        ("secret", "placeholder"),
        ("password", "placeholder"),
    ],
)
def test_credential_fields_are_rejected(field: str, value: str) -> None:
    config = load_example_config()
    config[field] = value

    with pytest.raises(ConfigValidationError, match="credential field"):
        validate_llm_config(config)


def test_credential_like_values_are_rejected() -> None:
    config = load_example_config()
    config["model"] = "sk-examplecredentialvalue123456"

    with pytest.raises(ConfigValidationError, match="credential-like value"):
        validate_llm_config(config)


def test_example_llm_config_contains_no_credentials() -> None:
    source = EXAMPLE_CONFIG_PATH.read_text(encoding="utf-8").lower()
    forbidden_fragments = [
        '"api_key"',
        '"apikey"',
        '"access_token"',
        '"auth_token"',
        '"authorization"',
        '"credential"',
        '"password"',
        '"secret"',
        "bearer ",
        "-----begin",
    ]
    for fragment in forbidden_fragments:
        assert fragment not in source


def test_llm_config_validation_does_not_mutate_input() -> None:
    config = load_example_config()
    before = copy.deepcopy(config)
    validate_llm_config(config)
    assert config == before


def test_llm_config_validator_has_no_external_or_dangerous_api() -> None:
    source = CONFIG_VALIDATOR_PATH.read_text(encoding="utf-8").lower()
    forbidden_tokens = [
        "openai",
        "anthropic",
        "requests",
        "urllib",
        "httpx",
        "socket",
        "subprocess",
        "eval(",
        "exec(",
        "system(",
        "spawn(",
        ".env",
        "`",
    ]
    for token in forbidden_tokens:
        assert token not in source
