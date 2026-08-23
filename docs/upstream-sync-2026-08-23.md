# 上游同步記錄：v3.29 → v3.30（2026-08-23）

## 範圍

- 基線：`ed848da6`（2026-08-04，上次同步終點）→ `b4770225`（2026-08-22）
- 22 個上游 commit，含 v3.30.0；104 檔，+9,272 / −510
- 合併方式：`git merge upstream/main`（3 檔文字衝突）
- 分支：`merge/upstream-v3.30`

## 裁決原則

同前次：以上游為 base，重放 fork 的台股（`tw`）／`zh-TW` 增量，並把**找靜默降級**當成主要工作
（見 `docs/upstream-sync-2026-08-05.md`）。本次的做法是：合併後把上游新增的每個共用常數／集合
抓出來，逐個問「它涵蓋 `tw` 嗎？涵蓋 `zh-TW` 嗎？」

## 三個衝突的裁決

| 檔案 | 衝突內容 | 裁決 |
| --- | --- | --- |
| `src/analyzer.py` | 上游在 `GeminiAnalyzer` 上新增 provider/model 身分解析（#2241），與 fork 已把 LLM transport 下移到 `src/llm/client.py` 的重構相撞 | 取 fork 的 `LLMClient` re-export；上游**新增**的 4 個身分解析方法照收，其餘（`_normalize_usage` / `_extract_*` / `_call_litellm` 等已下移者）丟棄 |
| `src/analyzer.py`（空回應文案） | 上游 `raise ValueError("LLM returned empty response")` vs fork 帶 `finish_reason` / `max_tokens` 的診斷文案 | 保留 fork 文案（推理模型燒光預算的症狀辨識，見 AGENTS §10），但採用上游的 `actual_model` 回傳 |
| `src/market_analyzer.py` | 上游加 `GenerationResult` import vs fork 的 `trading_calendar` import | 兩者聯集 |
| `src/notification.py` | fork 曾以「零 caller 死代碼」刪除 `generate_wechat_summary`，上游本次修改它 | 恢復上游版——上游新測試 `test_notification_empty_news_disclosure.py` 讓它重新有 caller（同 `tool_surface.py` 前例） |

## 移植到 `src/llm/client.py` 的上游改動

`_call_litellm` 與 `_AllModelsFailedError` 住在 fork 的 `src/llm/client.py`，上游對它們的改動必須手動移植，
否則 auto-merge 進 `analyzer.py` 的呼叫端會在執行期炸開：

- `_AllModelsFailedError.__init__` 補 `last_provider`（`_call_litellm_impl` 的 raise 與 `generate_text_with_metadata` 的讀取都依賴它）
- `_call_litellm` 補 `return_generation_result` 參數與 `Union[..., GenerationResult]` 回傳型別——**沒有這個，大盤複盤的 `generate_text_with_metadata` 是即時 TypeError**
- `_call_litellm` 的 fallback 分支補 `_promote_error_identity(fallback_exc.details)` 提升路由診斷
- `_promote_error_identity` 放在 `client.py`（緊鄰唯一呼叫者），其餘 3 個身分解析方法留在 `analyzer.py`（緊鄰 `_call_litellm_impl`）

## 找到的靜默降級（1 處，已修）

**`src/services/empty_news.py` 的語言集合不含 `zh-TW`。** 上游新模組（#2229，新聞檢索為空時如實標註）
自帶硬性守門：

```python
if set(_DISCLOSURES) != set(SUPPORTED_REPORT_LANGUAGES):
    raise RuntimeError(...)
```

fork 的 `SUPPORTED_REPORT_LANGUAGES` 是 `("zh", "zh-TW", "en", "ko")`，因此這個模組在本 fork
**import 就炸**。這次是 fail-loud 而非靜默，但形狀與前次的 84 鍵 zh-TW 缺口完全相同。
已補 zh-TW 兩條文案，並在 `tests/test_notification_empty_news_disclosure.py` 的 `EXPECTED` 補上對應字面
（該測試斷言 `set(SUPPORTED_REPORT_LANGUAGES) == set(EXPECTED)`，且逐 renderer／逐 template 驗證文案真的輸出）。

## 查過但沒問題的項目

- `MARKET_REVIEW_REGION_ORDER` / `MARKET_LIGHT_REGIONS` 合併後仍含 `tw`
- `stock_daily.canonical_id`（#2251）：`2330.TW` / `6488.TWO` / `00631L.TW` / `0050.TW` 都原樣保留為 canonical_id，無後綴剝除或 6 位 A 股假設
- `_market_review_summary` 淨化器（#2242）：純 markdown regex，不比對市場名或標題語言
- `systemConfigI18n.ts`（#2226）：只改一條既有描述文字，無新鍵，無 zh-TW 對齊缺口

## 已知的既有缺口（非本次引入，未修）

`src/share_image.py` 的 `_MARKET_RE` / `_MARKET_SCOPE_RE` / 區域清單只認 `大盘复盘`（簡體）與
`cn|hk|us|jp|kr`，不認繁體「大盤複盤」與 `tw`。合併前的 `main` 已是如此，本次合併沒有讓它變差，
故不在本次改動範圍內。
