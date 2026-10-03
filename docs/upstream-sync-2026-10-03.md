# 上游同步记录 2026-10-03（post-v3.32.0 第三轮）

## 基线

| | |
| --- | --- |
| 上一次同步基线 | `d3fee51a`（`docs/upstream-sync-2026-09-29.md` 收的最后一个 commit） |
| 本次上游 HEAD | `be148f39`（无新 tag） |
| 吸收 commit 数 | 6（全部） |
| 合并方式 | 分支 `chore/upstream-sync-2026-10-03`（自 `main` `256a44d9`）`git merge upstream/main --no-ff` |
| 冲突档 | 1：`src/analyzer.py` 22 处（`git merge-tree` 干跑与实际合并一致） |

## 吸收的上游改动

| commit | 内容 | 对本 fork 的意义 |
| --- | --- | --- |
| `4e29abc6` #2368 | `REPORT_LANGUAGE=en`（含复用英文骨架的 `ko`）时个股 system／user prompt 全面改用英文模板 | 与 fork 的 zh-TW 繁体 prompt 在同一批位置冲突，见「冲突裁决」 |
| `4f4b653e` #2365 | yfinance 基本面同比改按日期找去年同季 | 正向修正；台股基本面若走 yfinance 一并受益 |
| `a8c784a9` #2370 / `be148f39` #2373 | 财务摘要宽表按最新报告期解析；新浪财务指标新标签 | A 股基本面 |
| `5f063362` #2369 | 个股资金流带 `market` 参数、取最新日期列 | `get_capital_flow_context` 只对 `cn` 开放（`base.py` `_market_tag != "cn"` 即 not_supported），台股不经过 |
| `653f7ece` #2371 | 交易 Skill 指令传入 Codex 问股 | 本 fork 未启用 Codex 问股 |

## 冲突裁决（`src/analyzer.py`）

统一原则：**`if english:` 取上游英文；`else` 保留 fork 的 `L(繁, 简)`**；fork 专属逻辑（依市场的币别 `ccy`、估值 `V()` 回退、法人与交易成本区块）全部保留。

| 位置 | 裁决 |
| --- | --- |
| `_phase_aware_quote_labels` | 上游外层（en/ko 用 `_QUOTE_LABELS_EN` 对照）＋ fork 的 `_zh(context, report_language)` 内层；对照表以简体为 key，所以 en/ko 先取简体再查表 |
| `_legacy_audit_marker_specs` | 三路：英文／`_format_prompt_tech_section_title`（繁或简）／新闻标题三语；须与 prompt 实际标题逐字相同 |
| `_sanitize_trend_analysis_for_prompt` | 参数名改用上游的 `language`（唯一呼叫端同步），`english` 与 `L()` 并存 |
| 行情表 | 英文 `price_unit=""`；非英文 `price_unit=f" {ccy}"`（与 fork 原输出逐字相同）＋繁简标签 |
| `_format_amount` | **签名改为 `(amount, market='cn', report_language='zh')`**：上游是 `(amount, report_language)`，fork 是 `(amount, market)`，第二个位置参数语意相反。自动合并进来的上游英文呼叫端（市值）已一并改为三参数 |
| 决策仪表盘标题、财报、资金流、三大法人、筹码、趋势、量价、数据缺失、ETF 约束、股票名称格式 | `if english` 上游英文；`else` fork 繁简 |
| 新闻区块标题 | 上游 `else` 是一般字串 `"""`，接上 fork 的 `{L(...)}` 必须改成 f-string，否则 `{L("輿情情報", ...)}` 原样进 prompt。合并后以 AST 扫描全档：一般字串常数里没有 `{L(`、`{ccy}`、`{V(` |

### 合并时补的 fork 增量

上游新测试 `test_english_user_prompt_has_no_chinese_template_text` 抓到 fork 自己的台股区块在英文 prompt 里仍是中文——它用 AAPL，本 fork 的 `tests/test_analyzer_prompt_zh_tw.py` 再用 `2330.TW` 抓到第二处：

- `_tw_institutional_trend_lines`（三大法人近期趋势）：补 en/ko 文案与半形分隔
- 台股交易成本与 ATR14 提示：补 en/ko 文案

## 静默降级排查

逐个问上游本轮新增的共用常数／闸门「涵盖 `tw` 吗？涵盖 `zh-TW` 吗？」：

- **没有新增市场集合**。新增的都是语言二分 `in ("en", "ko")`，`zh-TW` 落在 `else`——也就是 fork 已加 `L()` 的分支。
- `_get_analysis_system_prompt` 的 `use_english_template` 在 zh-TW 仍走中文模板，与合并前相同（system prompt 仍是简体的既有限制，见 `src/AGENTS.md`「語言」）。
- **新增守门** `tests/test_analyzer_prompt_zh_tw.py`：zh-TW 的 prompt 本体在 13 个冲突区块都是繁体且不含对应简体；zh 反向仍是简体；zh-TW 稽核标记与 prompt 标题一致；台股 zh-TW 成交额带新台币、英文为英文量级且无中文；法人趋势三语。合并前**没有任何测试守 zh-TW prompt 本体**。
- mutation：开盘价标签改回简体、新闻标题拿掉 `f`、`_format_amount` 忽略市场币别、法人趋势拿掉英文分支——四者各自让新测试变红。

## 验证

| 项目 | 结果 |
| --- | --- |
| `ci_gate.sh syntax` / `flake8` | 绿 / 绿（0） |
| `scripts/check_ai_assets.py` | 绿 |
| 针对性测试（上游新增/改动 4 档、全部 `test_analyzer_*`、台股报告与交易成本、报告语言、`python_version_compat` 等） | 477 passed |
| **全量离线测试** | 未在本机跑，以 PR CI（Python 3.11、分三片）为准 |
