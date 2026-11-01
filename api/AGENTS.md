# api — FastAPI 服務層

## 模組定位

`api/` 是薄層:路由、請求校驗、回應序列化。消費端有兩個:Web(`apps/dsa-web`)與原生 iOS App(`apps/dsa-ios`,走公網入口,手機上的舊版本會一直留著)。所以**改回應欄位等於同時改兩個客戶端**。

## 進來改要遵守

- **台股代碼的接受規則要三處一起放寬或收緊**:後端閘門 `v1/endpoints/stocks.py` 的 `_STOCK_CODE_RE`、前端 `apps/dsa-web/src/utils/validation.ts`、聊天抽取 `chatStockCode.ts`;語意真源是 `src/services/market_symbol_utils.py`。三條 regex 本來就不逐字相同(指數別名各有處理),只同步台股那一段,**不要改成一模一樣**。只修一處的症狀是「解析得過但抓不到報價」,比直接拒絕更難診斷。
- 台股代碼正則的契約測試 `test_tw_code_pattern_contract.py` 只看得到「同一行寫了位數與 `TW`」的正則;`isdigit()`、分開比對後綴的寫法它看不到,查「帶字母的台股不見了」時仍要全掃。
- **字元判斷只認 ASCII。**Python 的 `\d`、`str.isdigit()`、`str.isalpha()` 都是 Unicode-aware,全形數字、阿拉伯-印度數字、漢字都會通過;而下游抓取失敗是 fail-open,結果是一份靜默缺資料的報告而不是拒絕。regex 帶 `re.ASCII`,字元方法配 `.isascii()` 或字面範圍比較。
- **錯誤一律用 `v1/errors.py` 的 `api_error()` 帶錯誤碼。**`HTTPException(detail="字串")` 會被包成籠統的 `http_error`,前端靠 `detail.error` 的碼分類(如 `portfolio_busy`、`screening_unavailable`),對不到碼就走不到對應的處理。
- **校驗失敗的回應只投影 `type`／`loc`／`msg`,刻意丟掉 pydantic 的 `input` 與 `ctx`**(會回顯密碼、把 100KB 輸入原樣吐回、`ctx` 裡的例外物件無法序列化而變 500)。端點自己組的錯誤訊息不經過那層投影,所以**新 schema 的字串欄位一律設 `max_length`**,在輸入邊界擋。
- **回應裡的數值要分清三種狀態:讀數是 0、沒有讀數、非有限值。**`float(x) if x else None` 兩頭都錯——NaN 為真會被放行(`JSONResponse` 直接 500)、0 是真實讀數卻被丟掉。缺值回 `null`,不要用 `0.0` 當哨兵。目前只有大盤複盤與選股的回傳有做非有限值清洗,行情類端點沒有。
- **批次端點單筆失敗回該筆 `null` 加 `error`,HTTP 仍是 200。**筆數上限要在解析與去重**之前**用原始輸入計算,否則一筆合法加大量重複可以繞過上限。
- **回應型別與客戶端是純手動同步**(沒有 codegen):`v1/schemas/` ↔ `apps/dsa-web/src/types/` 與 `apps/dsa-ios/Core/Sources/DSACore/Models.swift`,請求的欄位名另外手寫在 `apps/dsa-web/src/api/*.ts`。漏改後者時 tsc 照樣綠,請求少一個欄位、後端當作沒傳。**回應鍵名別讓數字後面接字母**:前端 `toCamelCase`(camelcase-keys)會把 `1w` 轉成 `1W`、`max_drawdown_1y` 轉成 `maxDrawdown1Y`,型別照寫就讀到 undefined、tsc 不會報。
- **報告語言的列舉在 schema 裡是手寫的 `Literal`**,不是從 `SUPPORTED_REPORT_LANGUAGES` 衍生。新增語言只改常數的話,文件描述會跟著變,請求仍被 422 擋下。

## 踩雷

- **認證的門只有中介層一道。**`ADMIN_AUTH_ENABLED` 開啟時 `/api/v1/*` 全部要 session,豁免清單是 `middlewares/auth.py` 的 `EXEMPT_PATHS`(完整路徑相等,不是前綴)。router 上的 `Security(...)` 依賴只是給 OpenAPI 看的,不會擋請求;路由掛到 `/api/v1/` 之外就是開放的。
- **請求帶的 `region` 會被正規化成固定順序,`.env` 的 `MARKET_REVIEW_REGION` 才保留輸入順序**(`tw,us` = 台股為主)。兩者刻意不同:前端勾選框送出的順序與點擊順序無關,設定檔則是操作者打一次、順序有意義。
- **自選清單的等價鍵要用原始輸入、並帶資產類型來算。**正規化會剝掉 `.SH` 這類後綴,指數身分在算鍵之前就沒了——踩過:移除指數 `000016.SH` 刪到同號的個股。
