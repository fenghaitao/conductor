"""Unit tests for Claude credential discovery."""

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from conductor.exceptions import ProviderError
from conductor.providers.claude_credentials import resolve_auth_token


# Canonical credentials file shape written by the claude CLI.
def _creds(access_token: str) -> str:
    return json.dumps({"claudeAiOauth": {"accessToken": access_token}})


class TestResolveAuthToken:
    def test_explicit_kwarg_takes_priority(self) -> None:
        result = resolve_auth_token(auth_token="explicit-token")
        assert result == "explicit-token"

    def test_env_var_when_file_absent(self, tmp_path: Path) -> None:
        with patch.dict(
            os.environ, {"ANTHROPIC_AUTH_TOKEN": "env-token"}, clear=True
        ), patch(
            "conductor.providers.claude_credentials.CREDENTIALS_PATH",
            tmp_path / "nonexistent.json",
        ):
            result = resolve_auth_token()
            assert result == "env-token"

    def test_env_var_takes_priority_over_file(self, tmp_path: Path) -> None:
        creds_file = tmp_path / ".credentials.json"
        creds_file.write_text(_creds("file-token"))

        with patch.dict(
            os.environ, {"ANTHROPIC_AUTH_TOKEN": "env-token"}, clear=True
        ), patch(
            "conductor.providers.claude_credentials.CREDENTIALS_PATH",
            creds_file,
        ):
            result = resolve_auth_token()
            assert result == "env-token"

    def test_file_missing_and_env_unset_raises(self, tmp_path: Path) -> None:
        with patch.dict(os.environ, {}, clear=True), patch(
            "conductor.providers.claude_credentials.CREDENTIALS_PATH",
            tmp_path / "nonexistent.json",
        ):
            with pytest.raises(ProviderError) as exc_info:
                resolve_auth_token()
            assert "claude login" in str(exc_info.value)
            assert "ANTHROPIC_AUTH_TOKEN" in str(exc_info.value)

    def test_malformed_json_raises(self, tmp_path: Path) -> None:
        creds_file = tmp_path / ".credentials.json"
        creds_file.write_text("not valid json {{{")

        with patch.dict(os.environ, {}, clear=True), patch(
            "conductor.providers.claude_credentials.CREDENTIALS_PATH",
            creds_file,
        ):
            with pytest.raises(ProviderError) as exc_info:
                resolve_auth_token()
            assert str(creds_file) in str(exc_info.value)

    def test_explicit_kwarg_overrides_env_and_file(self, tmp_path: Path) -> None:
        creds_file = tmp_path / ".credentials.json"
        creds_file.write_text(_creds("file-token"))

        with patch.dict(
            os.environ, {"ANTHROPIC_AUTH_TOKEN": "env-token"}, clear=True
        ), patch(
            "conductor.providers.claude_credentials.CREDENTIALS_PATH",
            creds_file,
        ):
            result = resolve_auth_token(auth_token="explicit")
            assert result == "explicit"

    def test_file_token_returned_when_no_env(self, tmp_path: Path) -> None:
        """Token from credentials file is returned when env var is unset."""
        creds_file = tmp_path / ".credentials.json"
        creds_file.write_text(_creds("file-token"))

        with patch.dict(os.environ, {}, clear=True), patch(
            "conductor.providers.claude_credentials.CREDENTIALS_PATH",
            creds_file,
        ):
            result = resolve_auth_token()
            assert result == "file-token"

    def test_file_valid_json_missing_claudeAiOauth_raises(self, tmp_path: Path) -> None:
        """Valid JSON without 'claudeAiOauth' key should raise ProviderError."""
        creds_file = tmp_path / ".credentials.json"
        creds_file.write_text(json.dumps({"other_key": "not_oauth"}))

        with patch.dict(os.environ, {}, clear=True), patch(
            "conductor.providers.claude_credentials.CREDENTIALS_PATH",
            creds_file,
        ):
            with pytest.raises(ProviderError) as exc_info:
                resolve_auth_token()
            assert "No subscription credentials found" in str(exc_info.value)

    def test_empty_string_auth_token_falls_through(self, tmp_path: Path) -> None:
        """Empty string auth_token should be treated as unset, falling through to env/file."""
        with patch.dict(
            os.environ, {"ANTHROPIC_AUTH_TOKEN": "env-token"}, clear=True
        ), patch(
            "conductor.providers.claude_credentials.CREDENTIALS_PATH",
            tmp_path / "nonexistent.json",
        ):
            result = resolve_auth_token(auth_token="")
            assert result == "env-token"

    def test_empty_access_token_in_file_raises_specific_error(self, tmp_path: Path) -> None:
        """A credentials file with accessToken: '' raises a specific ProviderError."""
        creds_file = tmp_path / ".credentials.json"
        creds_file.write_text(json.dumps({"claudeAiOauth": {"accessToken": ""}}))

        with patch.dict(os.environ, {}, clear=True), patch(
            "conductor.providers.claude_credentials.CREDENTIALS_PATH",
            creds_file,
        ):
            with pytest.raises(ProviderError) as exc_info:
                resolve_auth_token()
            assert "empty accessToken" in str(exc_info.value)
            assert str(creds_file) in str(exc_info.value)

    def test_never_reads_api_key_env(self, tmp_path: Path) -> None:
        creds_file = tmp_path / ".credentials.json"
        creds_file.write_text(_creds("file-token"))

        with patch.dict(
            os.environ,
            {"ANTHROPIC_API_KEY": "should-be-ignored"},
            clear=True,
        ), patch(
            "conductor.providers.claude_credentials.CREDENTIALS_PATH",
            creds_file,
        ):
            result = resolve_auth_token()
            assert result == "file-token"
