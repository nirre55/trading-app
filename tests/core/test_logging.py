"""Tests pour le module de logging structuré avec sanitisation."""

from io import StringIO

from loguru import logger
import pytest

from src.core.logging import _sanitize_message, register_sensitive_values, setup_logging


@pytest.fixture(autouse=True)
def _clean_loguru():
    """Nettoie les sinks loguru avant et après chaque test."""
    logger.remove()
    register_sensitive_values()  # Réinitialise les valeurs enregistrées
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

    def test_setup_logging_does_not_crash(self, tmp_path):
        setup_logging(log_dir=str(tmp_path))

    def test_setup_logging_debug_mode(self):
        setup_logging(log_level="DEBUG")


class TestSetupLoggingLevels:
    """Tests du filtrage par niveau de log."""

    def test_info_level_hides_debug_messages(self, tmp_path):
        """Au niveau INFO, les messages DEBUG ne sont pas capturés dans le sink fichier."""
        from src.core.logging import _file_format

        output = StringIO()
        setup_logging(log_level="INFO", log_dir=str(tmp_path))
        logger.add(output, format=_file_format, level="INFO")  # type: ignore[arg-type]
        logger.debug("Ce message DEBUG ne devrait pas apparaître")
        logged = output.getvalue()
        assert "Ce message DEBUG ne devrait pas apparaître" not in logged

    def test_debug_level_shows_debug_messages(self, tmp_path):
        """Au niveau DEBUG, les messages DEBUG sont bien capturés."""
        from src.core.logging import _file_format

        output = StringIO()
        setup_logging(log_level="DEBUG", log_dir=str(tmp_path))
        logger.add(output, format=_file_format, level="DEBUG")  # type: ignore[arg-type]
        logger.debug("Ce message DEBUG doit apparaître")
        logged = output.getvalue()
        assert "Ce message DEBUG doit apparaître" in logged


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

    def test_url_api_key_masked_preserves_other_params(self, tmp_path):
        """URL avec api_key= : la clé est masquée et les autres paramètres sont conservés (AC3)."""
        from src.core.logging import _file_format

        output = StringIO()
        setup_logging(log_level="DEBUG", log_dir=str(tmp_path))
        logger.add(output, format=_file_format, level="DEBUG")  # type: ignore[arg-type]
        url = "https://api.exchange.com/v3?api_key=TESTURLSECRET99&symbol=BTCUSDT&interval=1h"
        logger.info("URL appelée : {}", url)
        logged = output.getvalue()
        assert "TESTURLSECRET99" not in logged
        assert "***" in logged
        assert "symbol=BTCUSDT" in logged
        assert "interval=1h" in logged


class TestRegisterSensitiveValues:
    """Tests de register_sensitive_values() pour filtrage dynamique des clés API."""

    def test_raw_api_key_masked_in_file_sink(self, tmp_path):
        """Une valeur brute enregistrée est masquée même sans format key=value."""
        from src.core.logging import _file_format

        output = StringIO()
        setup_logging(log_level="DEBUG", log_dir=str(tmp_path))
        register_sensitive_values("MY_SECRET_API_KEY_XYZ123")
        logger.add(output, format=_file_format, level="DEBUG")  # type: ignore[arg-type]
        logger.info("Connexion avec clé MY_SECRET_API_KEY_XYZ123 établie")
        logged = output.getvalue()
        assert "MY_SECRET_API_KEY_XYZ123" not in logged
        assert "***" in logged

    def test_raw_api_key_masked_in_console_sink(self, tmp_path):
        """Une valeur brute enregistrée est masquée dans le sink console."""
        from src.core.logging import _console_format

        output = StringIO()
        setup_logging(log_level="DEBUG", log_dir=str(tmp_path))
        register_sensitive_values("CONSOLE_SECRET_KEY_ABC456")
        logger.add(output, format=_console_format, level="DEBUG",  # type: ignore[arg-type]
                   colorize=False)
        logger.info("Test CONSOLE_SECRET_KEY_ABC456")
        logged = output.getvalue()
        assert "CONSOLE_SECRET_KEY_ABC456" not in logged
        assert "***" in logged

    def test_multiple_sensitive_values_all_masked(self, tmp_path):
        """Plusieurs valeurs brutes enregistrées sont toutes masquées (sans pattern key=value)."""
        from src.core.logging import _file_format

        output = StringIO()
        setup_logging(log_level="DEBUG", log_dir=str(tmp_path))
        register_sensitive_values("KEY_VALUE_111", "SECRET_VALUE_222")
        logger.add(output, format=_file_format, level="DEBUG")  # type: ignore[arg-type]
        logger.info("Clés brutes détectées : KEY_VALUE_111 et SECRET_VALUE_222")
        logged = output.getvalue()
        assert "KEY_VALUE_111" not in logged
        assert "SECRET_VALUE_222" not in logged

    def test_empty_values_ignored(self):
        """Les valeurs vides ne plantent pas register_sensitive_values."""
        register_sensitive_values("", "valid_value", "")
        msg = _sanitize_message("test valid_value fin")
        assert "valid_value" not in msg

    def test_register_sensitive_values_resets_on_setup_logging(self, tmp_path):
        """setup_logging() réinitialise les valeurs enregistrées (évite fuites entre tests)."""
        register_sensitive_values("OLD_KEY_THAT_SHOULD_BE_CLEARED")
        setup_logging(log_dir=str(tmp_path))
        # Après setup_logging, les anciennes valeurs sont effacées
        msg = _sanitize_message("OLD_KEY_THAT_SHOULD_BE_CLEARED")
        assert "OLD_KEY_THAT_SHOULD_BE_CLEARED" in msg  # plus de masquage

    def test_short_values_not_registered(self):
        """Les valeurs de moins de 4 caractères sont ignorées à l'enregistrement (M2)."""
        register_sensitive_values("abc", "valid_longkey_123")
        msg = _sanitize_message("test abc valid_longkey_123 end")
        assert "abc" in msg  # trop court (3 chars) : non masqué
        assert "valid_longkey_123" not in msg  # longueur >= 4 : masqué

    def test_exception_message_sanitized_in_sink(self, tmp_path):
        """Exception contenant une valeur sensible est sanitisée dans le sink fichier (H1)."""
        from src.core.logging import _file_format

        output = StringIO()
        setup_logging(log_level="DEBUG", log_dir=str(tmp_path))
        register_sensitive_values("EXCEPTION_SECRET_KEY_789")
        logger.add(output, format=_file_format, level="DEBUG")  # type: ignore[arg-type]
        try:
            raise ValueError("Erreur avec EXCEPTION_SECRET_KEY_789 dans le message")
        except ValueError:
            logger.exception("Erreur détectée")
        logged = output.getvalue()
        assert "EXCEPTION_SECRET_KEY_789" not in logged
        assert "***" in logged
