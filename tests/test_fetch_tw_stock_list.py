# -*- coding: utf-8 -*-
"""scripts/fetch_tw_stock_list.py 的解析规则：哪些代号进台股自动补全索引。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from fetch_tw_stock_list import decode_big5, parse_rows  # noqa: E402


def _row(code: str, name: str, cfi: str) -> str:
    # ISIN 页面一列 7 格：「代号　名称」、ISIN、上市日、市场别、产业别、CFICode、备注
    return (
        f"<tr><td>{code}　{name}</td><td>TW000{code}</td><td>2010/01/01</td>"
        f"<td>上市</td><td></td><td>{cfi}</td><td></td></tr>"
    )


def _parse(*rows: str) -> dict:
    html = "<table>" + "".join(rows) + "</table>"
    return dict(parse_rows(html, "TW"))


def test_keeps_lettered_etfs_and_preferred_shares():
    got = _parse(
        _row("2330", "台積電", "ESVUFR"),
        _row("00631L", "元大台灣50正2", "CEOGDU"),
        _row("00679B", "元大美債20年", "CEOIBU"),
        _row("00400A", "主動國泰動能高息", "CEOJEU"),
        _row("1101B", "台泥乙特", "EPNRAR"),
        _row("2897B", "王道銀乙特", "EFNRAR"),
    )
    assert set(got) == {
        "2330.TW", "00631L.TW", "00679B.TW", "00400A.TW", "1101B.TW", "2897B.TW",
    }


def test_excludes_warrants_etn_reits_and_abs_even_with_valid_code_shape():
    # 这些代号同样是「数字 + 一个尾字母」，挡掉它们的是 CFI，不是代号格式。
    got = _parse(
        _row("03001T", "啟碁台新5A售02", "RWSCPE"),
        _row("02001L", "富邦蘋果正二N", "CMXXXU"),
        _row("01001T", "土銀富邦R1", "CBCIXU"),
        _row("01111S", "081中租賃A", "DAFUFR"),
    )
    assert got == {}


def test_rejects_malformed_codes():
    got = _parse(
        _row("2330AB", "兩個尾字母", "ESVUFR"),
        _row("233", "太短", "ESVUFR"),
        _row("１２３４", "全形數字", "ESVUFR"),
    )
    assert got == {}


def test_decode_big5_keeps_cp950_extension_characters():
    raw = "宏碁 恒耀".encode("cp950")
    assert decode_big5(raw) == "宏碁 恒耀"
