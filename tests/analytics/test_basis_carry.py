import pandas as pd
import pytest

from echolon.analytics.basis_carry import annualized_carry_cost, basis_series


def test_discount_basis_and_annualized_short_hedge_cost_anchor():
    dates = pd.to_datetime(["2023-01-03"])
    basis = basis_series(pd.Series([5_880.0], index=dates), pd.Series([6_000.0], index=dates))
    carry = annualized_carry_cost(basis, pd.Series([60.0], index=dates))

    assert basis.iloc[0] == pytest.approx(-0.02, abs=1e-9)
    assert carry.iloc[0] == pytest.approx(0.02 * 365.0 / 60.0, abs=1e-9)


def test_premium_basis_means_short_earns_carry():
    dates = pd.to_datetime(["2023-01-03"])
    basis = basis_series(pd.Series([6_120.0], index=dates), pd.Series([6_000.0], index=dates))
    carry = annualized_carry_cost(basis, pd.Series([60.0], index=dates))

    assert carry.iloc[0] < 0.0
