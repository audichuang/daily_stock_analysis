#!/usr/bin/env bash
# 本機用完即丟的 Postgres：建好 market schema 並跑到 Alembic head，給 market_data/tests 與新表的試跑用。
# 本機 .env 的 DATABASE_URL 是唯一一座正式 market 庫；新增表在正式庫 migration 之前，DB 測試只能在這裡驗。
#
#   scripts/pg_scratch.sh start   # 建立（若不存在）＋啟動＋upgrade head，最後一行印 export DATABASE_URL=...
#   scripts/pg_scratch.sh stop
#   scripts/pg_scratch.sh reset   # 停掉並刪掉資料目錄
#
# 需要 Homebrew 的 postgresql（initdb／pg_ctl／createdb／psql 在 PATH）。
# 只聽 localhost TCP、關掉 unix socket：暫存路徑常超過 socket 路徑的 103 bytes 上限，啟動會直接失敗。
set -euo pipefail

DIR="${PG_SCRATCH_DIR:-${TMPDIR:-/tmp}/dsa-pg-scratch}"
PORT="${PG_SCRATCH_PORT:-55432}"
URL="postgresql+psycopg://scratch@localhost:${PORT}/stock"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

running() { pg_ctl -D "$DIR/data" status >/dev/null 2>&1; }

case "${1:-start}" in
  start)
    for bin in initdb pg_ctl createdb psql; do
      command -v "$bin" >/dev/null || { echo "缺 $bin（brew install postgresql@17）" >&2; exit 1; }
    done
    if [ ! -d "$DIR/data" ]; then
      mkdir -p "$DIR"
      initdb -D "$DIR/data" -U scratch --auth=trust >/dev/null
    fi
    if ! running; then
      pg_ctl -D "$DIR/data" -o "-p $PORT -k '' -c listen_addresses=localhost" -l "$DIR/server.log" -w start >/dev/null
    fi
    if ! psql -h localhost -p "$PORT" -U scratch -lqt | cut -d'|' -f1 | grep -qw stock; then
      createdb -h localhost -p "$PORT" -U scratch stock
    fi
    psql -q -h localhost -p "$PORT" -U scratch stock -c "CREATE SCHEMA IF NOT EXISTS market"
    (cd "$ROOT" && DATABASE_URL="$URL" uv run python -m alembic -c market_data/alembic.ini upgrade head) >&2
    echo "export DATABASE_URL=$URL"
    ;;
  stop)
    if running; then pg_ctl -D "$DIR/data" -m fast stop >/dev/null; fi
    ;;
  reset)
    if running; then pg_ctl -D "$DIR/data" -m fast stop >/dev/null; fi
    rm -rf "$DIR"
    ;;
  *)
    echo "usage: $0 [start|stop|reset]" >&2; exit 2 ;;
esac
