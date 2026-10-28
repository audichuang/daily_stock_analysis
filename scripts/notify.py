#!/usr/bin/env python3
"""推一則通知到 Telegram 群組的指定主題（topic）；本 fork 所有排程與腳本的推播都走這裡。

用法（內文走 stdin，避免多行中文經 argv 被 shell 拆壞，也不讓內容出現在 ps）：
    printf '%s' "$BODY" | doppler run -p shioaji -c dev -- uv run python scripts/notify.py --topic system --title "標題"

TELEGRAM_BOT_TOKEN、TELEGRAM_CHAT_ID、TELEGRAM_TOPIC_<主題> 由 Doppler 注入。缺 token／chat id 時印一行略過、
回 0（與舊 Bark 路徑相同：沒注入就不推）；送出失敗回 1。內文是標準 Markdown，TelegramSender 負責轉格式、
分段（4096 UTF-16）、重試與 Markdown 被拒時退回純文字。

主題 → 用途（在群組裡各自可靜音）：
    morning  盤前判讀與回驗      intraday 盤中提醒（持股觸發、價格警報、記憶體背離）
    report   每日報告            plan     明日持股計畫
    media    財經媒體點名        system   失敗、卡鎖、上游同步等系統通知
"""
import argparse
import os
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

TOPICS = ("morning", "intraday", "report", "plan", "media", "system")


def send(body: str, topic: str, title: str = "") -> bool | None:
    """送出成功 True、失敗 False；沒設定 token／chat id 回 None（略過）。"""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not (token and chat_id):
        print("[notify] 未注入 TELEGRAM_BOT_TOKEN／TELEGRAM_CHAT_ID，略過推播", flush=True)
        return None
    thread_id = os.environ.get(f"TELEGRAM_TOPIC_{topic.upper()}", "").strip() or None
    if thread_id is None:
        print(f"[notify] 未設定 TELEGRAM_TOPIC_{topic.upper()}，改發到群組預設主題", flush=True)
    text = f"**{title}**\n{body}" if title else body

    from src.notification_sender.telegram_sender import TelegramSender

    sender = TelegramSender(SimpleNamespace(
        telegram_bot_token=token, telegram_chat_id=chat_id, telegram_message_thread_id=thread_id,
    ))
    return sender.send_to_telegram(text)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="推一則通知到 Telegram 群組的指定主題（內文從 stdin 讀）")
    ap.add_argument("--topic", required=True, choices=TOPICS)
    ap.add_argument("--title", default="")
    a = ap.parse_args(argv)
    body = sys.stdin.read().strip()
    if not body:
        # 排程的 Claude 分兩次 Bash 組內容時變數會消失，送出去只剩標題（2026-10-21 Bark 收到空訊息）
        print("[notify] 內文是空的，不送", file=sys.stderr)
        return 1
    ok = send(body, a.topic, a.title)
    if ok is not None:
        print(f"[notify] {a.topic}: {'已送出' if ok else '送出失敗'}", flush=True)
    return 1 if ok is False else 0


if __name__ == "__main__":
    sys.exit(main())
