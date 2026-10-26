# -*- coding: utf-8 -*-
"""STORAGE_DATABASE_URL 选库与按方言分派的 upsert。

不连真库：``create_engine`` 不建立连线就能拿到方言。两种方言编出的 ON CONFLICT
字串长得一样，所以断言构造器型别而不是 SQL 文本。
"""
import os
import sys
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects import postgresql, sqlite

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

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
    monkeypatch.setitem(storage.create_engine.__globals__, "_PROD_DATABASE_URLS", {prod_url})

    with pytest.raises(RuntimeError, match="production STORAGE_DATABASE_URL"):
        storage.create_engine(prod_url)
    storage.create_engine("postgresql+psycopg://u:p@db.invalid:5432/other")


def test_prod_url_guard_finds_dotenv_above_a_worktree(tmp_path):
    """git worktree 底下沒有 .env；守門要往上找到主 repo 的 .env，否則 worktree 跑測試會寫進正式庫。"""
    import src.storage as storage

    find = storage.create_engine.__globals__["_find_prod_database_urls"]
    (tmp_path / ".env").write_text("STORAGE_DATABASE_URL=postgresql+psycopg://u:p@db.invalid/prod\n", encoding="utf-8")
    worktree_tests = tmp_path / ".claude" / "worktrees" / "wt" / "tests"
    worktree_tests.mkdir(parents=True)
    conftest_path = worktree_tests / "conftest.py"

    assert find(conftest_path) == {"postgresql+psycopg://u:p@db.invalid/prod"}

    # 不在 Git repo 時仍保護最近的 .env；不擴大收集其他祖先的 .env。
    (worktree_tests.parent / ".env").write_text("STORAGE_DATABASE_URL=postgresql+psycopg://u:p@db.invalid/near\n", encoding="utf-8")
    assert find(conftest_path) == {"postgresql+psycopg://u:p@db.invalid/near"}


def _git(*args, cwd):
    import subprocess

    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


def _out_of_tree_worktree(tmp_path):
    """主 checkout 在 tmp/main（帶 .env），worktree 在樹外的 tmp/cache/wt，仿 dsa-upstream-sync 的佈局。"""
    import shutil

    if shutil.which("git") is None:
        pytest.skip("git not available")
    main = tmp_path / "main"
    main.mkdir()
    _git("init", "-q", cwd=main)
    _git("commit", "-q", "--allow-empty", "-m", "init", cwd=main)
    (main / ".env").write_text("STORAGE_DATABASE_URL=postgresql+psycopg://u:p@db.invalid/prod\n", encoding="utf-8")
    worktree = tmp_path / "cache" / "wt"
    worktree.parent.mkdir()
    _git("worktree", "add", "-q", "--detach", str(worktree), cwd=main)
    tests_dir = worktree / "tests"
    tests_dir.mkdir()
    return main, worktree, tests_dir / "conftest.py"


def test_prod_url_guard_finds_main_checkout_dotenv_from_out_of_tree_worktree(tmp_path):
    """樹外 worktree 往上找不到 .env；守門要經 git common dir 找到主 checkout 的 .env。"""
    import src.storage as storage

    find = storage.create_engine.__globals__["_find_prod_database_urls"]
    _main, _worktree, conftest_path = _out_of_tree_worktree(tmp_path)

    assert find(conftest_path) == {"postgresql+psycopg://u:p@db.invalid/prod"}


def test_prod_url_guard_out_of_tree_includes_nearer_dotenv(tmp_path):
    """worktree 自己的 URL 與主 checkout 的 URL 必須同時保留。"""
    import src.storage as storage

    find = storage.create_engine.__globals__["_find_prod_database_urls"]
    _main, worktree, conftest_path = _out_of_tree_worktree(tmp_path)
    (worktree / ".env").write_text("STORAGE_DATABASE_URL=postgresql+psycopg://u:p@db.invalid/near\n", encoding="utf-8")

    assert find(conftest_path) == {
        "postgresql+psycopg://u:p@db.invalid/near",
        "postgresql+psycopg://u:p@db.invalid/prod",
    }


