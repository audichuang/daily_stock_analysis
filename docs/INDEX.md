# 文档中心

这里是项目文档入口。README 负责项目概览和快速开始；更完整的配置、部署、功能说明和排障内容从这里进入。

## 按场景选择

| 我想要 | 先看 | 继续看 |
| --- | --- | --- |
| 快速了解项目能做什么 | [README](../README.md) | [完整配置与部署指南](full-guide.md) |
| 第一次把项目跑起来 | [小白客户端安装与配置](beginner-client-setup.md) | [完整配置与部署指南](full-guide.md) |
| 配置大模型渠道 | [LLM 配置指南](LLM_CONFIG_GUIDE.md) | [LLM 服务商配置指南](llm-providers.md)（含 xAI Grok 直连） |
| 配置推送通知 | [通知能力基线](notifications.md) | [完整配置与部署指南](full-guide.md) |
| 部署到服务器或云平台 | [部署指南](DEPLOY.md) | [云端 WebUI 部署](deploy-webui-cloud.md)、[Zeabur 部署](docker/zeabur-deployment.md) |
| 使用 Bot / IM 接入 | [Bot 命令与接入](bot-command.md) | [Bot 平台配置](bot/)、[Grok Bot 集成](grok-bot-integration.md) |
| 排查运行问题 | [FAQ](FAQ.md) | [更新日志](CHANGELOG.md) |
| 处理数据源失败或降级 | [数据源稳定性与故障处理图示](data-source-stability.md) | [FAQ](FAQ.md) |
| 参与开发或提交 PR | [贡献指南](CONTRIBUTING.md) | [API 规格](architecture/api_spec.json) |

## 快速开始

| 文档 | 内容 |
| --- | --- |
| [README](../README.md) | 项目定位、核心能力、快速开始、推送效果 |
| [小白客户端安装与配置](beginner-client-setup.md) | 面向不会代码用户的客户端下载、Anspire Open / AIHubMix 模型配置、新闻源配置和常见问题 |
| [完整配置与部署指南](full-guide.md) | 环境准备、运行方式、配置说明、部署路径和常见问题 |
| [FAQ](FAQ.md) | 常见配置、模型、通知、部署和运行问题 |
| [数据源稳定性与故障处理图示](data-source-stability.md) | Tushare、TickFlow、AkShare、Efinance、YFinance、Longbridge 等已接入源的使用场景、fallback 链路和推荐配置 |
| [数据中心](data-center-diagnostics.md) | 只读 Provider 能力、数据集质量、精确市场支持与运行时优先级 |
| [更新日志](CHANGELOG.md) | 版本变化、能力调整和迁移说明 |

## 配置

| 文档 | 内容 |
| --- | --- |
| [LLM 配置指南](LLM_CONFIG_GUIDE.md) | 大模型渠道、三层配置、Web 设置页和常见模型配置 |
| [LLM 服务商配置指南](llm-providers.md) | Provider 预设、Actions 映射、错误分类和诊断建议 |
| [LiteLLM YAML 示例](examples/litellm_config.example.yaml) | LiteLLM 多渠道配置示例 |
| [Grok Bot Skill 示例](examples/grok_bot/README.md) | 给 Grok Bot 粘贴的最小 Skill，调用现有 REST |
| [通知能力基线](notifications.md) | 企业微信、飞书、Telegram、Discord、Slack、邮件等通知渠道配置 |
| [Tushare 股票列表指南](TUSHARE_STOCK_LIST_GUIDE.md) | Tushare 股票列表相关配置和使用说明 |

## 使用专题

