"""Phase A1 — Tests for catalog hydration from INDICATOR_MAPPING + ta_lib signatures.

These tests are written FIRST (TDD). They fail against the 7-item hardcoded seed
and pass once catalog.py is rewritten to load from the real registry.
"""
from echolon.indicators import catalog


def test_catalog_has_at_least_170_entries():
    names = catalog.list_all()
    assert len(names) >= 170, f"Expected >= 170 entries, got {len(names)}"


def test_catalog_supports_cluster_filter_lookback():
    lookback = set(catalog.list_all(cluster="indicators_with_lookback"))
    for expected in ("rsi", "atr", "adx", "ema"):
        assert expected in lookback, (
            f"'{expected}' missing from indicators_with_lookback cluster; "
            f"got sample: {sorted(lookback)[:10]}"
        )


def test_catalog_cluster_filter_no_lookback_excludes_lookback_names():
    no_lookback = set(catalog.list_all(cluster="indicators_without_lookback"))
    for name in ("rsi", "atr", "adx", "ema"):
        assert name not in no_lookback, (
            f"'{name}' should NOT appear in indicators_without_lookback cluster"
        )


def test_catalog_info_returns_cluster_and_params_for_rsi():
    rsi = catalog.info("rsi")
    assert rsi is not None
    assert rsi.cluster == "indicators_with_lookback"
    param_names = [p["name"] for p in rsi.params]
    assert "timeperiod" in param_names, f"timeperiod not in params: {param_names}"
    tp = next(p for p in rsi.params if p["name"] == "timeperiod")
    assert tp["default"] == 14, f"Expected default=14, got {tp['default']}"


def test_catalog_info_bbands_upper_is_special_params():
    bbands_upper = catalog.info("bbands_upper")
    assert bbands_upper is not None
    assert bbands_upper.cluster == "indicators_with_special_params", (
        f"Expected indicators_with_special_params, got {bbands_upper.cluster}"
    )


def test_catalog_info_obv_is_no_lookback():
    obv = catalog.info("obv")
    assert obv is not None
    assert obv.cluster == "indicators_without_lookback"


def test_catalog_info_is_case_insensitive():
    upper = catalog.info("RSI")
    lower = catalog.info("rsi")
    assert upper is not None
    assert lower is not None
    assert upper.name == lower.name
    assert upper.cluster == lower.cluster
    assert upper.params == lower.params


def test_catalog_info_unknown_returns_none():
    assert catalog.info("fake_indicator_xyz_123") is None
    assert catalog.info("SPEAK_BLUE_TURTLE_INDEX") is None
    assert catalog.info("") is None


def test_catalog_output_columns_for_lookback_contains_period_template():
    rsi = catalog.info("rsi")
    assert rsi is not None
    assert any("{period}" in col for col in rsi.output_columns), (
        f"Expected a template column with '{{period}}', got: {rsi.output_columns}"
    )


def test_catalog_output_columns_for_no_lookback_is_name():
    obv = catalog.info("obv")
    assert obv is not None
    assert obv.output_columns == ["obv"]


def test_catalog_list_all_is_sorted():
    names = catalog.list_all()
    assert names == sorted(names), "list_all() must return sorted names"


def test_catalog_list_all_no_filter_includes_all_clusters():
    all_names = set(catalog.list_all())
    for cluster_name in (
        "indicators_with_lookback",
        "indicators_without_lookback",
        "indicators_with_special_params",
    ):
        cluster_names = set(catalog.list_all(cluster=cluster_name))
        assert cluster_names.issubset(all_names), (
            f"cluster '{cluster_name}' names are not a subset of list_all()"
        )


def test_catalog_info_has_function_and_file():
    rsi = catalog.info("rsi")
    assert rsi is not None
    assert rsi.function == "rsi"
    assert rsi.file == "ta_lib"


def test_catalog_bbands_entries_share_params():
    """BBANDS_UPPER/MIDDLE/LOWER all dispatch to bbands(); params must match."""
    upper = catalog.info("bbands_upper")
    middle = catalog.info("bbands_middle")
    lower = catalog.info("bbands_lower")
    assert upper is not None and middle is not None and lower is not None
    # All three share the same underlying function and therefore the same params
    assert upper.params == middle.params == lower.params
    param_names = {p["name"] for p in upper.params}
    assert {"timeperiod", "nbdevup", "nbdevdn", "matype"}.issubset(param_names), (
        f"bbands params should include timeperiod/nbdevup/nbdevdn/matype, got {param_names}"
    )
