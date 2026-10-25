# -*- coding: utf-8 -*-
"""繁體 → 簡體的逐字折疊表（操作建議關鍵字比對共用）。

回測引擎與 DecisionAction 正規化的關鍵字表都是簡體字面量；zh-TW 報告的建議文字
（「減碼」「賣出」「觀望」「不建議買入」）要先逐字折成簡體才比得到。只做一對一字元
替換，字串長度與位置不變。新增關鍵字用到有繁體寫法的字時，把那個字補進這張表，
不要另開平行的表。
"""

from __future__ import annotations

TRAD_TO_SIMP = str.maketrans(
    "買賣減倉碼強觀盤盪蕩議應當暫無須別沒進風險預觸發規佈迴",
    "买卖减仓码强观盘荡荡议应当暂无须别没进风险预触发规布回",
)


def fold_traditional(text: str) -> str:
    """把字串中表內的繁體字逐字換成簡體。"""
    return text.translate(TRAD_TO_SIMP)
