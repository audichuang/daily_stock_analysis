# -*- coding: utf-8 -*-
"""贴上持股文字匯入：名称/裸代号依帐户市场解析、缺成本不入帐、重贴去重。"""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

import src.auth as auth  # noqa: E402
from api.app import create_app  # noqa: E402
from src.config import Config  # noqa: E402
from src.services.portfolio_import_service import PortfolioImportService  # noqa: E402
from src.services.portfolio_service import PortfolioService  # noqa: E402
from src.storage import DatabaseManager  # noqa: E402

# 结构与 get_chat_stock_lookup() 相同：key -> ((code, name, kind), ...)
FAKE_LOOKUP = {
    "names": {
        "元大台灣50正2": (("00631L.TW", "元大台灣50正2", "stock"),),
        "聯電": (("2303.TW", "聯電", "stock"),),
        "联电": (("2303.TW", "聯電", "stock"),),
        "精成科": (("6191.TW", "精成科", "stock"),),
        # 同名跨市场：台股帐户只该看到 .TW 那一档
        "同名": (("1234.TW", "同名", "stock"), ("01234.HK", "同名", "stock")),
        # 同市场同名两档：必须拒绝，不能猜
        "撞名": (("1111.TW", "撞名", "stock"), ("2222.TWO", "撞名", "stock")),
    },
    "codes": {
        "00631L.TW": (("00631L.TW", "元大台灣50正2", "stock"),),
        "2303.TW": (("2303.TW", "聯電", "stock"),),
        "6191.TW": (("6191.TW", "精成科", "stock"),),
        "8069.TWO": (("8069.TWO", "元太", "stock"),),
        "2330": (("02330.HK", "港股撞号", "stock"),),
        "2330.TW": (("2330.TW", "台積電", "stock"),),
    },
    "index_rows": [],
}


def _parse(text: str, market: str = "tw") -> dict:
    with patch("src.services.portfolio_import_service.get_chat_stock_lookup", return_value=FAKE_LOOKUP):
        return PortfolioImportService.__new__(PortfolioImportService).parse_holdings_text(
            text=text, market=market, trade_date=date(2026, 10, 15)
        )


class ParseHoldingsTextTestCase(unittest.TestCase):
    def test_name_with_trailing_letter_and_simplified_name_resolve(self) -> None:
        parsed = _parse("元大台灣50正2 2,000 38.5\n联电\t450\t142.5\n")
        self.assertEqual([r["symbol"] for r in parsed["records"]], ["00631L.TW", "2303.TW"])
        self.assertEqual(parsed["records"][0]["quantity"], 2000.0)
        self.assertEqual(parsed["records"][0]["price"], 38.5)

    def test_bare_code_takes_suffix_from_index_not_concatenation(self) -> None:
        # 8069 只在上柜（.TWO）；盲目补 .TW 会得到不存在的 8069.TW。
        # 2330 的裸 key 在索引里是港股，台股帐户必须改走 2330.TW。
        parsed = _parse("8069 1000 150\n2330 1 900\n")
        self.assertEqual([r["symbol"] for r in parsed["records"]], ["8069.TWO", "2330.TW"])

    def test_cross_market_same_name_is_scoped_to_account_market(self) -> None:
        parsed = _parse("同名 10 20\n")
        self.assertEqual([r["symbol"] for r in parsed["records"]], ["1234.TW"])

    def test_ambiguous_name_in_same_market_is_rejected(self) -> None:
        parsed = _parse("撞名 10 20\n")
        self.assertEqual(parsed["records"], [])
        self.assertEqual(parsed["error_count"], 1)
        self.assertIn("1111.TW", parsed["errors"][0])

    def test_missing_cost_is_reported_not_defaulted(self) -> None:
        parsed = _parse("精成科 5000\n")
        self.assertEqual(parsed["records"], [])
        self.assertEqual(
            parsed["missing_cost"],
            [{"line": 1, "symbol": "6191.TW", "name": "精成科", "quantity": 5000.0}],
        )

    def test_broker_inventory_row_uses_today_balance_and_has_no_cost(self) -> None:
        # 券商库存表整列：昨日餘額 / 今日餘額 / 賣超 / 市值 / … / 即時價位。
        # 最后一栏是现价，不能被当成成本。
        text = (
            "商品\t昨日餘額\t今日餘額\t賣超(含委託)\t市值\n"
            "精成科\t4,000\t5,000\t\t477,000\t\t\t5\t\t\t\t\t5\t\t95.4\t\t\t\t\t\t\t\t95.2\n"
        )
        parsed = _parse(text)
        self.assertEqual(parsed["records"], [])
        self.assertEqual(parsed["skipped_count"], 1)
        self.assertEqual(parsed["missing_cost"][0]["quantity"], 5000.0)

    def test_line_date_overrides_default_and_bad_date_is_error(self) -> None:
        parsed = _parse("聯電 450 142.5 2026-01-05\n精成科 10 90 不是日期\n")
        self.assertEqual(parsed["records"][0]["trade_date"], date(2026, 1, 5))
        self.assertEqual(parsed["error_count"], 1)

    def test_unknown_name_with_numbers_is_error(self) -> None:
        parsed = _parse("不存在公司 10 20\n")
        self.assertEqual(parsed["records"], [])
        self.assertIn("不存在公司", parsed["errors"][0])


