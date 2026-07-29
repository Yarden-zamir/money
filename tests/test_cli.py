"""CLI generation contract.

The generated module is checked in, so the thing worth testing is that regenerating it from
the live schema produces exactly what is committed — and that the annotations survive the
trip into real Typer commands.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

GENERATED = Path(__file__).resolve().parents[1] / "src" / "money_cli" / "generated.py"


@pytest.fixture(scope="module")
def spec() -> dict:
    import os

    os.environ.setdefault("DEV_MODE", "1")
    from money.api.app import create_app

    return create_app().openapi()


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def test_the_checked_in_module_matches_the_schema(spec: dict) -> None:
    """This is what `money generate-cli --check` runs in CI."""
    from money_cli.generate import generate

    assert GENERATED.read_text(encoding="utf-8") == generate(spec), (
        "generated.py is stale. Run: uv run money generate-cli"
    )


def test_every_annotated_route_becomes_a_command(spec: dict) -> None:
    annotated = {
        operation["x-cli"]["command"]
        for methods in spec["paths"].values()
        for operation in methods.values()
        if isinstance(operation, dict) and "x-cli" in operation
    }
    source = GENERATED.read_text(encoding="utf-8")

    for command in annotated:
        name = command.split()[-1]
        assert f'.command("{name}"' in source, f"{command} did not generate a command"


class TestCommandSurface:
    def test_positional_args_follow_the_annotation_order(self, runner: CliRunner) -> None:
        from money_cli.main import app

        result = runner.invoke(app, ["entry", "add", "--help"])
        assert result.exit_code == 0
        assert "{amount} {payee}" in result.output.replace("\n", " ")

    def test_short_aliases_come_from_the_annotation(self, runner: CliRunner) -> None:
        from money_cli.main import app

        result = runner.invoke(app, ["entry", "add", "--help"])
        for alias in ("-b", "-d", "-n"):
            assert alias in result.output

    def test_transport_headers_never_become_flags(self, runner: CliRunner) -> None:
        """FastAPI exposes the auth dependency's Header/Cookie params in the schema.

        They are transport, not user input, and must not surface as CLI options.
        """
        from money_cli.main import app

        result = runner.invoke(app, ["assign", "--help"])
        assert "--authorization" not in result.output
        assert "--money-session" not in result.output

    def test_hand_written_commands_extend_generated_groups(self, runner: CliRunner) -> None:
        """`auth` and `budget` exist in both halves; neither may shadow the other."""
        from money_cli.main import app

        auth = runner.invoke(app, ["auth", "--help"]).output
        assert "whoami" in auth  # generated
        assert "login" in auth  # hand-written

        budget = runner.invoke(app, ["budget", "--help"]).output
        assert "connect" in budget  # generated
        assert "default" in budget  # hand-written

    def test_unauthenticated_calls_exit_with_code_four(self, runner: CliRunner) -> None:
        from money_cli.main import app

        result = runner.invoke(
            app,
            ["balance", "--budget", "joint"],
            env={"MONEY_HOST": "example.invalid", "MONEY_TOKEN": ""},
        )
        assert result.exit_code == 4


class TestConfig:
    def test_a_saved_token_is_not_world_readable(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        from money_cli import config

        config.save(config.HostConfig(host="money.example.com", token="money_pat_secret"))

        path = config.config_path()
        assert path.stat().st_mode & 0o077 == 0
        assert config.load("money.example.com").token == "money_pat_secret"

    def test_the_environment_overrides_the_file(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        from money_cli import config

        config.save(config.HostConfig(host="money.example.com", token="from-file"))
        monkeypatch.setenv("MONEY_TOKEN", "from-env")

        assert config.load("money.example.com").token == "from-env"

    def test_a_bare_hostname_is_https(self) -> None:
        from money_cli.config import HostConfig

        assert (
            HostConfig(host="money.yarden-zamir.com").base_url == "https://money.yarden-zamir.com"
        )
        assert HostConfig(host="http://localhost:8000").base_url == "http://localhost:8000"
