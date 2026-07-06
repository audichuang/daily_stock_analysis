import json
from pathlib import Path

from market_data import etl

FIX = Path(__file__).parent / "fixtures"


def test_transform_valuation_parses_roc_date_and_blanks():
    rows = json.loads((FIX / "bwibbu.json").read_bytes())
    df = etl.transform_valuation(rows)
    assert df.index.names == ["stock_id", "date"]
    r = df.loc[("1101", df.index.get_level_values("date")[0])]
    assert float(r["dividend_yield"]) == 3.38
    assert float(r["pb_ratio"]) == 0.75
    # 台泥 PEratio was blank "" -> NaN, not 0
    assert r["pe_ratio"] != r["pe_ratio"]  # NaN
    # ROC 1150703 -> 2026-07-03
    assert str(df.index.get_level_values("date")[0])[:10] == "2026-07-03"


def test_transform_index_maps_taiex():
    rows = json.loads((FIX / "fmtqik.json").read_bytes())
    df = etl.transform_index(rows)
    assert df.index.names == ["index_id", "date"]
    last = df.xs("TAIEX", level="index_id").iloc[-1]
    assert float(last["close"]) == 46780.62
    assert float(last["change"]) == 36.46
    assert int(last["turnover"]) == 1078028137102
