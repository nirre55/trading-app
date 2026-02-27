"""Tests unitaires pour MartingaleCapitalManager (story 7.2).

Couvre AC #1–#6 : martingale, martingale_inverse, plafonnement max_steps,
réinitialisation et log d'avertissement.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

import pytest

from src.capital.martingale import MartingaleCapitalManager
from src.models.config import CapitalConfig
from src.models.exchange import MarketRules


# ── Helpers ───────────────────────────────────────────────────────────────────


def make_config(
    mode: str = "martingale",
    risk_percent: float = 1.0,
    factor: float = 2.0,
    max_steps: int | None = 3,
) -> CapitalConfig:
    return CapitalConfig(
        mode=mode,
        risk_percent=risk_percent,
        risk_reward_ratio=2.0,
        factor=factor,
        max_steps=max_steps,
    )


def make_market_rules(
    step_size: str = "0.001",
    tick_size: str = "0.1",
    min_notional: str = "10",
    max_leverage: int = 10,
) -> MarketRules:
    return MarketRules(
        step_size=Decimal(step_size),
        tick_size=Decimal(tick_size),
        min_notional=Decimal(min_notional),
        max_leverage=max_leverage,
    )


def make_manager(
    mode: str = "martingale",
    risk_percent: float = 1.0,
    factor: float = 2.0,
    max_steps: int | None = 3,
    step_size: str = "0.001",
):
    config = make_config(mode=mode, risk_percent=risk_percent, factor=factor, max_steps=max_steps)
    rules = make_market_rules(step_size=step_size)
    return MartingaleCapitalManager(config=config, market_rules=rules)


# ── Test AC8 : état initial sans trade précédent ──────────────────────────────


def test_initial_state_uses_base_risk() -> None:
    """État initial : aucun trade enregistré → risk_percent de base utilisé."""
    # balance=10000, risk=1%, entry=50000, sl=49000 → dist=1000 → qty=0.1
    manager = make_manager(risk_percent=1.0, factor=2.0)
    qty = manager.calculate_position_size(
        balance=Decimal("10000"),
        entry_price=Decimal("50000"),
        stop_loss=Decimal("49000"),
    )
    assert qty == Decimal("0.100")


# ── Tests AC 1 : Martingale — multiplication après perte ─────────────────────


def test_ac1_martingale_one_loss_doubles_risk() -> None:
    """AC1 : martingale, 1 perte → risk_percent effectif × factor (1% → 2%)."""
    # Sans perte : qty = 0.1 (risk=1%)
    # Après 1 perte : risk=2% → qty = 0.2
    manager = make_manager(mode="martingale", risk_percent=1.0, factor=2.0)

    manager.record_trade_result(won=False)  # 1 perte

    qty = manager.calculate_position_size(
        balance=Decimal("10000"),
        entry_price=Decimal("50000"),
        stop_loss=Decimal("49000"),  # dist=1000
    )
    # risk=2% → risk_amount=200 → raw=200/1000=0.2
    assert qty == Decimal("0.200")


def test_ac1_martingale_two_losses_quadruples_risk() -> None:
    """AC1 (extension) : martingale, 2 pertes → risk × factor^2 (1% → 4%)."""
    manager = make_manager(mode="martingale", risk_percent=1.0, factor=2.0, max_steps=5)

    manager.record_trade_result(won=False)
    manager.record_trade_result(won=False)

    qty = manager.calculate_position_size(
        balance=Decimal("10000"),
        entry_price=Decimal("50000"),
        stop_loss=Decimal("49000"),
    )
    # risk=4% → risk_amount=400 → raw=400/1000=0.4
    assert qty == Decimal("0.400")


# ── Tests AC 2 : Martingale — plafonnement à max_steps ───────────────────────


def test_ac2_martingale_capped_at_max_steps() -> None:
    """AC2 : martingale, 3 pertes (max_steps=3) → plafonné à base × factor^3."""
    manager = make_manager(mode="martingale", risk_percent=1.0, factor=2.0, max_steps=3)

    # 3 pertes consécutives
    manager.record_trade_result(won=False)
    manager.record_trade_result(won=False)
    manager.record_trade_result(won=False)

    qty_at_cap = manager.calculate_position_size(
        balance=Decimal("10000"),
        entry_price=Decimal("50000"),
        stop_loss=Decimal("49000"),
    )
    # risk = 1% × 2^3 = 8% → risk_amount=800 → raw=800/1000=0.8
    assert qty_at_cap == Decimal("0.800")


def test_ac2_martingale_fourth_loss_stays_capped() -> None:
    """AC2 : 4ème perte après max_steps=3 → la quantité ne change pas (plafond)."""
    manager = make_manager(mode="martingale", risk_percent=1.0, factor=2.0, max_steps=3)

    for _ in range(3):
        manager.record_trade_result(won=False)

    qty_at_cap = manager.calculate_position_size(
        balance=Decimal("10000"),
        entry_price=Decimal("50000"),
        stop_loss=Decimal("49000"),
    )

    # 4ème perte — ne doit pas augmenter
    manager.record_trade_result(won=False)
    qty_after_extra_loss = manager.calculate_position_size(
        balance=Decimal("10000"),
        entry_price=Decimal("50000"),
        stop_loss=Decimal("49000"),
    )

    assert qty_at_cap == qty_after_extra_loss


# ── Tests AC 3 : Martingale — réinitialisation après gain ────────────────────


def test_ac3_martingale_win_resets_to_base() -> None:
    """AC3 : martingale, gain après pertes → risk_percent revient à la base."""
    manager = make_manager(mode="martingale", risk_percent=1.0, factor=2.0)

    # 2 pertes
    manager.record_trade_result(won=False)
    manager.record_trade_result(won=False)

    # Gain → reset
    manager.record_trade_result(won=True)

    qty = manager.calculate_position_size(
        balance=Decimal("10000"),
        entry_price=Decimal("50000"),
        stop_loss=Decimal("49000"),
    )
    # risk revenu à 1% → qty = 0.1
    assert qty == Decimal("0.100")


def test_ac3_martingale_win_without_prior_losses_stays_base() -> None:
    """AC3 (extension) : gain sans pertes préalables → base inchangée."""
    manager = make_manager(mode="martingale", risk_percent=1.0, factor=2.0)

    manager.record_trade_result(won=True)

    qty = manager.calculate_position_size(
        balance=Decimal("10000"),
        entry_price=Decimal("50000"),
        stop_loss=Decimal("49000"),
    )
    assert qty == Decimal("0.100")


# ── Tests AC 4 : Martingale inversée — multiplication après gain ──────────────


def test_ac4_martingale_inverse_one_win_multiplies_risk() -> None:
    """AC4 : martingale_inverse, 1 gain → risk × factor (1% → 1.5%)."""
    manager = make_manager(mode="martingale_inverse", risk_percent=1.0, factor=1.5, max_steps=2)

    manager.record_trade_result(won=True)  # 1 gain

    qty = manager.calculate_position_size(
        balance=Decimal("10000"),
        entry_price=Decimal("50000"),
        stop_loss=Decimal("49000"),
    )
    # risk=1.5% → risk_amount=150 → raw=150/1000=0.15
    assert qty == Decimal("0.150")


def test_ac4_martingale_inverse_capped_at_max_steps() -> None:
    """AC4 (plafonnement) : martingale_inverse, max_steps=2 gains → plafonné à base × factor^2."""
    manager = make_manager(mode="martingale_inverse", risk_percent=1.0, factor=1.5, max_steps=2)

    manager.record_trade_result(won=True)
    manager.record_trade_result(won=True)
    manager.record_trade_result(won=True)  # 3ème gain → toujours plafonné à max_steps=2

    qty = manager.calculate_position_size(
        balance=Decimal("10000"),
        entry_price=Decimal("50000"),
        stop_loss=Decimal("49000"),
    )
    # risk = 1% × 1.5^2 = 2.25% → risk_amount=225 → raw=225/1000=0.225
    assert qty == Decimal("0.225")


# ── Tests AC 5 : Martingale inversée — réinitialisation après perte ───────────


def test_ac5_martingale_inverse_loss_resets_to_base() -> None:
    """AC5 : martingale_inverse, perte après gains → risk_percent revient à la base."""
    manager = make_manager(mode="martingale_inverse", risk_percent=1.0, factor=1.5, max_steps=2)

    # 2 gains
    manager.record_trade_result(won=True)
    manager.record_trade_result(won=True)

    # Perte → reset
    manager.record_trade_result(won=False)

    qty = manager.calculate_position_size(
        balance=Decimal("10000"),
        entry_price=Decimal("50000"),
        stop_loss=Decimal("49000"),
    )
    # risk revenu à 1% → qty = 0.1
    assert qty == Decimal("0.100")


# ── Tests AC 6 : Log avertissement à max_steps ───────────────────────────────


def test_ac6_warning_logged_at_max_steps_martingale() -> None:
    """AC6 : martingale, atteinte de max_steps → warning loggé exactement une fois."""
    manager = make_manager(mode="martingale", risk_percent=1.0, factor=2.0, max_steps=3)

    with patch("src.capital.martingale.logger") as mock_logger:
        manager.record_trade_result(won=False)
        manager.record_trade_result(won=False)
        manager.record_trade_result(won=False)  # max_steps atteint ici — warning loggé

        assert mock_logger.warning.call_count == 1
        warning_args = mock_logger.warning.call_args[0]
        assert "max_steps atteint" in warning_args[0]
        assert "risk_percent plafonné" in warning_args[0]

        # 4ème perte → pas de warning supplémentaire
        manager.record_trade_result(won=False)
        assert mock_logger.warning.call_count == 1


def test_ac6_warning_logged_at_max_steps_martingale_inverse() -> None:
    """AC6 : martingale_inverse, atteinte de max_steps → warning loggé exactement une fois."""
    manager = make_manager(mode="martingale_inverse", risk_percent=1.0, factor=1.5, max_steps=2)

    with patch("src.capital.martingale.logger") as mock_logger:
        manager.record_trade_result(won=True)
        manager.record_trade_result(won=True)  # max_steps atteint ici

        assert mock_logger.warning.call_count == 1
        warning_args = mock_logger.warning.call_args[0]
        assert "max_steps atteint" in warning_args[0]

        # 3ème gain → toujours plafonné, pas de warning supplémentaire
        manager.record_trade_result(won=True)
        assert mock_logger.warning.call_count == 1


def test_ac6_no_warning_before_max_steps() -> None:
    """AC6 (complémentaire) : warning PAS loggé avant d'atteindre max_steps."""
    manager = make_manager(mode="martingale", risk_percent=1.0, factor=2.0, max_steps=3)

    with patch("src.capital.martingale.logger") as mock_logger:
        manager.record_trade_result(won=False)  # 1ère perte — pas encore max
        manager.record_trade_result(won=False)  # 2ème perte — pas encore max

        mock_logger.warning.assert_not_called()


