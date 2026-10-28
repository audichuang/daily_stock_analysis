# -*- coding: utf-8 -*-
"""scripts/notify.py：主題對應 message_thread_id、缺憑證略過、空內文拒送。"""
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


def test_missing_topic_id_falls_back_to_group_default(sent, monkeypatch):
    monkeypatch.delenv("TELEGRAM_TOPIC_PLAN")
    assert _main(monkeypatch, "x", "--topic", "plan") == 0
    assert sent == [("-100", None, "x")]


def test_missing_credentials_skips_without_failing(sent, monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN")
    assert _main(monkeypatch, "x", "--topic", "system") == 0
    assert sent == []


def test_empty_body_is_refused_even_with_title(sent, monkeypatch):
    assert _main(monkeypatch, "  \n", "--topic", "morning", "--title", "盤前判讀") == 1
    assert sent == []


def test_send_failure_returns_nonzero(sent, monkeypatch):
    monkeypatch.setattr(TelegramSender, "send_to_telegram", lambda self, content, **kw: False)
    assert _main(monkeypatch, "x", "--topic", "system") == 1
