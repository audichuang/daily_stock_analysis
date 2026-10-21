---
name: respond-to-review
description: 把 PR review 反馈收敛成完整契约修复，而不是在被点名的位置追加局部补丁。当 reviewer 指出了问题、要回应 review 意见、或 PR 被 request changes 时使用。
---

# 处理 Review 反馈

reviewer 点名的位置是**症状**，不是范围。收到反馈后先重新理解 reviewer 指出的业务契约，再检查同一语义涉及的所有路径，然后一次修完整契约——只改被点到的那几行，下一轮 review 会在兄弟路径上发现同样的问题。

规则真源是仓库根目录 `AGENTS.md`（新测试的 mutation 双向检查见 §1.2）。

## 收敛顺序

1. **逐条列出 reviewer 指出的原问题。** 用 reviewer 的原话，不要提前改写成你的理解。
2. **说明根因。** 「改了哪几行」不是根因；根因是「哪个契约被写错了、为什么当时看起来是对的」。
3. **找出同一语义影响的所有路径。** 至少过一遍：runtime、API / Web、CLI、diagnostics、workflow、docs、tests。用 grep 找出该函数 / 配置 / 字段的全部调用方，别靠回忆。
4. **修完整契约。** 完成标准是「同一语义在上一步列出的每条路径上表现一致」，不是「当前失败测试变绿」也不是「当前评论行改完了」。
5. **补覆盖 reviewer 反例的回归测试**，或明确写出无法验证的原因。测试要打在真实风险层上——mock 掉风险层只能证明局部实现通过。
6. **同步更新 PR body**，让 scope、验证结果、兼容性、风险、回滚方案与当前 head 一致。

走不完这六步时，说明当前 PR 需要拆分、关闭重做，或请维护者确认新的最小范围——这比继续堆补丁便宜。

## 会被判定为低质量提交的做法

- 用 broad fallback、静默降级、`return False/None/[]` 掩盖不清晰的契约。
- 测试 mock 掉真实风险层，只证明局部实现通过。
- CI 通过后声称问题已关闭，但没有覆盖 reviewer 指出的反例。CI 只说明自动检查通过，不能替代人工语义收敛。
- PR body 与实际 diff、验证结果或兼容风险不一致。
- review 后追加零散 patch，而不是重新收敛完整语义。
- 同一业务语义在 runtime、Web/API、docs、workflow、tests 中表现不一致。

## 验证与交付

按 `AGENTS.md` §6 验证矩阵选最接近改动面的检查（后端快速门槛：`uv run ./scripts/ci_gate.sh syntax` + `uv run ./scripts/ci_gate.sh flake8`）。交付说明按 `AGENTS.md` §5 的交付六项写。

涉及 git 写操作时按 [`../shared/baseline-sync.md`](../shared/baseline-sync.md) 的确认边界执行。