@pytest.mark.parametrize("location", ["main", "worktree"])
@pytest.mark.parametrize("key", ["STORAGE_DATABASE_URL", "DATABASE_URL"])
@pytest.mark.parametrize("url_object", [False, True], ids=["string", "url-object"])
def test_prod_url_guard_refuses_both_dotenvs_and_keys(tmp_path, monkeypatch, location, key, url_object):
    """最近的 .env 不同時，兩份 .env 的應用庫與行情庫仍須由所有入口拒絕。"""
    import sqlalchemy

    import src.storage as storage

    guard_globals = storage.create_engine.__globals__
    main, worktree, conftest_path = _out_of_tree_worktree(tmp_path)
    urls = {}
    for name, root in (("main", main), ("worktree", worktree)):
        urls[name] = {
            "STORAGE_DATABASE_URL": f"postgresql+psycopg://u:p@db.invalid/{name}_dsa",
            "DATABASE_URL": f"postgresql+psycopg://u:p@db.invalid/{name}_market",
        }
        (root / ".env").write_text(
            "".join(f"{env_key}={value}\n" for env_key, value in urls[name].items()),
            encoding="utf-8",
        )
    monkeypatch.setitem(
        guard_globals, "_PROD_DATABASE_URLS",
        guard_globals["_find_prod_database_urls"](conftest_path),
    )

    target = urls[location][key]
    if url_object:
        target = sqlalchemy.engine.make_url(target)
    for factory in (storage.create_engine, sqlalchemy.create_engine, sqlalchemy.engine.create_engine):
        with pytest.raises(RuntimeError, match="production"):
            factory(target)
        engine = factory("sqlite:///:memory:")
        try:
            with engine.connect() as connection:
                assert connection.exec_driver_sql("SELECT 1").scalar_one() == 1
        finally:
            engine.dispose()


@pytest.mark.parametrize("url_object", [False, True], ids=["string", "url-object"])
@pytest.mark.parametrize("safe_url", [
    "postgresql+psycopg://u:p@db.invalid/other",
    "postgresql+psycopg://u:p@other.invalid/prod",
    "postgresql+psycopg://u:p@db.invalid/prod?options=-csearch_path%3Dtest",
])
def test_prod_url_guard_forwards_unlisted_urls(monkeypatch, safe_url, url_object):
    """反向：只拒絕已知 URL，其他測試庫與建構參數必須原樣交給 SQLAlchemy。"""
    import sqlalchemy

    import src.storage as storage

    guard_globals = storage.create_engine.__globals__
    monkeypatch.setitem(guard_globals, "_PROD_DATABASE_URLS", {
        "postgresql+psycopg://u:p@db.invalid/prod",
        "postgresql+psycopg://u:p@db.invalid/market",
    })
    target = sqlalchemy.engine.make_url(safe_url) if url_object else safe_url
    calls = []
    sentinel = object()

    def create_engine(url, *args, **kwargs):
        calls.append((url, args, kwargs))
        return sentinel

    monkeypatch.setitem(guard_globals, "_original_create_engine", create_engine)
    for factory in (storage.create_engine, sqlalchemy.create_engine, sqlalchemy.engine.create_engine):
        assert factory(target, echo=True, connect_args={"application_name": "test"}) is sentinel
    assert calls == [(target, (), {"echo": True, "connect_args": {"application_name": "test"}})] * 3


@pytest.mark.parametrize("key", ["STORAGE_DATABASE_URL", "DATABASE_URL"])
def test_prod_url_guard_filters_blank_and_duplicate_urls(tmp_path, key):
    """兩種鍵都支援 dotenv 引號與空白；缺值不加入，重複的正式 URL 只保留一次。"""
    import src.storage as storage

    find = storage.create_engine.__globals__["_find_prod_database_urls"]
    main, worktree, conftest_path = _out_of_tree_worktree(tmp_path)
    url = "postgresql+psycopg://u:p@db.invalid/prod"
    (main / ".env").write_text(f"{key}='  {url}  '\n", encoding="utf-8")
    (worktree / ".env").write_text(
        f"STORAGE_DATABASE_URL\nDATABASE_URL='  '\n{key}=\" {url} \"\n", encoding="utf-8",
    )

    assert find(conftest_path) == {url}


def test_prod_url_guard_falls_back_when_nearest_dotenv_lacks_url(tmp_path):
    """worktree 自己的 .env 沒設 STORAGE_DATABASE_URL 時，還是要退到主 checkout 的 .env。"""
    import src.storage as storage

    find = storage.create_engine.__globals__["_find_prod_database_urls"]
    _main, worktree, conftest_path = _out_of_tree_worktree(tmp_path)
    (worktree / ".env").write_text("OTHER=1\n", encoding="utf-8")

    assert find(conftest_path) == {"postgresql+psycopg://u:p@db.invalid/prod"}


def test_prod_url_guard_outside_any_repo_finds_nothing(tmp_path):
    """反向：不在 repo 且往上沒有 .env 時回空集合，不能拿行程 cwd 的 .env 充數。"""
    import src.storage as storage

    find = storage.create_engine.__globals__["_find_prod_database_urls"]
    conftest_path = tmp_path / "loose" / "tests" / "conftest.py"
    conftest_path.parent.mkdir(parents=True)

    assert find(conftest_path) == set()


