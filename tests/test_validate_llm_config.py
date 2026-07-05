from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

import tools.check_lmstudio_server as lmstudio_check
from tools.validate_llm_config import (
    ConfigValidationError,
    parse_local_base_url,
    validate_llm_config,
)


ROOT = Path(__file__).resolve().parents[1]
CONFIG_KEEP_PATH = ROOT / "config" / ".gitkeep"
EXAMPLE_CONFIG_PATH = ROOT / "config" / "llm_config.example.json"
CONFIG_VALIDATOR_PATH = ROOT / "tools" / "validate_llm_config.py"
SERVER_CHECK_PATH = ROOT / "tools" / "check_lmstudio_server.py"


def load_example_config() -> dict:
    return json.loads(EXAMPLE_CONFIG_PATH.read_text(encoding="utf-8"))


def test_llm_config_workspace_and_example_exist() -> None:
    assert CONFIG_KEEP_PATH.is_file()
    assert EXAMPLE_CONFIG_PATH.is_file()
    assert CONFIG_VALIDATOR_PATH.is_file()
    assert SERVER_CHECK_PATH.is_file()


def test_example_llm_config_is_valid_and_local_only() -> None:
    config = load_example_config()
    assert validate_llm_config(config) == config
    assert config["provider"] == "lmstudio"
    assert config["mode"] == "local"
    assert config["base_url"] == "http://localhost:1234/v1"
    assert config["model"] in {"", "placeholder"}
    assert config["allow_external_api"] is False
    assert config["require_api_key"] is False
    assert config["output_contract"]["content"] == "ArchSeed JSON only"


def test_external_api_enablement_is_rejected() -> None:
    config = load_example_config()
    config["allow_external_api"] = True

    with pytest.raises(ConfigValidationError, match="must be false"):
        validate_llm_config(config)


def test_api_key_requirement_is_rejected() -> None:
    config = load_example_config()
    config["require_api_key"] = True

    with pytest.raises(ConfigValidationError, match="must be false"):
        validate_llm_config(config)


@pytest.mark.parametrize(
    "base_url",
    [
        "https://example.com/v1",
        "http://localhost.example.com:1234/v1",
        "http://192.168.1.20:1234/v1",
        "http://127.0.0.1:1234/other",
        "https://localhost:1234/v1",
    ],
)
def test_non_local_or_unsupported_base_url_is_rejected(base_url: str) -> None:
    config = load_example_config()
    config["base_url"] = base_url

    with pytest.raises(ConfigValidationError, match="localhost or 127.0.0.1"):
        validate_llm_config(config)


def test_loopback_base_urls_are_parsed() -> None:
    assert parse_local_base_url("http://localhost:1234/v1") == (
        "localhost",
        1234,
        "/v1",
    )
    assert parse_local_base_url("http://127.0.0.1:1234/v1") == (
        "127.0.0.1",
        1234,
        "/v1",
    )


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


def test_lmstudio_check_uses_only_models_get_endpoint() -> None:
    source = SERVER_CHECK_PATH.read_text(encoding="utf-8").lower()
    forbidden_tokens = [
        "/chat/completions",
        "/completions",
        "/responses",
        '"post"',
        "requests",
        "openai",
        "anthropic",
        "eval(",
        "exec(",
        "system(",
        "spawn(",
        ".env",
        "`",
    ]
    for token in forbidden_tokens:
        assert token not in source

    assert 'connection.request("get", models_path' in source
    assert 'models_path = f"{base_path.rstrip(\'/\')}/models"' in source


def test_lmstudio_check_reports_local_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[tuple[str, int, float, str]] = []

    class FakeResponse:
        status = 200

        def read(self, _limit: int) -> bytes:
            return b'{"data":[{"id":"local-model"}]}'

    class FakeConnection:
        def __init__(self, host: str, port: int, timeout: float) -> None:
            requests.append((host, port, timeout, ""))

        def request(
            self,
            method: str,
            path: str,
            headers: dict[str, str],
        ) -> None:
            assert headers == {"Accept": "application/json"}
            host, port, timeout, _ = requests[-1]
            requests[-1] = (host, port, timeout, f"{method} {path}")

        def getresponse(self) -> FakeResponse:
            return FakeResponse()

        def close(self) -> None:
            pass

    monkeypatch.setattr(lmstudio_check, "HTTPConnection", FakeConnection)
    assert lmstudio_check.check_lmstudio_server(load_example_config()) == [
        "local-model"
    ]
    assert requests == [("localhost", 1234, 3.0, "GET /v1/models")]
