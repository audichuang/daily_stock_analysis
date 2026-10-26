# tests — 離線測試套件

> 本檔只寫「寫測試」「跑全量」與「判讀紅燈」的增量。

## 模組定位

測試根有兩個:`tests/`(主套件)與 `market_data/tests/`(台股 DB,本 fork 增量)。**這份清單寫在兩處,必須一致**:`setup.cfg` 的 `testpaths` 與 `scripts/ci_test_shard.py` 的 `TEST_ROOTS`——漏一處就是整個根被靜默排除,看起來跟通過一模一樣。新增測試檔不登記時長表也照跑(沒紀錄的檔用中位數分片),但缺得多 shard 就失衡(踩過:缺 107 檔時三片 148／296／409 秒);各片差距明顯時照 `scripts/ci_durations_from_junit.py` 開頭的步驟重算。分片以整個檔為單位,單一檔比平均每片還長時它會獨占一片(目前是 `test_agent_active_stock_integration.py`),那片偏長是預期,重算解決不了。改名或刪除已登記的檔會紅。

這裡幾乎沒有全域的隔離:`os.environ`、時鐘、對外連線都不會自動還原或攔截。`conftest.py` 只做兩件事:在 import 時把 `TestClient` 換成不開執行緒的版本;以及**把 `STORAGE_DATABASE_URL` 釘成空字串，並讓所有 `create_engine` 入口拒絕已知正式應用庫與行情庫 URL**（守門測試在 `test_storage_database_url.py`）。沿父目錄找最近的 `.env`，同時經 `git rev-parse --git-common-dir` 找主 checkout 的 `.env`，合併兩份檔案的 `STORAGE_DATABASE_URL` 與 `DATABASE_URL`；工作樹自訂 URL 也不能遮住主 checkout 的正式庫。涵蓋樹內與樹外 worktree（dsa-upstream-sync 的 `~/.cache/dsa-upstream-sync/<date>`），字串與 SQLAlchemy `URL` 物件都會檢查，其他測試 URL 仍可使用。marker 只有 `network` 有作用(`unit`、`integration` 沒人用,標了也不會被 CI 跳過)。

## 寫新測試要遵守

- **被測函式會讀市場時間時,日期與 phase 兩個都要釘住。**只 patch `get_market_now` 而沒管 `infer_market_phase`,phase 就吃真實牆鐘;有些 phase 還會短路、根本不問日曆。測試只在特定時段紅(踩過三次:A 股盤前、紐約盤中、台北清晨——後者正是 `make morning` 的時段)。這個 repo 不用 freezegun,一律 patch 這兩個函式或把 `current_time` 傳進去。
- **時間戳在建構時取,不在模組 import 時取。**全量在慢機器上要跑近一小時,收集期算好的時戳到執行時已超過 realtime TTL——單跑綠、全量紅。
- **相對於「現在」的視窗用相對日期**;寫死日曆日會在某天開始必紅。DB 種子相反:用遠離真實資料的固定年份,見 `market_data/AGENTS.md`。
- **不是被測性質的 timeout／budget 放寬到 30~60 秒**(mock 立即返回,不會變慢),否則忙機器與 CI runner 上會假紅。斷言「此刻仍被擋住」的那種 timeout 相反——值越大越嚴格,不要放寬。
- **成對寫守門**:擋 PREMARKET 的測試要配一支「POSTMARKET 仍然放行」,否則把判斷寫成「非盤中一律擋」照樣綠。
- **mock 的接縫選自家函式,不要 patch `requests`／DNS**:後者會被其他測試殘留的 socket 狀態影響,變成順序敏感。
- **會走到選股／熱點 provider(eastmoney、akshare、sina)的測試要自帶連外守門。**那條鏈每個網路失敗都被 `except` 接住再 fallback,漏一格 mock 的測試有沒有網路都是綠的。守門是 `test_screening_api.py` 的 `_no_outbound_network`,**只對該檔生效**,新檔要自己複製一份;它刻意繼承 `BaseException`,而生產碼那端必須維持 `except Exception`,任一邊放寬守門就被吞掉。兩個必踩形狀:`provider="akshare"` 會讓未 patch 的 `_resolve_hotspot_provider` 造出真 provider;繼承真 provider 的 Fake 會繼承整條連外子樹。
- **官方端點的原始回應要逐位元組比對時,存成 `tests/fixtures/*.bin`**(`.gitattributes` 標 binary)。本機 git 是 `core.autocrlf=input`,其他副檔名的 CRLF 在 commit 時被改成 LF、工作區卻仍是 CRLF——本機綠、乾淨 checkout 才紅(踩過:期交所 CSV)。驗法:`git show HEAD:<檔>` 比位元組,或在新 worktree 跑該測試。
- **import 被測模組之前先呼叫 `litellm_stub.ensure_litellm_stub()`**,否則 LiteLLM 在 import 時就會連外。
- **驗「寫入當下的值」要在 `side_effect` 裡擷取**。從 `call_args` 讀回來的是同一個物件參考,事後比對恆真,呼叫順序錯了也不會紅。
- **生產路徑是「先建空物件、再逐欄賦值」的型別(如 `MarketOverview`),測試要複製同樣形狀。**用 kwargs 一次建構會讓建構期的守門看起來有效,實際上生產路徑不經過它。
- **別把被測的判斷本身 mock 掉**(例如同時 patch 掉 region 檢查與它保護的建構函式):那樣把 `tw` 從支援清單拿掉測試照樣綠。
- **加速不要引入 pytest-xdist／pytest-split。**有契約測試擋著;分片走自家的 `ci_test_shard.py`。