| 文档 | 内容 |
| --- | --- |
| [Daily Stock AI iOS App](ios-app.md) | 台美股原生看盤、AI 研究、私人服務連線與 TestFlight |
| [自选股变化状态与下一步](watchlist-next-action.md) | 首页自选股列表的变化、状态、下一步三段信号、映射规则和后续扩展边界 |
| [Bot 命令与接入](bot-command.md) | Bot 命令、Webhook、平台接入和回调说明 |
| [Bot 平台配置](bot/) | 飞书、钉钉、Discord 等 Bot 配置截图和补充说明 |
| [实时告警中心](alerts.md) | EventMonitor 基线、Web 规则管理、通知结果、冷却状态和 Phase 边界 |
| [个股研究聚合 API](stock-profile-api.md) | 单一 stock-profile 契约、分块质量状态、代码归一与后续 Web 边界 |
| [DecisionSignal 决策信号专题](decision-signals.md) | AI 建议池字段语义、API、Web 展示、告警/通知/组合风险联动、后验评估、脱敏、迁移与回滚 |
| [ETF 轮动](etf-rotation.md) | `--etf-rotation` 规则化双动量轮动：规则、配置、报告章节、参数平原解读与数据告警边界 |
| [ResearchArtifact 结构化研究产物](research-artifact.md) | structured_report 字段、Thesis / Evidence / Invalidation / Next Action / Data Quality 契约和旧报告兼容边界 |
| [组合风险与暴露看板](portfolio-risk-exposure-dashboard.md) | 持仓页风险旗标、市场暴露、币种暴露和价格质量聚合展示 |
| [选股解释契约](screening-explanations.md) | Why Selected / Why Now 的后端确定性解释、来源、质量状态与缺失值边界 |
| [资讯 / 情报源](intelligence-sources.md) | RSS/Atom 合规资讯源配置、测试、拉取、去重、存储、查询与安全边界 |
| [分析上下文包契约、运行态消费与可见性](analysis-context-pack.md) | AnalysisContextPack 首版范围、字段质量状态、P1/P2 内部契约、P3 Prompt 摘要消费、P4 历史/API/Web 低敏可见性、P5 数据质量评分、P6 迁移回滚与源码锚点；完整指南补充 #1386 阶段感知分析、迁移与回滚入口 |
| [图片识别 Prompt](image-extract-prompt.md) | 图片识别股票信息的 Prompt 与使用边界 |
| [OpenClaw Skill 集成](openclaw-skill-integration.md) | OpenClaw / Skill 外部集成说明 |
| [Grok Bot 集成](grok-bot-integration.md) | 2026-08-11 Grok Bot（AI teammate）与 DSA REST / DecisionSignal / Skill 的对接边界 |

## 台股（本 fork）

> 本 fork 的台股專屬文件。**第一次接手先讀「現況總覽」**：它說明每日分析抓哪些數據、哪些規則會改掉 LLM 結論、開關怎麼設，以及哪些問題已經研究過、不要重做。研究紀錄是當天快照，現行行為以總覽與程式為準。

### 先讀

| 文件 | 內容 |
| --- | --- |
| [台股分析現況總覽](tw-analysis-overview.md) | 一頁看懂每日個股分析抓哪些數據、哪些護欄會改掉 LLM 結論（依執行順序）、開關與建議值、2026-10-22 診斷與回測已回答的問題（零買進成因、放寬有沒有用、大盤／營收／投行預估），以及待辦 |
| [台股操作手册](tw-operating-guide.md) | 每天几点做什么、每日报告怎么读（看文字结论与狙击点位、忽略买卖标签；没有持有期）、三条线（AI 报告／波段／价值）的分工与证据状态、上柜月营收的口径闸门 |

### 流程與資料

| 文件 | 內容 |
| --- | --- |
| [台股波段候选流水线](tw-swing-pipeline.md) | 量化预筛 → AI 事件面研究 → 回验四层的契约：冻结的讯号定义、前瞻报酬分布与区块 bootstrap 区间、组合层（资金竞争／排序／走前验证）结论、回验指标，以及明确站不住的部分 |
| [台股個股四維度資料包](tw-stock-dossier.md) | Web「四維度分析」抽屜與 `/stock-report` 的 HTML 報告、解讀快取；`tw_stock_dossier.py` 各段的來源與限制（分點只有前 15 名、HHI 口徑、SMC 定義），以及與 botbook.cc 範例報告的逐項對照 |
| [台股 SMC 價位警報（預設關閉）](tw-level-alerts.md) | 看板「建立價位警報」的規則設計、Markdown 訊息版型、重建語意，以及啟用前檢查清單 |
| [台股資料正確性](tw-data-integrity.md) | 什麼叫「對」（逐列對官方的判準）、各資料集驗證到哪、已知不修的差異、2026-10-23～24 修了什麼，以及逐日比對工具 `scripts/audit_market_vs_official.py` 與重抓的 runbook |
| [總經、Fed 利率預期與重大事件](macro-data.md) | `market` schema 的 `macro_series`／`rate_expectations`／`event_calendar`：來源（yfinance、FRED、Kalshi、Fed 官網）、日期與機率語意、財報日可能差一天、開關與失敗語意、`make morning` 大局儀表怎麼讀 |
| [market_data 踩雷全集](market-data-pitfalls.md) | `market` schema 的資料語意、踩雷案例與實測數字（未還原價、只有上市的表、T86 初版、端點凍結） |
| [台股交易成本口徑](tw-trading-costs.md) | 回測、決策回驗與成本護欄共用的 `tw_trade_costs`：手續費、證交稅、滑價、年化天數 |
| [台灣境內基金](tw-funds.md) | 基金淨值資料來源、API、Web `/funds` 與基金持倉 |

