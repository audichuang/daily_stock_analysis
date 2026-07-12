# -*- coding: utf-8 -*-
"""Shared Sender protocol and outbound message contract for notification channels.

Every channel sender (the sibling ``*_sender.py`` modules) implements this
Protocol so ``NotificationService`` can hold them in a single composed
registry (``self._senders``) instead of inheriting from 14 mixins.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Protocol


@dataclass
class OutboundMessage:
    """A single notification payload, pre-resolved by the dispatcher.

    ``NotificationService`` decides image conversion, email group routing,
    and report-file staging once per send; each Sender only looks at these
    fields to decide which of its own transport variants to use.
    """

    text: str
    image_bytes: Optional[bytes] = None   # dispatcher 已轉換好；sender 自行決定用圖或 fallback 文字
    file_path: Optional[str] = None       # 報告存檔路徑（feishu 用；dispatcher 先存好）
    email_receivers: Optional[List[str]] = None  # dispatcher 已解析分組


class Sender(Protocol):
    """Common shape every notification channel sender implements."""

    def is_configured(self) -> bool: ...

    def send(self, msg: OutboundMessage) -> bool: ...
    # ponytail: bool 契约与现状等价；若日后需要 per-sender 错误诊断，升级成结构化 SendOutcome