def test_prod_url_guard_out_of_tree_refuses_prod_url_in_every_factory(tmp_path, monkeypatch):
    """樹外 worktree 找到的正式庫 URL，三個 create_engine 入口都要拒絕，非正式 URL 照常可用。"""
    import sqlalchemy

    import src.storage as storage

    guard_globals = storage.create_engine.__globals__
    _main, _worktree, conftest_path = _out_of_tree_worktree(tmp_path)
    prod_urls = guard_globals["_find_prod_database_urls"](conftest_path)
    assert prod_urls == {"postgresql+psycopg://u:p@db.invalid/prod"}
    monkeypatch.setitem(guard_globals, "_PROD_DATABASE_URLS", prod_urls)

    for factory in (storage.create_engine, sqlalchemy.create_engine, sqlalchemy.engine.create_engine):
        with pytest.raises(RuntimeError, match="production STORAGE_DATABASE_URL"):
            factory(next(iter(prod_urls)))
        engine = factory("sqlite:///:memory:")
        try:
            with engine.connect() as connection:
                assert connection.exec_driver_sql("SELECT 1").scalar_one() == 1
        finally:
            engine.dispose()


def test_prod_url_guard_nearer_url_still_looks_up_main_checkout(tmp_path, monkeypatch):
    """最近的 .env 已有 URL，也必須透過 git 查主 checkout，避免提前回傳漏擋。"""
    import subprocess

    import src.storage as storage

    find = storage.create_engine.__globals__["_find_prod_database_urls"]
    _main, worktree, conftest_path = _out_of_tree_worktree(tmp_path)
    (worktree / ".env").write_text("STORAGE_DATABASE_URL=postgresql+psycopg://u:p@db.invalid/near\n", encoding="utf-8")

    real_run = subprocess.run
    calls = []

    def git_lookup(*args, **kwargs):
        calls.append(args[0])
        return real_run(*args, **kwargs)

    monkeypatch.setattr(subprocess, "run", git_lookup)
    assert find(conftest_path) == {
        "postgresql+psycopg://u:p@db.invalid/near",
        "postgresql+psycopg://u:p@db.invalid/prod",
    }
    assert calls == [["git", "-C", str(conftest_path.parent.resolve()), "rev-parse", "--git-common-dir"]]


def test_prod_url_guard_resolves_relative_git_common_dir(tmp_path, monkeypatch):
    """git 回相對路徑的 common dir 時，要相對於 worktree 的 tests 目錄解析。"""
    import subprocess

    import src.storage as storage

    find = storage.create_engine.__globals__["_find_prod_database_urls"]
    main, _worktree, conftest_path = _out_of_tree_worktree(tmp_path)
    real_run = subprocess.run

    def relative_common_dir(args, **kwargs):
        result = real_run(args, **kwargs)
        result.stdout = os.path.relpath(main / ".git", conftest_path.parent.resolve()) + "\n"
        return result

    monkeypatch.setattr(subprocess, "run", relative_common_dir)
    assert find(conftest_path) == {"postgresql+psycopg://u:p@db.invalid/prod"}


def test_prod_url_guard_ignores_cwd_repo(tmp_path, monkeypatch):
    """反向：行程 cwd 在帶 .env 的 checkout 時，也只查 start 所屬的 repo。"""
    import src.storage as storage

    find = storage.create_engine.__globals__["_find_prod_database_urls"]
    main, _worktree, _conftest = _out_of_tree_worktree(tmp_path)
    loose = tmp_path / "unrelated" / "tests" / "conftest.py"
    loose.parent.mkdir(parents=True)
    monkeypatch.chdir(main)

    assert find(loose) == set()


@pytest.mark.parametrize("failure", ["oserror", "timeout"])
def test_prod_url_guard_handles_git_lookup_failure(tmp_path, monkeypatch, failure):
    """git 不存在或逾時時回空集合，不讓 conftest import 失敗。"""
    import subprocess

    import src.storage as storage

    find = storage.create_engine.__globals__["_find_prod_database_urls"]
    _main, _worktree, conftest_path = _out_of_tree_worktree(tmp_path)

    def failed_git_lookup(*args, **kwargs):
        if failure == "oserror":
            raise FileNotFoundError("git unavailable")
        raise subprocess.TimeoutExpired(["git"], 10)

    monkeypatch.setattr(subprocess, "run", failed_git_lookup)
    assert find(conftest_path) == set()


def test_prod_url_guard_main_checkout_without_dotenv(tmp_path):
    """主 checkout 沒有 .env 時回空集合。"""
    import src.storage as storage

    find = storage.create_engine.__globals__["_find_prod_database_urls"]
    main, _worktree, conftest_path = _out_of_tree_worktree(tmp_path)
    (main / ".env").unlink()

    assert find(conftest_path) == set()


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
