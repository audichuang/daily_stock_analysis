# -*- coding: utf-8 -*-
"""
Unit tests for the Sender protocol + NotificationService composition
(refactor: introduce Sender protocol and composition for notification
channels).

Two layers are covered:

1. Each of the 14 channel senders implements the ``Sender`` protocol
   (``is_configured()`` + ``send(msg)``) and its ``is_configured()`` agrees
   with ``NotificationService.detect_configured_channels`` for the same
   config.
2. ``NotificationService._send_to_static_channel`` routes correctly through
   ``self._senders`` (image-vs-text selection, email receiver resolution,
   feishu file_path condition, unknown-channel skip) by injecting fake
   sender objects into the registry.
"""
import os
import sys
import unittest
from typing import Any, Dict, List, Optional, Tuple
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

for optional_module in ("litellm", "json_repair"):
    try:
        __import__(optional_module)
    except ModuleNotFoundError:
        sys.modules[optional_module] = mock.MagicMock()

from src.config import Config
from src.notification import NotificationChannel, NotificationService
from src.notification_noise import reset_notification_noise_state
from src.notification_sender import (
    AstrbotSender,
    CustomWebhookSender,
    DingtalkSender,
    DiscordSender,
    EmailSender,
    FeishuSender,
    GotifySender,
    NtfySender,
    OutboundMessage,
    PushoverSender,
    PushplusSender,
    Sender,
    Serverchan3Sender,
    SlackSender,
    TelegramSender,
    WechatSender,
    WECHAT_IMAGE_MAX_BYTES,
)


def _make_config(**overrides) -> Config:
    return Config(stock_list=[], **overrides)


