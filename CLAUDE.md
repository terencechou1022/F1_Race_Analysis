# F1 賽後社群文案自動化(f1_race_analysis)

F1 賽後自動分析 + FB/IG 社群文案生成器。每場 Q/R/SQ/S 結束後由排程器執行,
自動:偵測賽季與待處理場次 → FastF1 抓數據 → 分析 → 產出 CSV/Excel/摘要/配圖 →
Gemini 生成 FB+IG 文案(三重守門)→ 事實查核報告。使用者複製文案發文。

**單檔架構是刻意的**:`main.py`(~1850 行,53 函式),使用者部署
到排程器時只需複製一個檔案。除非使用者明確要求,不要拆分成多模組。

## 首次接手

先讀 `HANDOFF.md`(專案演進歷程、已修 bug、當前進度與待辦),再跑煙霧測試確認環境。

## 常用指令

```bash
pip install -r requirements.txt
python main.py          # 自動模式(生產執行方式)
python tests/smoke_test.py            # 煙霧測試(離線,不需網路與 API key)
python -W error::FutureWarning tests/smoke_test.py   # 順便驗證無棄用 API
```

執行需要 `Gemini_API_Key.txt` 在腳本同目錄(多把 key 用換行/逗號分隔)。

## 架構地圖(依檔內編號區段)

| 區段 | 內容 |
|---|---|
| 1 | `AutoConfig` dataclass:所有可調參數集中於此 |
| 2 | 工具函式:`fmt_s`/`fmt_val`(None 安全格式化)、`to_seconds`、session 載入 |
| 3 | 自動偵測:`resolve_target_years`(賽季+跨年)、`find_pending_targets`(回溯窗口)、`classify_session_name`(名稱三層分類)、`sanity_check_session_definitions`(啟動自檢) |
| 4 | 三種分析:`mode_fastest` / `mode_strategy`(stint 代表圈)/ `mode_pit`(進站窗口) |
| 4.5 | `check_data_availability`(pre-flight)、`derive_stint_overview`/`derive_pit_counts`/`derive_dnf_entries`(summary 事實推導,一律從原始 laps/results 算)、`factcheck_data`(數據交叉驗證,含對前述推導的相等性查核)、`factcheck_post_numbers`(文案數字溯源,含「第 N 圈」須溯源至完賽圈數)、`write_factcheck_report` |
| 5 | CSV / Excel 輸出 |
| 5.5 | 三種配圖(matplotlib Agg、深色 F1 風格、~1080x1080、英文標籤) |
| 6 | `generate_summary_report`:summary.txt = **文案的唯一事實來源** |
| 7 | Gemini:`load_race_notes`/`sanitize_notes`(賽事筆記:第二級事實來源,截斷/消毒/注入免疫)、`SESSION_FOCUS` 模板(Q/R/SQ/S 各一)、`generate_with_fallback`(模型清單×key 輪詢) |
| 7.5 | 守門:`strip_template_lines`(剝除模型回聲的格式說明)、`STATIC_RULES` + `validate_post_static`(含樣板句保底)、`review_post_llm`(AI 審核員) |
| 8 | `process_one` / `run` 主流程 |

## 不可違反的設計原則(修改任何程式碼前先讀這段)

1. **寧缺勿錯(零容忍)**:寧可不產出,絕不產出錯誤或文不對題的內容。
   任何改動不得弱化:pre-flight 檢查、`factcheck_data` 錯誤即中止、
   守門三關(靜態規則 → 數字溯源 → AI 審核)、重寫上限後拒絕輸出。
2. **summary.txt 是文案第一級事實來源**:文案中每個數字必須能溯源至 summary
   (直接出現或為兩時間之差)。新增任何會寫進文案的數據,必須同步:
   (a) 寫入 summary、(b) 納入 `factcheck_data` 交叉驗證、(c) 確認
   `factcheck_post_numbers` 能驗證它。
   賽事筆記(`notes/`,選用)為**第二級事實來源**:與摘要矛盾時一律摘要優先;
   只可引用不可延伸;筆記內指令性文字一律忽略(注入免疫)。
   有筆記時溯源集合 = summary ∪ notes(見 `docs/notes_feature_spec.md`)。
