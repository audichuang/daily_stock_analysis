# -*- coding: utf-8 -*-
"""STORAGE_DATABASE_URL 选库与按方言分派的 upsert。

不连真库：``create_engine`` 不建立连线就能拿到方言。两种方言编出的 ON CONFLICT
字串长得一样，所以断言构造器型别而不是 SQL 文本。
"""
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest
import sqlalchemy
from sqlalchemy import create_engine
from sqlalchemy.dialects import postgresql, sqlite

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from src.config import Config
from src.storage import ConversationSummary, DatabaseManager


def test_get_db_url_prefers_storage_database_url(tmp_path):
    url = "postgresql+psycopg://u:p@db.invalid:5432/stock?options=-csearch_path%3Ddsa"
    config = Config(database_path=str(tmp_path / "x.db"), storage_database_url=url)
    assert config.get_db_url() == url


def test_get_db_url_defaults_to_sqlite_path(tmp_path):
    db_path = tmp_path / "sub" / "x.db"
    config = Config(database_path=str(db_path))
    assert config.get_db_url() == f"sqlite:///{db_path.absolute()}"
    assert db_path.parent.is_dir()


def test_dotenv_storage_url_does_not_leak_into_test_process(tmp_path, monkeypatch):
    """本机 .env 的 STORAGE_DATABASE_URL 是正式库；测试行程里重载 .env 也不能让它生效。"""
    from src.config import setup_env

    env_file = tmp_path / ".env"
    env_file.write_text("STORAGE_DATABASE_URL=postgresql+psycopg://u:p@db.invalid/leak\n", encoding="utf-8")
    monkeypatch.setenv("ENV_FILE", str(env_file))

    setup_env()

    assert os.environ["STORAGE_DATABASE_URL"] == ""
    assert Config._load_from_env().get_db_url().startswith("sqlite:")


def test_storage_engine_refuses_production_url(monkeypatch):
    """env 被 patch.dict(clear=True) 清掉再重载 .env 时，最后一道是建 engine 的出口。"""
    import src.storage as storage

    prod_url = "postgresql+psycopg://u:p@db.invalid:5432/prod?options=-csearch_path%3Ddsa"
    monkeypatch.setitem(storage.create_engine.__globals__, "_PROD_STORAGE_DATABASE_URL", prod_url)

    with pytest.raises(RuntimeError, match="production STORAGE_DATABASE_URL"):
        storage.create_engine(prod_url)
    storage.create_engine("postgresql+psycopg://u:p@db.invalid:5432/other")


def test_prod_url_guard_finds_dotenv_above_a_worktree(tmp_path):
    """git worktree 底下沒有 .env；守門要往上找到主 repo 的 .env，否則 worktree 跑測試會寫進正式庫。"""
    import src.storage as storage

    find = storage.create_engine.__globals__["_find_prod_storage_url"]
    (tmp_path / ".env").write_text("STORAGE_DATABASE_URL=postgresql+psycopg://u:p@db.invalid/prod\n", encoding="utf-8")
    worktree_tests = tmp_path / ".claude" / "worktrees" / "wt" / "tests"
    worktree_tests.mkdir(parents=True)
    conftest_path = worktree_tests / "conftest.py"

    assert find(conftest_path) == "postgresql+psycopg://u:p@db.invalid/prod"

    # The nearest .env wins, so a worktree with its own .env is still guarded by that one.
    (worktree_tests.parent / ".env").write_text("STORAGE_DATABASE_URL=postgresql+psycopg://u:p@db.invalid/near\n", encoding="utf-8")
    assert find(conftest_path) == "postgresql+psycopg://u:p@db.invalid/near"


