#!/usr/bin/env python3
"""手動刷新行事曆應用庫快取；可指定隔離 SQLite，預設使用既有應用庫設定。"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    from src.services.calendar_service import CalendarService
    print(json.dumps(CalendarService().refresh(), ensure_ascii=False))


if __name__ == "__main__":
    main()
