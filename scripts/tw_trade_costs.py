"""相容 shim：台股交易成本的真源已移到 `src/utils/tw_trade_costs.py`。

研究腳本與每日報告的成本檢核（`src/trade_cost_guardrail.py`）必須用同一組費率，
而 `src/` 不能反過來 import `scripts/`，所以真源放在 `src/`、這裡只轉出。
不要在這裡加任何常數或邏輯。
"""

import sys
from pathlib import Path

_REPO = str(Path(__file__).resolve().parent.parent)
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from src.utils.tw_trade_costs import *  # noqa: E402,F401,F403
from src.utils.tw_trade_costs import _validate_slippage  # noqa: E402,F401