### 研究與對帳（結論正本）

| 文件 | 內容 |
| --- | --- |
| [台股訊號研究 2026-10](tw-signal-research-2026-10.md) | 大盤狀態（0050 季線、市場寬度、融資背離）與月營收動能（降速、月減、斷創高）的前瞻淨報酬回測，以及賣方共識（目標價／EPS 修正）調查：n、期間、bootstrap CI 與 inconclusive 標記，和接進 prompt 時的用字規則 |
| [台股大盤位階與長期進場時點](tw-market-position.md) | 大盤層量測（2026-07~08）：回撤深度、距 5 年線、均值回歸、月份季節性、一次投入 vs 分批 |
| [台股波段判断事后对帐 2026-08](tw-swing-hindsight-2026-08.md) | 2026-07-24 ~ 08-05 的 4 笔波段决策、5 笔盘前 regime、7 档筛选候选量到 2026-08-21 的中途对帐：逐档还原价报酬与同窗 0050 对照、过了对抗审查的误判、可知与不可知的盲点、该改与**不该改**的清单 |

### 研究紀錄（快照，`docs/research/`）

| 文件 | 內容 |
| --- | --- |
| [零買進診斷 2026-10-22](research/2026-10-22-no-buy-diagnosis.md) | 研究紀錄：873 份報告零買進的根因（資金流護欄、黃燈 conservative、多頭排列）、反推回測、外部方法對照、資料缺口與修改提案的原始版本 |
| [台灣財經媒體掃描 2026-10-22](research/2026-10-22-tw-media-sweep.md) | 研究紀錄：五類媒體（技術、籌碼、電視、基本面、報紙券商）的分析方法、年底共識、點名個股事後表現（inconclusive）、DSA 缺的數據 |
| [點名來源擴充 2026-10-23](research/2026-10-23-media-sources-expansion.md) | 研究紀錄：媒體點名頻道的收錄／拿掉／沒收與理由、PTT `[標的]` 文試跑、審查抓到的資料截止日（look-ahead）與代號錯誤 |
| [分析師方法對照 2026-10-26](research/2026-10-26-analyst-methods-gap.md) | 研究紀錄：籌碼／技術／基本面／總經／學術五派方法對照本 fork 的資料與策略，經對抗審查後的缺口與待驗實驗清單（TDR 混入 live 漏斗、20.2% 錨點待重測、SUS 營收、處置延後進場等，全部 inconclusive） |
| [實驗：LHR 否決 2026-10-26](research/2026-10-26-exp-lhr-veto.md) | 研究紀錄：漲停率減跌停率（LHR）否決突破候選的事先登記與結果——否決有害（h60 均值與 P(≥30%) 區間皆為負），LHR 與 20 日波動相關 +0.78 |
| [實驗：反波動加權、PB≥2 否決 2026-10-26](research/2026-10-26-exp-invvol-pb.md) | 研究紀錄：組合層反波動部位加權（有害：h60 逐日報酬差區間整段為負、Sharpe 1.19→1.00）與突破池 PB≥2 否決（池內 76% PB≥2、閘門未過、未檢定）的事先登記與結果 |
| [實驗：突破池基準率重測 2026-10-26](research/2026-10-26-exp-rebaseline-anchor.md) | 研究紀錄：SW-F1 休市日復權、月營收期限順延、宇宙統一之後重跑 `measure_signal_forward`，更新 `confidence` 錨點（原 20.2%）的事先登記、判準與結果 |
| [實驗：法人對立極端樣本外 2026-10-26](research/2026-10-26-exp-divergence-oos.md) | 研究紀錄：外資與投信橫斷面對立極端（90 臂唯一存活構念）以 2013–2019 做樣本外驗證的事先登記、判準與結果 |
| [實驗：處置公告延後進場 2026-10-26](research/2026-10-26-exp-disposal-delay.md) | 研究紀錄：TWSE 處置公告歷史（2013 起）與處置期制度沿革，突破池「延後 3／4 日進場」「處置期後進場」「剔除」對正常進場的事先登記、判準與結果（延後 inconclusive、剔除較差） |
| [實驗：FOMC／CPI／NFP 前一日延後進場 2026-10-28](research/2026-10-28-pre-event-delay.md) | 研究紀錄：重大總經事件前一個台股交易日，突破池延後到事件日進場對正常進場（h60）的事先登記、判準與結果，含大局緊縮日（DGS10／Brent／DXY 20 日同漲）子檢定（主檢定 n=112、子檢定 n=21，皆 inconclusive；`tw-morning-call` Step 2.5 那條維持只寫進 `reason`） |
| [實驗：SUS／營收÷歷史最高 取代或補充 YoY≥20 2026-10-26](research/2026-10-26-exp-revenue-sus.md) | 研究紀錄：月營收更正的入庫語意（後寫覆蓋、不留原值）、SUS 與營收÷歷史最高在突破池當補充或取代 YoY≥20 閘門的事先登記、判準與結果 |
| [實驗：SUS／營收÷歷史最高 取代或補充 YoY≥20 2026-10-26](research/2026-10-26-exp-revenue-sus.md) | 研究紀錄：月營收更正的入庫語意（後寫覆蓋、不留原值）、SUS 與營收÷歷史最高在突破池當補充或取代 YoY≥20 閘門的事先登記、判準與結果（4 個主檢定全部 inconclusive） |
| [實驗：SUS／營收÷歷史最高 取代或補充 YoY≥20 2026-10-26](research/2026-10-26-exp-revenue-sus.md) | 研究紀錄：月營收更正的入庫語意（後寫覆蓋、不留原值）、SUS 與營收÷歷史最高在突破池當補充或取代 YoY≥20 閘門的事先登記、判準與結果（2 個主檢定通過但未過 Bonferroni、2 個 inconclusive，無一存活，整體 inconclusive） |
| [總經模型階梯 2026-10-28](research/2026-10-28-macro-ladder.md) | 研究紀錄：07:30 資訊集下只看美股＋台指期夜盤 vs 加總經（10Y、2Y、DXY、台幣、Brent、HYG、VIX、ICSA）的樣本外增量 R² 與 0050 交易腿（確認性比較 inconclusive、待對抗審查），四條預登記事件規則（全部 inconclusive），對齊規則與 mutation 清單 |
| [美股資料源與社群做法調查 2026-10-31](research/2026-10-31-us-data-sources-survey.md) | 研究紀錄：美股資料現況、免費 API 限額與授權、富途 OpenD 實測、英文與中文社群看法 |
| [探索性回測：產業反轉、25MA 出場 2026-10-28](research/2026-10-28-explore-reversal-ma25.md) | 研究紀錄：五日產業相對輸家反轉（每週換手，對 0050 不支持，區間整段為負）與 breakout 組合改跌破 25MA 連 3 日出場（區間跨零，inconclusive，點估計 Sharpe／回撤都較差）的事先判準、事後偏離與結果 |

