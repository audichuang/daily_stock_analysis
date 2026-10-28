#!/usr/bin/env python3
"""推一則通知到 Telegram 群組的指定主題（topic）；本 fork 所有排程與腳本的推播都走這裡。

用法（內文走 stdin，避免多行中文經 argv 被 shell 拆壞，也不讓內容出現在 ps）：
    printf '%s' "$BODY" | doppler run -p shioaji -c dev -- uv run python scripts/notify.py --topic system --title "標題"

TELEGRAM_BOT_TOKEN、TELEGRAM_CHAT_ID、TELEGRAM_TOPIC_<主題> 由 Doppler 注入。只有送到指定主題才印
`[notify] <主題>: 已送出` 並回 0；缺憑證、缺該主題的 id（否則會掉進群組預設主題，分流就失效）、空內文或送出失敗
一律回 1，原因印在 stderr。內文是標準 Markdown，TelegramSender 負責轉格式、分段（4096 UTF-16）、重試與
Markdown 被拒時退回純文字。

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


def missing_config(topic: str) -> list[str]:
    """送到這個主題還缺哪些環境變數（空串列＝齊全）。"""
    keys = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", f"TELEGRAM_TOPIC_{topic.upper()}")
    return [k for k in keys if not os.environ.get(k, "").strip()]


def send(body: str, topic: str, title: str = "") -> bool:
    """送到指定主題才回 True；缺設定或送出失敗回 False，原因印在 stderr。"""
    missing = missing_config(topic)
    if missing:
        print(f"[notify] 未注入 {'、'.join(missing)}，不送", file=sys.stderr, flush=True)
        return False
    token = os.environ["TELEGRAM_BOT_TOKEN"].strip()
    chat_id = os.environ["TELEGRAM_CHAT_ID"].strip()
    thread_id = os.environ[f"TELEGRAM_TOPIC_{topic.upper()}"].strip()
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
    ap.add_argument("--check", action="store_true",
                    help="只檢查該主題的憑證與 id 是否齊全（不讀 stdin、不送）；main.py 入口在啟動前用它擋掉會落到預設主題的情況")
    a = ap.parse_args(argv)
    if a.check:
        missing = missing_config(a.topic)
        if missing:
            print(f"[notify] 未注入 {'、'.join(missing)}：{a.topic} 主題的推播會失效，停止", file=sys.stderr, flush=True)
            return 1
        return 0
    body = sys.stdin.read().strip()
    if not body:
        # 排程的 Claude 分兩次 Bash 組內容時變數會消失，送出去只剩標題（2026-10-21 Bark 收到空訊息）
        print("[notify] 內文是空的，不送", file=sys.stderr)
        return 1
    if send(body, a.topic, a.title):
        print(f"[notify] {a.topic}: 已送出", flush=True)
        return 0
    print(f"[notify] {a.topic}: 送出失敗", file=sys.stderr, flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())
