"""CLI wrapper：實作在 `src/services/tw_stock_dossier.py`（Web API 也用同一份）。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.services.tw_stock_dossier import main  # noqa: E402

if __name__ == "__main__":
    main()
