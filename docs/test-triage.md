# 全量測試與紅燈判讀

全量离线测试应该全绿；红了先排除下面的假红，再判回归。

## 跑全量

- 耗時依機器差十幾倍(實測:一台 Mac 約 4 分鐘、另一台機器 56 分鐘,測試數相當、都是單行程),別拿一個數字估另一台;平常用受影響測試檔的子集。
- **「離線」測試其實會連外,是這個 repo 最貴的一類坑**(踩過一次掛 6 小時 21 分,只燒 30 秒 CPU)。止血是單測 timeout(數字見下方),會讓它紅在那個測試上並印出堆疊。

## 判讀紅燈:先排除這幾種假紅,再判回歸

| 形狀 | 特徵 | 判別 |
|---|---|---|
| 負載 | 錯誤是 timeout 類(`Test timed out`、`assertFalse(thread.is_alive())`),不是斷言值不對 | 單獨在空機器上重跑會綠 |
| 連外 | 紅在 timeout 並印出堆疊,停在 socket 讀取 | 對方收了連線卻不回;補上漏掉的那格 mock |
| 連外(fail-open) | 斷言值不對、不是 timeout:對端回錯時生產碼吞掉錯誤、該欄變缺值(踩過:台股 `get_fundamental_context` 沒 mock `TwseFundamentalAdapter`,TWSE 一回非 JSON,`growth` 就進 `missing_fields`) | 單跑常綠;**斷網重跑穩定重現**——用一個 pytest plugin 把 `socket.socket.connect` 對非 loopback 改成拋錯,帶 `-p` 載入 |
| `.env` 漏入 | 「預設值」類測試讀到本機 `.env` 的值 | 單跑綠;帶 `<KEY>=<.env 的值> pytest <該測試>` 紅。CI 沒有 `.env`,只在本機出現 |
| 時段 | 同一份程式碼早上紅、下午綠,**單跑也紅** | 換個時段重跑;修法見 `tests/AGENTS.md`「日期與 phase 兩個都要釘住」 |
| 執行鎖 | 只有 `test_single_run_lock_blocks_overlap` 紅 | 同一台機器正在跑 `make media-picks`(Mac 平日 23:00 排程),測試拿到的是真的鎖;等它跑完再重跑 |

- `.env` 有兩條漏入路徑:任何較早跑的測試呼叫 `load_dotenv()`;以及 `market_data/tests/conftest.py` 在收集期就把 `DATABASE_URL` 寫進行程且不還原——所以全量裡連的是本機真實庫,單跑 `tests/` 底下的檔則沒有。
- 單測 timeout 直接打 `pytest` 是 300 秒,經 `ci_gate.sh` 是 120 秒。
- 連外與時段兩種要修。`.env` 漏入的「預設值」類假紅是既有問題、CI 綠,真正的修法是隔離 `os.environ`——記錄下來即可,不要順手改。
- **例外:會指向正式資料的鍵不是假紅,是事故。**`.env` 新增任何指向正式服務的 URL／金鑰,要在 conftest 中和(曾因 `STORAGE_DATABASE_URL` 漏入,fixture 寫進 NAS 共用的正式應用庫)。`DATABASE_URL` 例外:`market_data/tests` 刻意連它並用 rollback 保護。
