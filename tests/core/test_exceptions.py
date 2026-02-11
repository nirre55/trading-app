"""Tests pour la hiérarchie d'exceptions de trading-app."""

from src.core.exceptions import (
    ConfigError,
    ExchangeConnectionError,
    ExchangeError,
    InsufficientBalanceError,
    OrderFailedError,
    RateLimitError,
    TradeError,
    TradingAppError,
    DataValidationError,
)


class TestTradingAppError:
    """Tests pour la classe de base TradingAppError."""

    def test_instanciation_avec_message(self):
        err = TradingAppError("erreur de test")
        assert str(err) == "erreur de test"

    def test_instanciation_avec_context(self):
        ctx = {"key": "value", "code": 42}
        err = TradingAppError("erreur", context=ctx)
        assert err.context == {"key": "value", "code": 42}

    def test_context_par_defaut_vide(self):
        err = TradingAppError("erreur")
        assert err.context == {}

    def test_herite_de_exception(self):
        assert issubclass(TradingAppError, Exception)


class TestHierarchieExchangeError:
    """Tests de la branche ExchangeError."""

    def test_exchange_error_herite_trading_app_error(self):
        assert issubclass(ExchangeError, TradingAppError)

    def test_connection_error_herite_exchange_error(self):
        assert issubclass(ExchangeConnectionError, ExchangeError)

    def test_connection_error_herite_trading_app_error(self):
        assert issubclass(ExchangeConnectionError, TradingAppError)

    def test_rate_limit_error_herite_exchange_error(self):
        assert issubclass(RateLimitError, ExchangeError)

    def test_rate_limit_error_herite_trading_app_error(self):
        assert issubclass(RateLimitError, TradingAppError)

    def test_isinstance_connection_error_est_exchange_error(self):
        err = ExchangeConnectionError("connexion perdue")
        assert isinstance(err, ExchangeError)

    def test_isinstance_rate_limit_error_est_exchange_error(self):
        err = RateLimitError("trop de requêtes")
        assert isinstance(err, ExchangeError)


class TestHierarchieTradeError:
    """Tests de la branche TradeError."""

    def test_trade_error_herite_trading_app_error(self):
        assert issubclass(TradeError, TradingAppError)

    def test_order_failed_error_herite_trade_error(self):
        assert issubclass(OrderFailedError, TradeError)

    def test_order_failed_error_herite_trading_app_error(self):
        assert issubclass(OrderFailedError, TradingAppError)

    def test_insufficient_balance_error_herite_trade_error(self):
        assert issubclass(InsufficientBalanceError, TradeError)

    def test_insufficient_balance_error_herite_trading_app_error(self):
        assert issubclass(InsufficientBalanceError, TradingAppError)

    def test_isinstance_order_failed_est_trade_error(self):
        err = OrderFailedError("ordre échoué")
        assert isinstance(err, TradeError)

    def test_isinstance_insufficient_balance_est_trade_error(self):
        err = InsufficientBalanceError("balance insuffisante")
        assert isinstance(err, TradeError)


class TestAutresExceptions:
    """Tests pour ConfigError et DataValidationError."""

    def test_config_error_herite_trading_app_error(self):
        assert issubclass(ConfigError, TradingAppError)

    def test_validation_error_herite_trading_app_error(self):
        assert issubclass(DataValidationError, TradingAppError)

    def test_config_error_message(self):
        err = ConfigError("config invalide")
        assert str(err) == "config invalide"

    def test_validation_error_message(self):
        err = DataValidationError("donnée invalide")
        assert str(err) == "donnée invalide"


class TestContextPropagation:
    """Tests que le context est propagé dans toute la hiérarchie."""

    def test_exchange_error_avec_context(self):
        err = ExchangeError("erreur", context={"exchange": "binance"})
        assert err.context == {"exchange": "binance"}

    def test_connection_error_avec_context(self):
        err = ExchangeConnectionError("déconnecté", context={"retry": 3})
        assert err.context == {"retry": 3}

    def test_trade_error_avec_context(self):
        err = TradeError("erreur trade", context={"pair": "BTC/USDT"})
        assert err.context == {"pair": "BTC/USDT"}

    def test_order_failed_avec_context(self):
        err = OrderFailedError("ordre rejeté", context={"order_id": "123"})
        assert err.context == {"order_id": "123"}
