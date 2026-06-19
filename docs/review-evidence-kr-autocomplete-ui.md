# KR/JP 自动补全下拉列表变更的可视证据补充说明

本次改动涉及 `apps/dsa-web/src/components/StockAutocomplete/SuggestionsList.tsx` 的 Web UI 展示（JP/KR 市场徽标）。该项为可视化审核项，建议在 PR 描述/评论中附上受影响下拉列表截图（建议前后对比）。

原因（当前环境）:
- 本地自动化环境目前以代码与回归测试为主，尚未在该上下文内启动可复用的前端可视化回归截图链路。
- 未提交一次性截图资产到仓库；仅通过仓库内可回放测试与 PR 描述附图进行审核。

替代审计证据：
- 回归测试 `apps/dsa-web/src/components/StockAutocomplete/__tests__/StockAutocomplete.test.tsx` 中已新增/保留 `韩股` 与 `日股` 市场徽标文案校验。
- 后端索引兼容性回归在 `tests/test_stock_index_remote_service.py` 的 `test_validate_stock_index_payload_accepts_jp_and_kr_markets` 覆盖。