class _RecordingSender:
    """Generic Sender-protocol test double.

    Records every call made to it (including the legacy per-channel method
    names ``NotificationService``'s compat delegators forward to, e.g.
    ``send_to_wechat`` / ``_send_wechat_image``) so a single fake can stand
    in for any channel injected into ``NotificationService._senders``.
    """

    def __init__(self, *, configured: bool = True, result: Any = True, **attrs: Any):
        self.configured = configured
        self.result = result
        self.method_results: Dict[str, Any] = {}
        self.calls: List[Tuple[str, tuple, dict]] = []
        for key, value in attrs.items():
            setattr(self, key, value)

    def is_configured(self) -> bool:
        return self.configured

    def send(self, msg: OutboundMessage) -> bool:
        self.calls.append(("send", (msg,), {}))
        return self.result

    def __getattr__(self, name: str):
        def _record(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return self.method_results.get(name, self.result)
        return _record


class TestSenderProtocolConformance(unittest.TestCase):
    """Every sender implements is_configured()/send(); is_configured() agrees
    with detect_configured_channels for representative configs."""

    def test_all_senders_expose_protocol_methods(self):
        config = _make_config()
        senders = [
            AstrbotSender(config), CustomWebhookSender(config), DingtalkSender(config),
            DiscordSender(config), EmailSender(config), FeishuSender(config),
            GotifySender(config), NtfySender(config), PushoverSender(config),
            PushplusSender(config), Serverchan3Sender(config), SlackSender(config),
            TelegramSender(config), WechatSender(config),
        ]
        for sender in senders:
            self.assertTrue(callable(getattr(sender, "is_configured", None)))
            self.assertTrue(callable(getattr(sender, "send", None)))
            self.assertFalse(sender.is_configured())

    def _assert_is_configured_matches_detection(self, channel: NotificationChannel, sender: Sender, config: Config):
        detected = NotificationService.detect_configured_channels(config)
        self.assertEqual(
            sender.is_configured(),
            channel in detected,
            f"{channel} is_configured() disagrees with detect_configured_channels",
        )

    def test_wechat_is_configured_matches_detection(self):
        for cfg in (_make_config(), _make_config(wechat_webhook_url="https://wechat.example/hook")):
            self._assert_is_configured_matches_detection(NotificationChannel.WECHAT, WechatSender(cfg), cfg)

    def test_dingtalk_is_configured_matches_detection(self):
        for cfg in (_make_config(), _make_config(dingtalk_webhook_url="https://dingtalk.example/hook")):
            self._assert_is_configured_matches_detection(NotificationChannel.DINGTALK, DingtalkSender(cfg), cfg)

    def test_feishu_is_configured_matches_detection_webhook(self):
        for cfg in (_make_config(), _make_config(feishu_webhook_url="https://feishu.example/hook")):
            self._assert_is_configured_matches_detection(NotificationChannel.FEISHU, FeishuSender(cfg), cfg)

    def test_feishu_is_configured_matches_detection_app_bot(self):
        cfg = _make_config(
            feishu_app_id="app-id", feishu_app_secret="app-secret", feishu_chat_id="chat-id",
        )
        self._assert_is_configured_matches_detection(NotificationChannel.FEISHU, FeishuSender(cfg), cfg)
        # Partial App Bot triad must not count as configured, matching detect_configured_channels.
        partial_cfg = _make_config(feishu_app_id="app-id")
        self._assert_is_configured_matches_detection(NotificationChannel.FEISHU, FeishuSender(partial_cfg), partial_cfg)

    def test_telegram_is_configured_matches_detection(self):
        for cfg in (
            _make_config(),
            _make_config(telegram_bot_token="tok"),
            _make_config(telegram_bot_token="tok", telegram_chat_id="chat"),
        ):
            self._assert_is_configured_matches_detection(NotificationChannel.TELEGRAM, TelegramSender(cfg), cfg)

    def test_email_is_configured_matches_detection(self):
        for cfg in (
            _make_config(),
            _make_config(email_sender="a@example.com", email_password="pw"),
        ):
            self._assert_is_configured_matches_detection(NotificationChannel.EMAIL, EmailSender(cfg), cfg)

    def test_pushover_is_configured_matches_detection(self):
        for cfg in (
            _make_config(),
            _make_config(pushover_user_key="u", pushover_api_token="t"),
        ):
            self._assert_is_configured_matches_detection(NotificationChannel.PUSHOVER, PushoverSender(cfg), cfg)

    def test_ntfy_is_configured_matches_detection(self):
        for cfg in (
            _make_config(),
            _make_config(ntfy_url="https://ntfy.sh/my-topic"),
            # URL with no topic path segment: NtfySender.is_configured()
            # used to just check the URL was non-empty (True) while
            # detect_configured_channels requires resolve_ntfy_endpoint() to
            # yield a topic (False) — a real "advertised but fails" gap,
            # now closed by resolving the full endpoint in is_configured().
            _make_config(ntfy_url="https://ntfy.sh"),
        ):
            self._assert_is_configured_matches_detection(NotificationChannel.NTFY, NtfySender(cfg), cfg)

    def test_gotify_is_configured_matches_detection(self):
        for cfg in (
            _make_config(),
            _make_config(gotify_url="https://gotify.example", gotify_token="tok"),
            # URL already pointing at /message: GotifySender.is_configured()
            # used to just check url+token were non-empty (True) while
            # detect_configured_channels requires resolve_gotify_message_endpoint()
            # to succeed, which it doesn't for an already-/message URL
            # (False) — now closed by resolving the endpoint in is_configured().
            _make_config(gotify_url="https://gotify.example/message", gotify_token="tok"),
        ):
            self._assert_is_configured_matches_detection(NotificationChannel.GOTIFY, GotifySender(cfg), cfg)

    def test_pushplus_is_configured_matches_detection(self):
        for cfg in (_make_config(), _make_config(pushplus_token="tok")):
            self._assert_is_configured_matches_detection(NotificationChannel.PUSHPLUS, PushplusSender(cfg), cfg)

    def test_serverchan3_is_configured_matches_detection(self):
        for cfg in (_make_config(), _make_config(serverchan3_sendkey="key")):
            self._assert_is_configured_matches_detection(NotificationChannel.SERVERCHAN3, Serverchan3Sender(cfg), cfg)

    def test_custom_webhook_is_configured_matches_detection(self):
        for cfg in (_make_config(), _make_config(custom_webhook_urls=["https://example.com/webhook"])):
            self._assert_is_configured_matches_detection(NotificationChannel.CUSTOM, CustomWebhookSender(cfg), cfg)

    def test_discord_is_configured_matches_detection(self):
        for cfg in (
            _make_config(),
            _make_config(discord_webhook_url="https://discord.com/api/webhooks/1/abc"),
            _make_config(discord_bot_token="tok", discord_main_channel_id="123"),
        ):
            self._assert_is_configured_matches_detection(NotificationChannel.DISCORD, DiscordSender(cfg), cfg)

    def test_slack_is_configured_matches_detection(self):
        for cfg in (
            _make_config(),
            _make_config(slack_webhook_url="https://hooks.slack.com/services/x"),
            _make_config(slack_bot_token="tok", slack_channel_id="C123"),
        ):
            self._assert_is_configured_matches_detection(NotificationChannel.SLACK, SlackSender(cfg), cfg)

    def test_astrbot_is_configured_matches_detection(self):
        for cfg in (_make_config(), _make_config(astrbot_url="https://astrbot.example")):
            self._assert_is_configured_matches_detection(NotificationChannel.ASTRBOT, AstrbotSender(cfg), cfg)


class TestSenderSendVariantSelection(unittest.TestCase):
    """Each sender's send(msg) picks the right transport variant."""

    def test_wechat_send_uses_image_when_within_limit(self):
        sender = WechatSender(_make_config(wechat_webhook_url="https://wechat.example/hook"))
        with mock.patch.object(sender, "_send_wechat_image", return_value=True) as mock_image, \
             mock.patch.object(sender, "send_to_wechat", return_value=True) as mock_text:
            ok = sender.send(OutboundMessage(text="hi", image_bytes=b"x" * 10))
        self.assertTrue(ok)
        mock_image.assert_called_once_with(b"x" * 10)
        mock_text.assert_not_called()

    def test_wechat_send_falls_back_to_text_when_image_over_limit(self):
        sender = WechatSender(_make_config(wechat_webhook_url="https://wechat.example/hook"))
        oversized = b"x" * (WECHAT_IMAGE_MAX_BYTES + 1)
        with mock.patch.object(sender, "_send_wechat_image", return_value=True) as mock_image, \
             mock.patch.object(sender, "send_to_wechat", return_value=True) as mock_text:
            ok = sender.send(OutboundMessage(text="hi", image_bytes=oversized))
        self.assertTrue(ok)
        mock_image.assert_not_called()
        mock_text.assert_called_once_with("hi")

    def test_wechat_send_uses_text_when_no_image(self):
        sender = WechatSender(_make_config(wechat_webhook_url="https://wechat.example/hook"))
        with mock.patch.object(sender, "send_to_wechat", return_value=True) as mock_text:
            sender.send(OutboundMessage(text="hi"))
        mock_text.assert_called_once_with("hi")

    def test_telegram_send_uses_photo_when_image_present(self):
        sender = TelegramSender(_make_config(telegram_bot_token="t", telegram_chat_id="c"))
        with mock.patch.object(sender, "_send_telegram_photo", return_value=True) as mock_photo, \
             mock.patch.object(sender, "send_to_telegram", return_value=True) as mock_text:
            sender.send(OutboundMessage(text="hi", image_bytes=b"png"))
        mock_photo.assert_called_once_with(b"png")
        mock_text.assert_not_called()

    def test_telegram_send_uses_text_when_no_image(self):
        sender = TelegramSender(_make_config(telegram_bot_token="t", telegram_chat_id="c"))
        with mock.patch.object(sender, "send_to_telegram", return_value=True) as mock_text:
            sender.send(OutboundMessage(text="hi"))
        mock_text.assert_called_once_with("hi")

    def test_feishu_send_uses_file_when_file_path_present(self):
        sender = FeishuSender(_make_config(feishu_webhook_url="https://feishu.example/hook"))
        with mock.patch.object(sender, "send_feishu_file", return_value=True) as mock_file, \
             mock.patch.object(sender, "send_to_feishu", return_value=True) as mock_text:
            sender.send(OutboundMessage(text="hi", file_path="/tmp/report.md"))
        mock_file.assert_called_once_with("/tmp/report.md")
        mock_text.assert_not_called()

    def test_feishu_send_uses_text_when_no_file_path(self):
        sender = FeishuSender(_make_config(feishu_webhook_url="https://feishu.example/hook"))
        with mock.patch.object(sender, "send_to_feishu", return_value=True) as mock_text:
            sender.send(OutboundMessage(text="hi"))
        mock_text.assert_called_once_with("hi")

    def test_email_send_uses_inline_image_with_receivers(self):
        sender = EmailSender(_make_config(email_sender="a@example.com", email_password="pw"))
        with mock.patch.object(sender, "_send_email_with_inline_image", return_value=True) as mock_image, \
             mock.patch.object(sender, "send_to_email", return_value=True) as mock_text:
            sender.send(OutboundMessage(text="hi", image_bytes=b"png", email_receivers=["a@x.com"]))
        mock_image.assert_called_once_with(b"png", receivers=["a@x.com"])
        mock_text.assert_not_called()

    def test_email_send_uses_text_with_receivers_when_no_image(self):
        sender = EmailSender(_make_config(email_sender="a@example.com", email_password="pw"))
        with mock.patch.object(sender, "send_to_email", return_value=True) as mock_text:
            sender.send(OutboundMessage(text="hi", email_receivers=["a@x.com"]))
        mock_text.assert_called_once_with("hi", receivers=["a@x.com"])

    def test_slack_send_uses_image_with_fallback(self):
        sender = SlackSender(_make_config(slack_webhook_url="https://hooks.slack.com/services/x"))
        with mock.patch.object(sender, "_send_slack_image", return_value=True) as mock_image, \
             mock.patch.object(sender, "send_to_slack", return_value=True) as mock_text:
            sender.send(OutboundMessage(text="hi", image_bytes=b"png"))
        mock_image.assert_called_once_with(b"png", fallback_content="hi")
        mock_text.assert_not_called()

    def test_custom_webhook_send_uses_image_with_fallback(self):
        sender = CustomWebhookSender(_make_config(custom_webhook_urls=["https://example.com/webhook"]))
        with mock.patch.object(sender, "_send_custom_webhook_image", return_value=True) as mock_image, \
             mock.patch.object(sender, "send_to_custom", return_value=True) as mock_text:
            sender.send(OutboundMessage(text="hi", image_bytes=b"png"))
        mock_image.assert_called_once_with(b"png", fallback_content="hi")
        mock_text.assert_not_called()

    def test_dingtalk_send_always_text(self):
        sender = DingtalkSender(_make_config(dingtalk_webhook_url="https://dingtalk.example/hook"))
        with mock.patch.object(sender, "send_to_dingtalk", return_value=True) as mock_text:
            sender.send(OutboundMessage(text="hi", image_bytes=b"png"))
        mock_text.assert_called_once_with("hi")

    def test_text_only_senders_ignore_image_bytes(self):
        cases = [
            (PushoverSender(_make_config(pushover_user_key="u", pushover_api_token="t")), "send_to_pushover"),
            (NtfySender(_make_config(ntfy_url="https://ntfy.sh/topic")), "send_to_ntfy"),
            (GotifySender(_make_config(gotify_url="https://gotify.example", gotify_token="t")), "send_to_gotify"),
            (PushplusSender(_make_config(pushplus_token="t")), "send_to_pushplus"),
            (Serverchan3Sender(_make_config(serverchan3_sendkey="k")), "send_to_serverchan3"),
            (AstrbotSender(_make_config(astrbot_url="https://astrbot.example")), "send_to_astrbot"),
            (DiscordSender(_make_config(discord_webhook_url="https://discord.com/api/webhooks/1/a")), "send_to_discord"),
        ]
        for sender, method_name in cases:
            with mock.patch.object(sender, method_name, return_value=True) as mock_text:
                sender.send(OutboundMessage(text="hi", image_bytes=b"png"))
            mock_text.assert_called_once_with("hi")


class TestSendToStaticChannelInjectedRegistry(unittest.TestCase):
    """NotificationService._send_to_static_channel routed through fake senders
    injected into self._senders (fake registry): it resolves image-channel
    membership, email receiver groups, and feishu report file staging once,
    then makes exactly one ``sender.send(OutboundMessage(...))`` call — the
    legacy per-channel methods (``_send_wechat_image``, ``send_to_email``,
    etc.) are never called directly by the dispatcher anymore, only by
    each Sender's own ``send()``."""

    def setUp(self):
        reset_notification_noise_state()

    @mock.patch("src.notification.get_config")
    def _build_service(self, mock_get_config, **config_overrides):
        mock_get_config.return_value = _make_config(**config_overrides)
        return NotificationService()

    @staticmethod
    def _sent_message(fake: _RecordingSender) -> OutboundMessage:
        send_calls = [c for c in fake.calls if c[0] == "send"]
        assert len(send_calls) == 1, f"expected exactly one send() call, got {fake.calls}"
        (msg,) = send_calls[0][1]
        return msg

    def test_image_channel_membership_controls_image_bytes(self):
        service = self._build_service()
        fake = _RecordingSender()
        service._senders[NotificationChannel.WECHAT] = fake
        service._markdown_to_image_channels = {"wechat"}

        ok = service._send_to_static_channel(
            NotificationChannel.WECHAT, "hello",
            image_bytes=b"x" * 10, email_stock_codes=None, email_send_to_all=False,
        )

        self.assertTrue(ok)
        msg = self._sent_message(fake)
        self.assertEqual(msg.text, "hello")
        self.assertEqual(msg.image_bytes, b"x" * 10)
        self.assertIsNone(msg.file_path)
        self.assertIsNone(msg.email_receivers)

    def test_channel_not_in_image_set_gets_text_even_with_image_bytes(self):
        service = self._build_service()
        fake = _RecordingSender()
        service._senders[NotificationChannel.WECHAT] = fake
        service._markdown_to_image_channels = set()  # wechat not opted into images

        ok = service._send_to_static_channel(
            NotificationChannel.WECHAT, "hello",
            image_bytes=b"x" * 10, email_stock_codes=None, email_send_to_all=False,
        )

        self.assertTrue(ok)
        msg = self._sent_message(fake)
        self.assertEqual(msg.text, "hello")
        self.assertIsNone(msg.image_bytes)

    def test_email_send_to_all_resolves_group_receivers(self):
        service = self._build_service()
        fake = _RecordingSender(_stock_email_groups=[(["000001"], ["a@x.com"])])
        fake.method_results["get_all_email_receivers"] = ["a@x.com", "default@x.com"]
        service._senders[NotificationChannel.EMAIL] = fake

        ok = service._send_to_static_channel(
            NotificationChannel.EMAIL, "hello",
            image_bytes=None, email_stock_codes=None, email_send_to_all=True,
        )

        self.assertTrue(ok)
        call_names = [c[0] for c in fake.calls]
        self.assertIn("get_all_email_receivers", call_names)
        msg = self._sent_message(fake)
        self.assertEqual(msg.email_receivers, ["a@x.com", "default@x.com"])

    def test_email_stock_codes_resolve_group_receivers(self):
        service = self._build_service()
        fake = _RecordingSender(_stock_email_groups=[(["000001"], ["a@x.com"])])
        fake.method_results["get_receivers_for_stocks"] = ["a@x.com"]
        service._senders[NotificationChannel.EMAIL] = fake

        service._send_to_static_channel(
            NotificationChannel.EMAIL, "hello",
            image_bytes=None, email_stock_codes=["000001"], email_send_to_all=False,
        )

        msg = self._sent_message(fake)
        self.assertEqual(msg.email_receivers, ["a@x.com"])

    def test_email_without_groups_configured_passes_none_receivers(self):
        service = self._build_service()
        fake = _RecordingSender(_stock_email_groups=[])
        service._senders[NotificationChannel.EMAIL] = fake

        service._send_to_static_channel(
            NotificationChannel.EMAIL, "hello",
            image_bytes=None, email_stock_codes=["000001"], email_send_to_all=False,
        )

        msg = self._sent_message(fake)
        self.assertIsNone(msg.email_receivers)

    def test_feishu_file_path_staged_when_send_as_file_and_report_route(self):
        service = self._build_service()
        fake = _RecordingSender(_feishu_send_as_file=True)
        service._senders[NotificationChannel.FEISHU] = fake

        with mock.patch.object(service, "save_report_to_file", return_value="/tmp/report.md") as mock_save:
            service._send_to_static_channel(
                NotificationChannel.FEISHU, "hello",
                image_bytes=None, email_stock_codes=None, email_send_to_all=False,
                route_type="report",
            )

        mock_save.assert_called_once()
        msg = self._sent_message(fake)
        self.assertEqual(msg.file_path, "/tmp/report.md")

    def test_feishu_skips_file_path_when_route_is_not_report(self):
        service = self._build_service()
        fake = _RecordingSender(_feishu_send_as_file=True)
        service._senders[NotificationChannel.FEISHU] = fake

        service._send_to_static_channel(
            NotificationChannel.FEISHU, "hello",
            image_bytes=None, email_stock_codes=None, email_send_to_all=False,
            route_type="alert",
        )

        msg = self._sent_message(fake)
        self.assertIsNone(msg.file_path)

    def test_feishu_skips_file_path_when_send_as_file_disabled(self):
        service = self._build_service()
        fake = _RecordingSender(_feishu_send_as_file=False)
        service._senders[NotificationChannel.FEISHU] = fake

        service._send_to_static_channel(
            NotificationChannel.FEISHU, "hello",
            image_bytes=None, email_stock_codes=None, email_send_to_all=False,
            route_type="report",
        )

        msg = self._sent_message(fake)
        self.assertIsNone(msg.file_path)

    def test_unknown_channel_is_skipped(self):
        service = self._build_service()
        ok = service._send_to_static_channel(
            NotificationChannel.UNKNOWN, "hello",
            image_bytes=None, email_stock_codes=None, email_send_to_all=False,
        )
        self.assertFalse(ok)


class TestMixinAttributeDelegation(unittest.TestCase):
    """pipeline._send_notifications 直接读取的原 mixin 属性必须仍可解析。

    回归保护：移除 mixin 继承后，pipeline 聚合通知路径仍读取
    notifier._feishu_send_as_file / _slack_bot_token / _slack_channel_id
    （src/core/pipeline.py 的 Feishu 存档条件与 Slack 图片上传判断）。
    """

    @mock.patch("src.notification.get_config")
    def _build_service(self, mock_get_config, **config_overrides):
        mock_get_config.return_value = _make_config(**config_overrides)
        return NotificationService()

    def test_feishu_send_as_file_delegates_to_sender(self):
        service = self._build_service(
            feishu_webhook_url="https://open.feishu.cn/hook/x",
            feishu_send_as_file=True,
        )
        self.assertTrue(service._feishu_send_as_file)

        service_off = self._build_service(
            feishu_webhook_url="https://open.feishu.cn/hook/x",
        )
        self.assertFalse(service_off._feishu_send_as_file)

    def test_slack_bot_attrs_delegate_to_sender(self):
        service = self._build_service(
            slack_bot_token="xoxb-token",
            slack_channel_id="C123",
        )
        self.assertEqual(service._slack_bot_token, "xoxb-token")
        self.assertEqual(service._slack_channel_id, "C123")

        service_off = self._build_service()
        self.assertIsNone(service_off._slack_bot_token)
        self.assertIsNone(service_off._slack_channel_id)


if __name__ == "__main__":
    unittest.main()