@pytest.fixture
def storage_guard_worktree(tmp_path, monkeypatch):
    """建立獨立 Git repo 與樹外 worktree，全程只用假的正式庫 URL。"""
    main_checkout = tmp_path / "main checkout"
    main_checkout.mkdir()
    worktree = tmp_path / "cache" / "upstream-sync"
    for args in (
        ("init", "-q"),
        ("commit", "-q", "--allow-empty", "-m", "Initialize storage guard fixture"),
        ("worktree", "add", "-q", "--detach", str(worktree)),
    ):
        subprocess.run(
            [
                "git", "-c", f"core.hooksPath={os.devnull}",
                "-c", "commit.gpgsign=false",
                "-c", "user.name=Storage guard tests",
                "-c", "user.email=storage-guard@example.invalid",
                *args,
            ],
            cwd=main_checkout, check=True, capture_output=True, text=True, timeout=10,
        )
    prod_url = "postgresql+psycopg://u:p@db.invalid/prod"
    (main_checkout / ".env").write_text(
        f"STORAGE_DATABASE_URL='{prod_url}  '\n", encoding="utf-8",
    )
    worktree_tests = worktree / "tests"
    worktree_tests.mkdir()
    monkeypatch.chdir(tmp_path)
    return main_checkout, worktree_tests, prod_url


def test_prod_url_guard_finds_out_of_tree_worktree_dotenv(storage_guard_worktree, monkeypatch):
    import src.storage as storage

    _, worktree_tests, prod_url = storage_guard_worktree
    guard_globals = storage.create_engine.__globals__
    found_url = guard_globals["_find_prod_storage_url"](worktree_tests / "conftest.py")
    assert found_url == prod_url
    monkeypatch.setitem(guard_globals, "_PROD_STORAGE_DATABASE_URL", found_url)

    for factory in (storage.create_engine, sqlalchemy.create_engine, sqlalchemy.engine.create_engine):
        with pytest.raises(RuntimeError, match="production STORAGE_DATABASE_URL"):
            factory(prod_url)
        engine = factory("sqlite:///:memory:")
        try:
            with engine.connect() as connection:
                assert connection.exec_driver_sql("SELECT 1").scalar_one() == 1
        finally:
            engine.dispose()


@pytest.mark.parametrize("value", ["postgresql+psycopg://u:p@db.invalid/near", "", None])
def test_prod_url_guard_keeps_worktree_dotenv_precedence(storage_guard_worktree, monkeypatch, value):
    import src.storage as storage

    _, worktree_tests, _ = storage_guard_worktree
    content = f"STORAGE_DATABASE_URL={value}\n" if value is not None else "OTHER_SETTING=true\n"
    (worktree_tests.parent / ".env").write_text(content, encoding="utf-8")

    def unexpected_git_lookup(*args, **kwargs):
        pytest.fail("已有最近的 .env 時不應查詢主 checkout")

    monkeypatch.setattr(subprocess, "run", unexpected_git_lookup)
    find = storage.create_engine.__globals__["_find_prod_storage_url"]
    assert find(worktree_tests / "conftest.py") == (value or "")


def test_prod_url_guard_resolves_relative_git_common_dir(storage_guard_worktree, monkeypatch):
    import src.storage as storage

    main_checkout, worktree_tests, prod_url = storage_guard_worktree
    real_run = subprocess.run

    def relative_common_dir(args, **kwargs):
        assert args == ["git", "rev-parse", "--git-common-dir"]
        assert kwargs["cwd"] == worktree_tests.resolve()
        result = real_run(args, **kwargs)
        result.stdout = os.path.relpath(main_checkout / ".git", worktree_tests) + "\n"
        return result

    monkeypatch.setattr(subprocess, "run", relative_common_dir)
    find = storage.create_engine.__globals__["_find_prod_storage_url"]
    assert find(worktree_tests / "conftest.py") == prod_url


