# 繁中介面詞彙表

Web 與 iOS 手動同步的正本。Web 在 `apps/dsa-web/src/i18n/uiText.ts`、`locales/featureText.ts` 的 `zh-TW`；iOS 在 `apps/dsa-ios/App/Design/PresentationText.swift`。兩邊沒有 codegen，改這裡要兩邊一起改。

## 通用用語

| 用這個 | 不要用 | 備註 |
|---|---|---|
| 警報 | 告警、預警 | `警告` 只留給日誌與執行流程的嚴重度 |
| 持股 | 持倉 | 導覽與頁面標題叫「資產」，內容裡仍叫持股 |
| 重新整理 | 刷新 | |
| 設定 | 配置 | |
| 管道 | 渠道 | 通知管道、模型管道 |
| 股票代號 | 股票代碼 | `錯誤代碼` 這類非股票的代碼不改 |
| 自選 | 自選股（僅標題可用） | |

## 範例值

輸入框與說明的範例用 `2330.TW`、`台積電`、`AAPL`，不用 A 股代號。不放英文眉標（如 `Data Center`、`DETAIL VIEW`）。

## 動作

顯示一律依結構化 `action` 枚舉查表，不讀存檔的標籤。舊報告存的「減倉」「持有」「買入」要顯示成下表的詞。

| `action` | 顯示 | 語意色（Web `actionTone`／iOS `ActionTone`） |
|---|---|---|
| `buy` | 買進 | 品牌色 |
| `add` | 加碼 | 品牌色 |
| `hold` | 續抱 | 灰 |
| `watch` | 觀望 | 灰 |
| `avoid` | 迴避 | 琥珀 |
| `reduce` | 減碼 | 琥珀 |
| `sell` | 賣出 | 琥珀 |
| `alert` | 警報 | 琥珀 |

## 顏色

- 行情方向與損益：紅漲綠跌、紅賺綠賠（Web `--market-up`／`--market-down`，iOS `Theme.up`／`Theme.down`）。
- 動作不用紅綠，見上表。
- `success`／`danger` 只給系統狀態（連線成功、刪除等）。

## 數字

- 負號用 `−`（U+2212），正值的百分比帶 `+`。
- 千分位一律加；沒有讀數顯示 `—`，不顯示 0。
- 語系預設 `zh-TW`，數字欄用 tabular 數字。