## 跑全量

- 全量是 `uv run ./scripts/ci_gate.sh`(不帶參數＝`all`,第四階段 `pytest -m "not network"`),應該全綠。耗時依機器差十幾倍(實測:一台 Mac 約 4 分鐘、另一台機器 56 分鐘,測試數相當、都是單行程),別拿一個數字估另一台;平常用受影響測試檔的子集。
- **別和另一個重活並行**(pytest 全量 + vitest 全量):實測 vitest 從 15 failed 變 143 failed,全是 timeout,兩份結果同時被污染。
- **「離線」測試其實會連外,是這個 repo 最貴的一類坑**(踩過一次掛 6 小時 21 分,只燒 30 秒 CPU)。止血是單測 timeout(數字見下節),會讓它紅在那個測試上並印出堆疊。LiteLLM 在 import 時會去 `raw.githubusercontent.com` 抓 model cost map(有本地 fallback,不會掛)。
- 台股代碼正則的契約測試 `test_tw_code_pattern_contract.py` 只看得到「同一行寫了位數與 `TW`」的正則;`isdigit()`、分開比對後綴的寫法它看不到,查「帶字母的台股不見了」時仍要全掃。

## 判讀紅燈:先排除這幾種假紅,再判回歸

| 形狀 | 特徵 | 判別 |
|---|---|---|
| 負載 | 錯誤是 timeout 類(`Test timed out`、`assertFalse(thread.is_alive())`),不是斷言值不對 | 單獨在空機器上重跑會綠 |
| 連外 | 紅在 timeout 並印出堆疊,停在 socket 讀取 | 對方收了連線卻不回;補上漏掉的那格 mock |
| 連外(fail-open) | 斷言值不對、不是 timeout:對端回錯時生產碼吞掉錯誤、該欄變缺值(踩過:台股 `get_fundamental_context` 沒 mock `TwseFundamentalAdapter`,TWSE 一回非 JSON,`growth` 就進 `missing_fields`) | 單跑常綠;**斷網重跑穩定重現**——用一個 pytest plugin 把 `socket.socket.connect` 對非 loopback 改成拋錯,帶 `-p` 載入 |
| `.env` 漏入 | 「預設值」類測試讀到本機 `.env` 的值 | 單跑綠;帶 `<KEY>=<.env 的值> pytest <該測試>` 紅。CI 沒有 `.env`,只在本機出現 |
| 時段 | 同一份程式碼早上紅、下午綠,**單跑也紅** | 換個時段重跑;修法見上方「日期與 phase 都要釘」 |
| 執行鎖 | 只有 `test_single_run_lock_blocks_overlap` 紅 | 同一台機器正在跑 `make media-picks`(Mac 平日 23:00 排程),測試拿到的是真的鎖;等它跑完再重跑 |

- `.env` 有兩條漏入路徑:任何較早跑的測試呼叫 `load_dotenv()`;以及 `market_data/tests/conftest.py` 在收集期就把 `DATABASE_URL` 寫進行程且不還原——所以全量裡連的是本機真實庫,單跑 `tests/` 底下的檔則沒有。
- 單測 timeout 直接打 `pytest` 是 300 秒,經 `ci_gate.sh` 是 120 秒。
- `test_python_version_compat.py` 在本機拿不到 CI 那個 Python 版本時是 **skip 不是 fail**;看到它綠不代表 3.11 已經剖析過。
- 連外與時段兩種要修。`.env` 漏入的「預設值」類假紅是既有問題、CI 綠,真正的修法是隔離 `os.environ`——記錄下來即可,不要順手改。
- **例外:會指向正式資料的鍵不是假紅,是事故。**2026-10-08 全量把 `.env` 的 `STORAGE_DATABASE_URL`(NAS 共用的正式 `dsa` 應用庫)帶進行程,測試只改了 `DATABASE_PATH`,於是告警規則、持倉帳戶、決策信號、LLM 用量等 fixture 全寫進正式庫,還改到一筆真實訊號;症狀只是一個告警測試卡在連新浪。現已由 conftest 擋住;**以後 `.env` 新增任何指向正式服務的 URL/金鑰,要在 conftest 照樣中和**,別等它漏。`DATABASE_URL` 不會被清空；`market_data/tests` 獨立執行時由自己的 fixture 用 rollback 保護，與 `tests/` 共同收集時仍會套用上述正式庫 engine 守門。
