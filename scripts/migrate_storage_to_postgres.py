#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 DSA 应用库（分析历史、回测、LLM 用量等）从 SQLite 搬到 Postgres 的独立 schema。

和 ``migrate_sqlite_to_pg.py`` 无关：那支搬的是 finlab 行情到 ``market`` schema、
会 TRUNCATE、没有参数。这支只碰 ``--schema`` 指定的 schema 里 ``src.storage``
定义的表。

步骤：建 schema（不存在时）→ 用 ``DatabaseManager`` 建表 → 依外键顺序逐表复制
→ 把自增序列推到 max(id) → 逐表比对行数。

目标表非空时默认中止；``--replace`` 先清空这些表（只限本 schema 的 DSA 表）再搬。

用法：
    uv run python scripts/migrate_storage_to_postgres.py \\
        --target-url "$STORAGE_DATABASE_URL" --schema dsa [--sqlite data/stock_analysis.db] \\
        [--dry-run] [--replace]

``--target-url`` 的 search_path 必须指向 ``--schema``（例如 URL 带
``?options=-csearch_path%3Ddsa``），否则表会建到别的 schema——脚本会检查并中止。
"""
import argparse
import os
import re
import sys
from pathlib import Path

from sqlalchemy import create_engine, func, select, text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

BATCH = 500
_SCHEMA_RE = re.compile(r"^[a-z_][a-z0-9_]*$")


def _redact(url: str) -> str:
    return re.sub(r"://([^:/@]+):[^@]*@", r"://\1:***@", url)


def _sqlite_columns(engine, table_name: str) -> set:
    with engine.connect() as conn:
        rows = conn.exec_driver_sql(f'PRAGMA table_info("{table_name}")').fetchall()
    return {row[1] for row in rows}


def main() -> int:
    ap = argparse.ArgumentParser(description="DSA SQLite 应用库 → Postgres schema")
    ap.add_argument("--sqlite", default="data/stock_analysis.db", help="来源 SQLite 档")
    ap.add_argument("--target-url", default=os.environ.get("STORAGE_DATABASE_URL", ""),
                    help="目标 SQLAlchemy URL（默认读 STORAGE_DATABASE_URL）")
    ap.add_argument("--schema", required=True, help="目标 schema，例如 dsa")
    ap.add_argument("--dry-run", action="store_true", help="只列出会搬什么，不写入")
    ap.add_argument("--replace", action="store_true", help="目标表非空时先清空再搬")
    args = ap.parse_args()

    if not _SCHEMA_RE.match(args.schema):
        print(f"[Error] schema 名称不合法: {args.schema!r}", file=sys.stderr)
        return 2
    if not args.target_url.startswith("postgresql"):
        print("[Error] --target-url 必须是 postgresql URL", file=sys.stderr)
        return 2
    sqlite_path = Path(args.sqlite)
    if not sqlite_path.is_file():
        print(f"[Error] 找不到 SQLite 档: {sqlite_path}", file=sys.stderr)
        return 2

    src_engine = create_engine(f"sqlite:///file:{sqlite_path.resolve()}?mode=ro&uri=true")
    print(f"来源: {sqlite_path}")
    print(f"目标: {_redact(args.target_url)} (schema={args.schema})")

    from src.storage import Base

    with src_engine.connect() as conn:
        src_tables = {r[0] for r in conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    unknown = sorted(src_tables - set(Base.metadata.tables) - {"sqlite_sequence"})
    if unknown:
        print(f"[Error] 来源有 ORM 未定义的表，不会被搬: {unknown}", file=sys.stderr)
        return 1

    plan = []
    with src_engine.connect() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in src_tables:
                continue
            present = _sqlite_columns(src_engine, table.name)
            cols = [c for c in table.columns if c.name in present]
            dropped = sorted(present - {c.name for c in table.columns})
            count = conn.execute(select(func.count()).select_from(table)).scalar_one()
            plan.append((table, cols, count))
            note = f"（来源多出未定义栏位，略过: {dropped}）" if dropped else ""
            print(f"  {table.name:32s} {count:>7d} 行{note}")

    if args.dry_run:
        print("dry-run：未写入。")
        return 0

    tgt_engine = create_engine(args.target_url)
    with tgt_engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{args.schema}"'))
    with tgt_engine.connect() as conn:
        current = conn.execute(text("SELECT current_schema()")).scalar()
    if current != args.schema:
        print(f"[Error] 连线的 current_schema()={current!r}，不是 {args.schema!r}；"
              "请在 URL 设 search_path（?options=-csearch_path%3D" + args.schema + "）",
              file=sys.stderr)
        return 1

    # DatabaseManager 负责建表与 schema_migrations 基线，与正式运行同一条路径。
    from src.storage import DatabaseManager
    DatabaseManager(db_url=args.target_url)

    names = [t.name for t, _, _ in plan]
    with tgt_engine.begin() as conn:
        nonempty = [
            n for n in names
            if n != "schema_migrations"
            and conn.execute(text(f'SELECT EXISTS (SELECT 1 FROM "{args.schema}"."{n}")')).scalar()
        ]
        if nonempty and not args.replace:
            print(f"[Error] 目标表非空，未加 --replace，中止: {nonempty}", file=sys.stderr)
            return 1
        quoted = ", ".join(f'"{args.schema}"."{n}"' for n in names)
        conn.execute(text(f"TRUNCATE {quoted} RESTART IDENTITY"))

        for table, cols, count in plan:
            copied = 0
            with src_engine.connect() as src:
                result = src.execute(select(*cols)).mappings()
                while True:
                    rows = result.fetchmany(BATCH)
                    if not rows:
                        break
                    conn.execute(table.insert(), [dict(r) for r in rows])
                    copied += len(rows)
            if copied != count:
                raise RuntimeError(f"{table.name}: 读到 {copied} 行，预期 {count}")

        for table, _, _ in plan:
            pk = list(table.primary_key.columns)
            if len(pk) == 1 and pk[0].autoincrement is True:
                conn.execute(text(
                    f"SELECT setval(pg_get_serial_sequence('\"{args.schema}\".\"{table.name}\"', "
                    f"'{pk[0].name}'), COALESCE((SELECT MAX(\"{pk[0].name}\") "
                    f"FROM \"{args.schema}\".\"{table.name}\"), 0) + 1, false)"
                ))

    mismatched = []
    with tgt_engine.connect() as conn:
        for table, _, count in plan:
            got = conn.execute(text(f'SELECT COUNT(*) FROM "{args.schema}"."{table.name}"')).scalar()
            if got != count:
                mismatched.append((table.name, count, got))
    if mismatched:
        print(f"[Error] 行数不符: {mismatched}", file=sys.stderr)
        return 1
    print(f"完成：{len(plan)} 张表、{sum(c for _, _, c in plan)} 行，行数逐表相符。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