class CommitHoldingsTextTestCase(unittest.TestCase):
    def setUp(self) -> None:
        auth._auth_enabled = None
        self.temp_dir = tempfile.TemporaryDirectory()
        data_dir = Path(self.temp_dir.name)
        env_path = data_dir / ".env"
        db_path = data_dir / "portfolio_text_import.db"
        env_path.write_text(
            f"STOCK_LIST=2330.TW\nADMIN_AUTH_ENABLED=false\nDATABASE_PATH={db_path}\n", encoding="utf-8"
        )
        self._lookup_patcher = patch(
            "src.services.portfolio_import_service.get_chat_stock_lookup", return_value=FAKE_LOOKUP
        )
        self._lookup_patcher.start()
        os.environ["ENV_FILE"] = str(env_path)
        os.environ["DATABASE_PATH"] = str(db_path)
        Config.reset_instance()
        DatabaseManager.reset_instance()
        self.service = PortfolioService()
        self.client = TestClient(create_app(static_dir=data_dir / "empty-static"))
        self.account_id = self.service.create_account(
            name="TW", broker="Demo", market="tw", base_currency="TWD"
        )["id"]

    def tearDown(self) -> None:
        DatabaseManager.reset_instance()
        Config.reset_instance()
        os.environ.pop("ENV_FILE", None)
        os.environ.pop("DATABASE_PATH", None)
        self._lookup_patcher.stop()
        self.temp_dir.cleanup()

    def _post(self, path: str, **body) -> dict:
        resp = self.client.post(path, json={"account_id": self.account_id, "trade_date": "2026-10-01", **body})
        self.assertEqual(resp.status_code, 200, resp.text)
        return resp.json()

    def test_parse_endpoint_returns_missing_cost_rows(self) -> None:
        data = self._post("/api/v1/portfolio/imports/text/parse", text="聯電 450 142.5\n精成科 5000\n")
        self.assertEqual(data["record_count"], 1)
        self.assertEqual(data["missing_cost"][0]["symbol"], "6191.TW")

    def test_commit_writes_buys_and_repaste_is_deduplicated(self) -> None:
        text = "聯電 450 142.5\n元大台灣50正2 2000 38.5\n"
        first = self._post("/api/v1/portfolio/imports/text/commit", text=text)
        self.assertEqual((first["inserted_count"], first["duplicate_count"]), (2, 0))
        # 行序调换后重贴，同一份持股不能把仓位翻倍。
        again = self._post("/api/v1/portfolio/imports/text/commit", text="\n".join(reversed(text.splitlines())))
        self.assertEqual((again["inserted_count"], again["duplicate_count"]), (0, 2))

        trades = self.service.repo.list_trades(self.account_id, date(2026, 10, 15))
        self.assertEqual(
            sorted((t.symbol, t.quantity, t.price, t.market, t.currency) for t in trades),
            [("00631L.TW", 2000.0, 38.5, "tw", "TWD"), ("2303.TW", 450.0, 142.5, "tw", "TWD")],
        )
        self.assertTrue(all(t.note == "text_import" for t in trades))

    def test_commit_rejects_whole_paste_when_any_row_lacks_cost(self) -> None:
        resp = self.client.post(
            "/api/v1/portfolio/imports/text/commit",
            json={"account_id": self.account_id, "text": "聯電 450 142.5\n精成科 5000\n"},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("6191.TW", resp.text)
        self.assertEqual(self.service.repo.list_trades(self.account_id, date(2026, 10, 15)), [])

    def test_dry_run_writes_nothing(self) -> None:
        data = self._post("/api/v1/portfolio/imports/text/commit", text="聯電 450 142.5\n", dry_run=True)
        self.assertEqual(data["inserted_count"], 1)
        self.assertEqual(self.service.repo.list_trades(self.account_id, date(2026, 10, 15)), [])

    def test_unknown_account_is_bad_request(self) -> None:
        resp = self.client.post(
            "/api/v1/portfolio/imports/text/parse", json={"account_id": 99999, "text": "聯電 1 1"}
        )
        self.assertEqual(resp.status_code, 400)


if __name__ == "__main__":
    unittest.main()