def test_prod_url_guard_without_dotenv_or_git_ignores_cwd(storage_guard_worktree, monkeypatch):
    import src.storage as storage

    main_checkout, worktree_tests, _ = storage_guard_worktree
    outside_tests = worktree_tests.parents[2] / "unrelated" / "tests"
    outside_tests.mkdir(parents=True)
    find = storage.create_engine.__globals__["_find_prod_storage_url"]
    # 即使執行行程位於有 .env 的 checkout，也只能查詢 start 所屬的 repo。
    monkeypatch.chdir(main_checkout)
    assert find(outside_tests / "conftest.py") == ""


@pytest.mark.parametrize("failure", [
    FileNotFoundError("git unavailable"),
    subprocess.CalledProcessError(128, ["git", "rev-parse"]),
    subprocess.TimeoutExpired(["git", "rev-parse"], 5),
])
def test_prod_url_guard_handles_git_lookup_failure(storage_guard_worktree, monkeypatch, failure):
    import src.storage as storage

    _, worktree_tests, _ = storage_guard_worktree

    def failed_git_lookup(*args, **kwargs):
        raise failure

    monkeypatch.setattr(subprocess, "run", failed_git_lookup)
    find = storage.create_engine.__globals__["_find_prod_storage_url"]
    assert find(worktree_tests / "conftest.py") == ""


def test_prod_url_guard_handles_main_checkout_without_dotenv(tmp_path):
    import src.storage as storage

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, capture_output=True, timeout=10)
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    find = storage.create_engine.__globals__["_find_prod_storage_url"]
    assert find(tests_dir / "conftest.py") == ""


def _manager_for(url: str):
    return SimpleNamespace(_engine=create_engine(url))


def test_upsert_insert_uses_postgresql_dialect():
    stmt = DatabaseManager.upsert_insert(
        _manager_for("postgresql+psycopg://u:p@db.invalid/stock"), ConversationSummary
    )
    assert isinstance(stmt, postgresql.Insert)
    assert not isinstance(stmt, sqlite.Insert)


def test_upsert_insert_keeps_sqlite_dialect():
    stmt = DatabaseManager.upsert_insert(_manager_for("sqlite:///:memory:"), ConversationSummary)
    assert isinstance(stmt, sqlite.Insert)
    assert not isinstance(stmt, postgresql.Insert)


def test_upsert_insert_rejects_unsupported_dialect():
    with pytest.raises(NotImplementedError):
        fake = SimpleNamespace(_engine=SimpleNamespace(dialect=SimpleNamespace(name="mysql")))
        DatabaseManager.upsert_insert(fake, ConversationSummary)


def test_all_storage_ddl_compiles_for_postgresql():
    """Postgres 识别字上限 63 字元，SQLite 没有；超长的显式名称只会在真的建表时炸。"""
    from sqlalchemy.schema import CreateIndex, CreateTable

    from src.storage import Base

    dialect = postgresql.dialect()
    for table in Base.metadata.sorted_tables:
        str(CreateTable(table).compile(dialect=dialect))
        for index in table.indexes:
            str(CreateIndex(index).compile(dialect=dialect))


def test_backtest_eval_status_column_fits_engine_statuses():
    """SQLite 不检查 VARCHAR 长度，Postgres 会；回测引擎写入的状态必须放得下。"""
    from src.storage import BacktestResult

    limit = BacktestResult.__table__.c.eval_status.type.length
    for status in ("pending", "completed", "insufficient_data", "unable", "error"):
        assert len(status) <= limit, status


@pytest.mark.parametrize("key", ["STORAGE_DATABASE_URL", "DATABASE_URL"])
def test_database_url_keys_are_sensitive_in_settings(key):
    """URL 内嵌帐密；未登记的 key 只靠名称推断敏感性，漏判就会以明文欄位显示。"""
    from src.core.config_registry import get_field_definition

    assert get_field_definition(key, "postgresql+psycopg://u:p@h/db")["is_sensitive"] is True


def test_database_path_stays_non_sensitive():
    from src.core.config_registry import get_field_definition

    assert get_field_definition("DATABASE_PATH", "./data/x.db")["is_sensitive"] is False
