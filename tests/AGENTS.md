# tests — 離線測試套件

## 模組定位

測試根有兩個:`tests/`(主套件)與 `market_data/tests/`(台股 DB,本 fork 增量)。**這份清單寫在兩處,必須一致**:`setup.cfg` 的 `testpaths` 與 `scripts/ci_test_shard.py` 的 `TEST_ROOTS`——漏一處就是整個根被靜默排除,看起來跟通過一模一樣。新增測試檔不登記時長表也照跑(沒紀錄的檔用中位數分片),但缺得多 shard 就失衡(踩過:缺 107 檔時三片 148／296／409 秒);各片差距明顯時照 `scripts/ci_durations_from_junit.py` 開頭的步驟重算。分片以整個檔為單位,單一檔比平均每片還長時它會獨占一片(例如整合型的大檔),那片偏長是預期,重算解決不了。改名或刪除已登記的檔會紅。

這裡幾乎沒有全域的隔離:`os.environ`、時鐘、對外連線都不會自動還原或攔截。`conftest.py` 在 import 時做的事:把 `TestClient` 換成不開執行緒的版本;**把 `STORAGE_DATABASE_URL` 釘成空字串,並讓 `create_engine` 拒絕 `.env` 裡那條正式應用庫 URL**(守門測試在 `test_storage_database_url.py`;worktree／`.env` 的判定細節見 conftest 註解);另外中和幾個會連外或讀本機資料的 env(`TW_ADHOC_CLOSED_FILE`、`TW_CLOSURE_AUTODETECT`、`TW_LIVE_EVENTS_ENABLED`、`ANALYST_CONSENSUS_ENABLED`、`TW_BROKER_INDEX_TARGETS`)——要測這些功能的自己 monkeypatch 或注入 config 打開。marker 只有 `network` 有作用(`unit`、`integration` 沒人用,標了也不會被 CI 跳過)。

## 寫新測試要遵守

- **被測函式會讀市場時間時,日期與 phase 兩個都要釘住。**只 patch `get_market_now` 而沒管 `infer_market_phase`,phase 就吃真實牆鐘;有些 phase 還會短路、根本不問日曆。測試只在特定時段紅(踩過三次:A 股盤前、紐約盤中、台北清晨——後者正是 `make morning` 的時段)。這個 repo 不用 freezegun,一律 patch 這兩個函式或把 `current_time` 傳進去。
- **時間戳在建構時取,不在模組 import 時取。**全量在慢機器上要跑近一小時,收集期算好的時戳到執行時已超過 realtime TTL——單跑綠、全量紅。
- **不是被測性質的 timeout／budget 放寬到 30~60 秒**(mock 立即返回,不會變慢),否則忙機器與 CI runner 上會假紅。斷言「此刻仍被擋住」的那種 timeout 相反——值越大越嚴格,不要放寬。
- **成對寫守門**:擋 PREMARKET 的測試要配一支「POSTMARKET 仍然放行」,否則把判斷寫成「非盤中一律擋」照樣綠。
- **mock 的接縫選自家函式,不要 patch `requests`／DNS**:後者會被其他測試殘留的 socket 狀態影響,變成順序敏感。
- **會走到選股／熱點 provider(eastmoney、akshare、sina)的測試要自帶連外守門。**那條鏈每個網路失敗都被 `except` 接住再 fallback,漏一格 mock 的測試有沒有網路都是綠的。守門是 `test_screening_api.py` 的 `_no_outbound_network`,**只對該檔生效**,新檔要自己複製一份;它刻意繼承 `BaseException`,而生產碼那端必須維持 `except Exception`,任一邊放寬守門就被吞掉。兩個必踩形狀:`provider="akshare"` 會讓未 patch 的 `_resolve_hotspot_provider` 造出真 provider;繼承真 provider 的 Fake 會繼承整條連外子樹。
- **官方端點的原始回應要逐位元組比對時,存成 `tests/fixtures/*.bin`**(`.gitattributes` 標 binary)。本機 git 是 `core.autocrlf=input`,其他副檔名的 CRLF 在 commit 時被改成 LF、工作區卻仍是 CRLF——本機綠、乾淨 checkout 才紅(踩過:期交所 CSV)。驗法:`git show HEAD:<檔>` 比位元組,或在新 worktree 跑該測試。
- **被測模組會 import `litellm`(`src.analyzer`、`src/llm/`、`src/agent/` 一類)時,import 之前先呼叫 `litellm_stub.ensure_litellm_stub()`**,否則 LiteLLM 在 import 時會去抓 model cost map(有本地 fallback,不會掛,但會連外)。
- **驗「寫入當下的值」要在 `side_effect` 裡擷取**。從 `call_args` 讀回來的是同一個物件參考,事後比對恆真,呼叫順序錯了也不會紅。
- **生產路徑是「先建空物件、再逐欄賦值」的型別(如 `MarketOverview`),測試要複製同樣形狀。**用 kwargs 一次建構會讓建構期的守門看起來有效,實際上生產路徑不經過它。
- **別把被測的判斷本身 mock 掉**(例如同時 patch 掉 region 檢查與它保護的建構函式):那樣把 `tw` 從支援清單拿掉測試照樣綠。
- **加速不要引入 pytest-xdist／pytest-split。**有契約測試擋著;分片走自家的 `ci_test_shard.py`。

- **`.env` 裡指向正式資料的鍵漏進測試不是假紅,是事故。**`.env` 新增任何指向正式服務的 URL／金鑰,要在 conftest 中和(曾因 `STORAGE_DATABASE_URL` 漏入,fixture 寫進 NAS 共用的正式應用庫)。`DATABASE_URL` 例外:`market_data/tests` 刻意連它並用 rollback 保護。

- 全量耗時、連外坑與紅燈判讀（負載、連外、`.env` 漏入、時段、執行鎖）見 `docs/test-triage.md`。