# ── Tests supplémentaires ─────────────────────────────────────────────────────


def test_martingale_no_max_steps_accumulates_unlimited() -> None:
    """max_steps=None : la séquence s'accumule sans limite."""
    manager = make_manager(mode="martingale", risk_percent=1.0, factor=2.0, max_steps=None)

    for _ in range(5):
        manager.record_trade_result(won=False)

    qty = manager.calculate_position_size(
        balance=Decimal("10000"),
        entry_price=Decimal("50000"),
        stop_loss=Decimal("49000"),
    )
    # risk = 1% × 2^5 = 32% → risk_amount=3200 → raw=3200/1000=3.2
    assert qty == Decimal("3.200")


def test_sl_distance_zero_raises() -> None:
    """Distance SL nulle → ValueError."""
    manager = make_manager()
    with pytest.raises(ValueError, match="Distance SL invalide"):
        manager.calculate_position_size(
            balance=Decimal("10000"),
            entry_price=Decimal("50000"),
            stop_loss=Decimal("50000"),
        )


def test_quantity_zero_after_rounding_raises() -> None:
    """Quantité arrondie = 0 → ValueError."""
    manager = make_manager(step_size="1")
    with pytest.raises(ValueError, match="Quantité calculée nulle"):
        manager.calculate_position_size(
            balance=Decimal("1"),
            entry_price=Decimal("50000"),
            stop_loss=Decimal("49000"),
        )
