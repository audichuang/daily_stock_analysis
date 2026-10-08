# tests — 離線測試套件

> 共通規則見 repo 根 `AGENTS.md`(該跑哪個門檻 §6、mutation 雙向檢查 §1.2、跑全量的行為規則 §10),本檔只寫「寫測試」與「判讀紅燈」的增量。

## 模組定位

測試根有兩個:`tests/`(主套件)與 `market_data/tests/`(台股 DB,本 fork 增量)。**這份清單寫在兩處,必須一致**:`setup.cfg` 的 `testpaths` 與 `scripts/ci_test_shard.py` 的 `TEST_ROOTS`——漏一處就是整個根被靜默排除,看起來跟通過一模一樣。新增測試檔不用登記時長表(沒紀錄的檔用中位數分片);改名或刪除已登記的檔才會紅。

這裡幾乎沒有全域的隔離:`os.environ`、時鐘、對外連線都不會自動還原或攔截。`conftest.py` 只做兩件事:在 import 時把 `TestClient` 換成不開執行緒的版本;以及**把 `STORAGE_DATABASE_URL` 釘成空字串,並讓 `create_engine` 拒絕 `.env` 裡那條正式應用庫 URL**(守門測試在 `test_storage_database_url.py`)。marker 只有 `network` 有作用(`unit`、`integration` 沒人用,標了也不會被 CI 跳過)。

## 寫新測試要遵守

- **被測函式會讀市場時間時,日期與 phase 兩個都要釘住。**只 patch `get_market_now` 而沒管 `infer_market_phase`,phase 就吃真實牆鐘;有些 phase 還會短路、根本不問日曆。測試只在特定時段紅(踩過三次:A 股盤前、紐約盤中、台北清晨——後者正是 `make morning` 的時段)。這個 repo 不用 freezegun,一律 patch 這兩個函式或把 `current_time` 傳進去。
- **時間戳在建構時取,不在模組 import 時取。**全量在慢機器上要跑近一小時,收集期算好的時戳到執行時已超過 realtime TTL——單跑綠、全量紅。
- **相對於「現在」的視窗用相對日期**;寫死日曆日會在某天開始必紅。DB 種子相反:用遠離真實資料的固定年份,見 `market_data/AGENTS.md`。
- **不是被測性質的 timeout／budget 放寬到 30~60 秒**(mock 立即返回,不會變慢),否則忙機器與 CI runner 上會假紅。斷言「此刻仍被擋住」的那種 timeout 相反——值越大越嚴格,不要放寬。
- **成對寫守門**:擋 PREMARKET 的測試要配一支「POSTMARKET 仍然放行」,否則把判斷寫成「非盤中一律擋」照樣綠。
- **mock 的接縫選自家函式,不要 patch `requests`／DNS**:後者會被其他測試殘留的 socket 狀態影響,變成順序敏感。
- **會走到選股／熱點 provider(eastmoney、akshare、sina)的測試要自帶連外守門。**那條鏈每個網路失敗都被 `except` 接住再 fallback,漏一格 mock 的測試有沒有網路都是綠的。守門是 `test_screening_api.py` 的 `_no_outbound_network`,**只對該檔生效**,新檔要自己複製一份;它刻意繼承 `BaseException`,而生產碼那端必須維持 `except Exception`,任一邊放寬守門就被吞掉。兩個必踩形狀:`provider="akshare"` 會讓未 patch 的 `_resolve_hotspot_provider` 造出真 provider;繼承真 provider 的 Fake 會繼承整條連外子樹。
- **import 被測模組之前先呼叫 `litellm_stub.ensure_litellm_stub()`**,否則 LiteLLM 在 import 時就會連外。
- **驗「寫入當下的值」要在 `side_effect` 裡擷取**。從 `call_args` 讀回來的是同一個物件參考,事後比對恆真,呼叫順序錯了也不會紅。
- **生產路徑是「先建空物件、再逐欄賦值」的型別(如 `MarketOverview`),測試要複製同樣形狀。**用 kwargs 一次建構會讓建構期的守門看起來有效,實際上生產路徑不經過它。
- **別把被測的判斷本身 mock 掉**(例如同時 patch 掉 region 檢查與它保護的建構函式):那樣把 `tw` 從支援清單拿掉測試照樣綠。
- **加速不要引入 pytest-xdist／pytest-split。**有契約測試擋著;分片走自家的 `ci_test_shard.py`。

## 判讀紅燈:先排除四種假紅,再判回歸

| 形狀 | 特徵 | 判別 |
|---|---|---|
| 負載 | 錯誤是 timeout 類(`Test timed out`、`assertFalse(thread.is_alive())`),不是斷言值不對 | 單獨在空機器上重跑會綠 |
| 連外 | 紅在 timeout 並印出堆疊,停在 socket 讀取 | 對方收了連線卻不回;補上漏掉的那格 mock |
| `.env` 漏入 | 「預設值」類測試讀到本機 `.env` 的值 | 單跑綠;帶 `<KEY>=<.env 的值> pytest <該測試>` 紅。CI 沒有 `.env`,只在本機出現 |
| 時段 | 同一份程式碼早上紅、下午綠,**單跑也紅** | 換個時段重跑;修法見上方「日期與 phase 都要釘」 |

- `.env` 有兩條漏入路徑:任何較早跑的測試呼叫 `load_dotenv()`;以及 `market_data/tests/conftest.py` 在收集期就把 `DATABASE_URL` 寫進行程且不還原——所以全量裡連的是本機真實庫,單跑 `tests/` 底下的檔則沒有。
- 單測 timeout 直接打 `pytest` 是 300 秒,經 `ci_gate.sh` 是 120 秒。
- `test_python_version_compat.py` 在本機拿不到 CI 那個 Python 版本時是 **skip 不是 fail**;看到它綠不代表 3.11 已經剖析過。
- 連外與時段兩種要修。`.env` 漏入的「預設值」類假紅是既有問題、CI 綠,真正的修法是隔離 `os.environ`——記錄下來即可,不要順手改。
- **例外:會指向正式資料的鍵不是假紅,是事故。**2026-10-08 全量把 `.env` 的 `STORAGE_DATABASE_URL`(NAS 共用的正式 `dsa` 應用庫)帶進行程,測試只改了 `DATABASE_PATH`,於是告警規則、持倉帳戶、決策信號、LLM 用量等 fixture 全寫進正式庫,還改到一筆真實訊號;症狀只是一個告警測試卡在連新浪。現已由 conftest 擋住;**以後 `.env` 新增任何指向正式服務的 URL/金鑰,要在 conftest 照樣中和**,別等它漏。`DATABASE_URL` 例外:`market_data/tests` 刻意連它並用 rollback 保護。
