"""Tests pour le module de logging structuré avec sanitisation."""

from io import StringIO

from loguru import logger
import pytest

from src.core.logging import _sanitize_message, setup_logging


@pytest.fixture(autouse=True)
def _clean_loguru():
    """Nettoie les sinks loguru avant et après chaque test."""
    logger.remove()
    yield
    logger.remove()


class TestSanitizeMessage:
    """Tests de la fonction _sanitize_message."""

    def test_sanitize_message_api_key(self):
        msg = "Connexion avec api_key='xK9mP2nQ7wR4tY6u'"
        result = _sanitize_message(msg)
        assert "xK9mP2nQ7wR4tY6u" not in result
        assert "***" in result

    def test_sanitize_message_api_secret(self):
        msg = "Config: api_secret=abc123def456"
        result = _sanitize_message(msg)
        assert "abc123def456" not in result
        assert "***" in result

    def test_sanitize_message_no_sensitive_data(self):
        msg = "Trading BTC/USDT"
        result = _sanitize_message(msg)
        assert result == msg

    def test_sanitize_message_multiple_patterns(self):
        msg = "api_key='key123' et api_secret=secret456"
        result = _sanitize_message(msg)
        assert "key123" not in result
        assert "secret456" not in result
        assert result.count("***") >= 2

    def test_sanitize_message_password(self):
        msg = "Connexion avec password='myP@ssw0rd'"
        result = _sanitize_message(msg)
        assert "myP@ssw0rd" not in result
        assert "***" in result

    def test_sanitize_message_secret(self):
        msg = "Config: secret=sUp3rS3cr3t"
        result = _sanitize_message(msg)
        assert "sUp3rS3cr3t" not in result
        assert "***" in result

    def test_sanitize_message_token(self):
        msg = "Auth: token='tok_abc123xyz'"
        result = _sanitize_message(msg)
        assert "tok_abc123xyz" not in result
        assert "***" in result


class TestSetupLogging:
    """Tests de la fonction setup_logging."""

    def test_setup_logging_creates_directory(self, tmp_path):
        log_dir = tmp_path / "logs"
        setup_logging(log_dir=str(log_dir))
        assert log_dir.exists()

    def test_setup_logging_does_not_crash(self):
        setup_logging()

    def test_setup_logging_debug_mode(self):
        setup_logging(log_level="DEBUG")


class TestApiKeyFiltering:
    """Tests de filtrage des clés API dans les sinks."""

    def test_api_key_filtered_in_sink(self):
        from src.core.logging import _file_format

        output = StringIO()
        logger.add(output, format=_file_format, level="DEBUG")  # type: ignore[arg-type]
        logger.info("Connexion avec api_key='xK9mP2nQ7wR4tY6u'")
        logged = output.getvalue()
        assert "xK9mP2nQ7wR4tY6u" not in logged
        assert "***" in logged