### 維運

| 文件 | 內容 |
| --- | --- |
| [本機排程與每日報告維運](daily-report-ops.md) | Orca 排程一覽（盤前、上游同步、每日報告、持股檢查）、每日報告的逾時／鎖／完成標記與卡住時的診斷 |
| [CI 自架 runner（ttnas）](ci-ttnas-runner.md) | CI 跑在 ttnas 自架 runner 的設定由來（4 片、本機快取、tmpfs）、各種紅的症狀對照與排障指令 |
| [NAS 上的 Web 服務與發版](nas-deploy.md) | 本 fork Web 服務跑在 NAS：不在本機再起一份的理由、釘 digest 經 Komodo 的手動發版流程、NAS 問股後端、唯讀查看線上狀態與直接查 DB、第二台開發機的分工 |

## 部署与打包

| 文档 | 内容 |
| --- | --- |
| [部署指南](DEPLOY.md) | 服务器部署、Docker、systemd、Supervisor 等部署方式 |
| [云端 WebUI 部署](deploy-webui-cloud.md) | 云服务器访问 WebUI 的部署说明 |
| [Zeabur 部署](docker/zeabur-deployment.md) | Zeabur 平台部署说明 |
| [桌面端打包说明](desktop-package.md) | Electron 桌面端和 Web 构建产物打包说明（上游文件，本 fork 不使用桌面版） |

## 参考与开发

| 文档 | 内容 |
| --- | --- |
| [API 规格](architecture/api_spec.json) | FastAPI OpenAPI 规格产物 |
| [贡献指南](CONTRIBUTING.md) | Issue、PR、测试、文档同步和协作要求 |
| [真實使用者流程驗證](verification.md) | verify skill、ego-browser、隔離啟動、功能地圖與實跑證據 |

## 多语言

| 文档 | 内容 |
| --- | --- |
| [英文文档索引](INDEX_EN.md) | English documentation index |
| [英文 README](README_EN.md) | English project overview and quick start |
| [繁中 README](README_CHT.md) | 繁體中文項目概覽與快速開始 |
