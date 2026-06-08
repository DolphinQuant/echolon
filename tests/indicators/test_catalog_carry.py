"""Carry indicators in the catalog — Step 1 of the carry catalog refactor.

The 5 forward-curve carry indicators are intentionally NOT in INDICATOR_MAPPING
(they take a multi-contract curve_snapshot, not a single-contract df). Before
this change they were invisible to ``catalog.info`` / ``validate`` — so the
qorka coding/QC agents (which delegate to this catalog) concluded carry "isn't a
real indicator" and deleted it. They must now be discoverable, tagged by kind +
compute_source, while staying out of the per-contract ta-lib map.
"""
from echolon.indicators import catalog

CARRY_NAMES = (
    "carry_front_back",
    "curve_slope_near",
    "risk_adj_carry",
    "carry_z_3m",
    "carry_change_20d",
)


def test_carry_indicators_present_in_catalog():
    names = set(catalog.list_all())
    for n in CARRY_NAMES:
        assert n in names, f"{n} missing from catalog.list_all()"


def test_carry_info_tagged_curve_kind_and_injection_source():
    cfb = catalog.info("carry_front_back")
    assert cfb is not None
    assert cfb.kind == "curve_carry"
    # Step 1: carry is still qorka-injected (Path-B); engine-compute is Step 2.
    assert cfb.compute_source == "external_injection"
    assert cfb.requires == "forward_curve_snapshot"
    assert cfb.output == "per_date_scalar_broadcast"


def test_carry_indicator_params_match_calc_defaults():
    z = catalog.info("carry_z_3m")
    assert z is not None
    window = next((p for p in z.params if p["name"] == "window"), None)
    assert window is not None, f"window param missing: {z.params}"
    assert window["default"] == 63

    change = catalog.info("carry_change_20d")
    lag = next((p for p in change.params if p["name"] == "lag"), None)
    assert lag is not None and lag["default"] == 20

    # data-input args (curve_snapshot / series) are NOT exposed as tunable params
    cfb = catalog.info("carry_front_back")
    assert all(p["name"] not in ("curve_snapshot", "carry_history",
                                 "front_settlement_series") for p in cfb.params)


def test_talib_indicators_retain_per_contract_kind():
    # Regression: existing ta-lib entries keep the per-contract pipeline kind.
    atr = catalog.info("atr")
    assert atr is not None
    assert atr.kind == "per_contract_talib"
    assert atr.compute_source == "echolon_pipeline"
    assert atr.requires == "single_contract_ohlcv"


def test_validate_accepts_carry_name_ind004_retired():
    # The old IND-004 "unknown indicator" rejection of carry is retired:
    # a declared carry name now validates clean against the catalog.
    errors = catalog.validate({"carry_front_back": {}})
    assert errors == [], f"carry_front_back should validate clean, got: {errors}"


def test_validate_is_kind_aware_for_carry_params():
    # validate is catalog-backed, so it validates a curve_carry indicator's
    # OWN params (window/n/lag) — not the ta-lib param set.
    assert catalog.validate({"carry_z_3m": {"window": [40, 80]}}) == []
    # unknown param on a carry indicator → IND-005 (param-level awareness)
    bad_param = catalog.validate({"carry_z_3m": {"bogus_param": 5}})
    assert any(e["code"] == "IND-005" for e in bad_param), bad_param
    # range validation still applies to carry params
    bad_range = catalog.validate({"carry_z_3m": {"window": [80, 40]}})
    assert any(e["code"] == "IND-006" for e in bad_range), bad_range