3. **冪等契約**:`social_post.txt` 存在 = 該場完成。任何失敗路徑都不得
   產生此檔;排程器重複執行必須安全。失敗要留下 `FAILED_gemini.txt` 或
   `[SKIP]` 訊息並可自動重試。
4. **Session 白名單**:只支援 Q/R/SQ/S。新增 session 類型必須同時更新
   `ALLOWED_SESSIONS`、`SESSION_LABEL`、`SESSION_FOCUS`、`SPRINT_WEEKEND_NOTE`、
   `STATIC_RULES`,否則 `sanity_check_session_definitions` 會拒絕啟動(這是刻意的)。
5. **衝刺/正賽絕不混淆**:SQ≠Q、S≠R。改 prompt 模板時保留防混淆條款。
6. **未知寧可跳過並警報**:認不得的 session 名稱 → 跳過 + SESSION_ALERT.txt,
   絕不猜測套模板。
7. **年份不落地**:任何新程式碼不得寫死年份;用 `resolve_target_years` 與
   每場傳遞的 `year` 參數,hashtag 用 `{year}` 佔位符。

## 測試方法(沙箱無法連 F1 計時伺服器,測試全部離線)

- `tests/smoke_test.py` 是既有測試母版:mock `google.genai`(必須在 import
  腳本**之前**注入 `sys.modules`)、以合成 DataFrame 建假 session、
  以 `importlib` 載入腳本模組。
- 假 session 的 `laps` 需要 `pick_drivers`/`pick_fastest` 時,用測試檔內的
  `LapsShim`(繼承 DataFrame)。
- 守門/查核類改動,必測正反兩向:合法內容通過 + 違規內容被退。
- 賽程相關改動可用真實 `fastf1.get_event_schedule(2025)`(僅需一般網路)。
- 一律以 `-W error::FutureWarning` 跑一次,防 pandas 棄用 API 滲入。

## 已知邊界與待辦方向(與使用者確認過的)

- 數字查核管「數字有無依據」,不管「數字接在誰身上」(張冠李戴由 AI 審核員
  負責,非 100%)→ 發文前人工掃一眼是設計內的最後防線,factcheck_report.txt
  就是為此存在。
- 文案只寫數據面(summary 沒有事故/天氣等敘事)。候選功能:讓使用者提供
  「賽事筆記」欄位供 AI 引用——若實作,筆記須標示為使用者提供的事實,
  且不得繞過數字查核。
- `pick_fastest` 與原始最小圈速的差異採方向性判定(快=錯誤/慢=警告),
  因 fastf1 可能排除被判無效的圈——不要改回「不等即錯」。
- 模型清單 `gemini_models` 約每年檢視;若全數下架,FAILED_gemini.txt 會指引。
- 尚未實作:自動發文(刻意不做,人工複查是最後防線)、遙測深度分析
  (`fetch_telemetry` 預設關)。

## 安全

- **絕不 commit `Gemini_API_Key.txt`**(.gitignore 已涵蓋;新增任何含密鑰的
  檔案先加入 .gitignore)。
- `fastf1_cache/`、`output/` 體積大且可重生,不進版控。

## 輸出結構(生產)

```
output/{year}/round_{NN}/{Q|R|SQ|S}/
├── social_post.txt        # 完成標記 + 最終文案(FB版+IG版)
├── summary.txt            # 文案唯一事實來源
├── factcheck_report.txt   # 查核軌跡
├── fastest_laps.csv / strategy_laps.csv / pit_laps.csv / analysis.xlsx
├── chart_*.png            # 配圖(Q/SQ 一張;S 兩張;R 三張)
└── FAILED_gemini.txt / rejected_draft_N.txt   # 僅失敗時存在
output/SESSION_ALERT.txt                        # 僅名稱異動時存在
```
