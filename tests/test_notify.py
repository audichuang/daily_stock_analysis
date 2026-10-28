# -*- coding: utf-8 -*-
"""scripts/notify.py：主題對應 message_thread_id；缺憑證、缺主題 id、空內文都拒送並回非零。"""
import io
import sys

import pytest

from scripts import notify
from src.notification_sender.telegram_sender import TelegramSender


@pytest.fixture
def sent(monkeypatch):
    calls = []

    def fake_send(self, content, **kwargs):
        calls.append((self._telegram_config["chat_id"], self._telegram_config["message_thread_id"], content))
        return True

    monkeypatch.setattr(TelegramSender, "send_to_telegram", fake_send)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "-100")
    for t in notify.TOPICS:
        monkeypatch.setenv(f"TELEGRAM_TOPIC_{t.upper()}", f"id-{t}")
    return calls


def _main(monkeypatch, body, *args):
    monkeypatch.setattr(sys, "stdin", io.StringIO(body))
    return notify.main(list(args))


def test_each_topic_goes_to_its_own_thread(sent, monkeypatch):
    for t in notify.TOPICS:
        assert _main(monkeypatch, "內文", "--topic", t, "--title", "標題") == 0
    assert [c[1] for c in sent] == [f"id-{t}" for t in notify.TOPICS]
    assert sent[0] == ("-100", "id-morning", "**標題**\n內文")


def test_missing_topic_id_is_refused_not_sent_to_general(sent, monkeypatch, capsys):
    # 掉進群組預設主題等於分流失效，還會印成功騙過排程的判準
    monkeypatch.delenv("TELEGRAM_TOPIC_PLAN")
    assert _main(monkeypatch, "x", "--topic", "plan") == 1
    assert sent == []
    out = capsys.readouterr()
    assert "已送出" not in out.out and "TELEGRAM_TOPIC_PLAN" in out.err


@pytest.mark.parametrize("key", ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"])
def test_missing_credentials_fail_loudly(sent, monkeypatch, capsys, key):
    monkeypatch.delenv(key)
    assert _main(monkeypatch, "x", "--topic", "system") == 1
    assert sent == []
    assert key in capsys.readouterr().err


def test_empty_body_is_refused_even_with_title(sent, monkeypatch):
    assert _main(monkeypatch, "  \n", "--topic", "morning", "--title", "盤前判讀") == 1
    assert sent == []


def test_send_failure_returns_nonzero_without_success_marker(sent, monkeypatch, capsys):
    monkeypatch.setattr(TelegramSender, "send_to_telegram", lambda self, content, **kw: False)
    assert _main(monkeypatch, "x", "--topic", "system") == 1
    assert "已送出" not in capsys.readouterr().out


def test_success_marker_only_after_delivery(sent, monkeypatch, capsys):
    assert _main(monkeypatch, "x", "--topic", "media") == 0
    assert capsys.readouterr().out.strip() == "[notify] media: 已送出"


def test_make_notify_passes_title_and_body_verbatim(tmp_path):
    # 走真的 Makefile：標題裡的引號、空白、$、反引號、% 都要原樣到 notify.py（不能變成 make／shell 語法）
    import os
    import shutil
    import subprocess
    from pathlib import Path

    if shutil.which("make") is None:
        pytest.skip("make not available")
    root = Path(__file__).resolve().parent.parent
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "doppler").write_text('#!/bin/sh\nwhile [ "$1" != "--" ]; do shift; done; shift; exec "$@"\n')
    (bindir / "uv").write_text(
        f'#!/bin/sh\n{{ printf "%s|" "$@"; printf "STDIN=%s" "$(cat)"; }} > "{tmp_path}/uv_args"\n')
    for f in bindir.iterdir():
        f.chmod(0o755)
    marker = tmp_path / "make_shell_ran"
    title = f'持股 "轉強 續抱" $NVDA $(shell touch {marker}) `id` 50%'
    r = subprocess.run(
        ["make", "-s", "-C", str(root), "notify", "TOPIC=plan", f"TITLE={title}"],
        input="內文 $HOME `x`", capture_output=True, text=True, timeout=30,
        env={**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}"},
    )
    assert r.returncode == 0, r.stderr
    args = (tmp_path / "uv_args").read_text(encoding="utf-8")
    assert args == f"run|python|scripts/notify.py|--topic|plan|--title|{title}|STDIN=內文 $HOME `x`"
    assert not marker.exists(), "標題裡的 $(shell …) 被 make 執行了"


def test_check_mode_reports_missing_topic_without_sending(sent, monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    assert notify.main(["--check", "--topic", "report"]) == 0
    monkeypatch.delenv("TELEGRAM_TOPIC_REPORT")
    assert notify.main(["--check", "--topic", "report"]) == 1
    assert "TELEGRAM_TOPIC_REPORT" in capsys.readouterr().err
    assert sent == []


def test_every_main_py_launch_checks_its_topic_first():
    # main.py 自己不認主題 id：缺了就落到群組預設主題。所有帶 TELEGRAM_MESSAGE_THREAD_ID 啟動 main.py 的入口
    # 都要先用 notify.py --check 擋同一個主題
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    launches = []
    for f in ("Makefile", "scripts/daily_report.sh"):
        for line in (root / f).read_text(encoding="utf-8").splitlines():
            if "TELEGRAM_MESSAGE_THREAD_ID=" in line and "main.py" in line:
                launches.append((f, line))
    assert len(launches) == 3
    for f, line in launches:
        m = re.search(r'notify\.py --check --topic (\w+) && TELEGRAM_MESSAGE_THREAD_ID="\$+TELEGRAM_TOPIC_(\w+)"', line)
        assert m and m.group(1).upper() == m.group(2), f"{f}: {line.strip()}"
