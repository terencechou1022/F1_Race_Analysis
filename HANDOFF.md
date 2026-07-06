# 交接文件(HANDOFF)


## 專案來歷

`fastf1_batch_gemini.py`(2018–2024 批量分析 + YouTube 講稿),經多輪重構成現在的
`main.py`:萬用賽季、賽後自動化、FB/IG 社群文案、三層事實查核。

使用者是台灣的 F1 社群創作者(FB/IG,繁體中文賽後分析),核心價值觀:
**文不對題與捏造數據零容忍,寧缺勿錯**。整個守門與查核體系都是為此而生。

## 演進時間軸與關鍵決策(為什麼長這樣)

1. **萬用化**:從寫死 2018–2024 → 寫死 2026 → 最終 `year=None` 自動偵測(含 1–2 月跨年
   雙年掃描)+ 回溯窗口 14 天(防首次啟用整季回填燒光 API 額度)。
2. **YouTube 講稿 → FB/IG 文案**:一次 Gemini 呼叫產出 FB 長文 + IG 短文,以
   `=== FB版 === / === IG版 ===` 分隔。
3. **Session 專屬模板**:Q/R/SQ/S 各一套 `SESSION_FOCUS`,衝刺週末額外注入防混淆條款
   (使用者明確要求:衝刺賽絕不能寫成正賽)。FP1–3 被刻意排除(白名單)。
4. **守門三關**(依序):靜態規則 → 確定性數字溯源(`factcheck_post_numbers`)→
   AI 審核員。退稿帶原因重寫,上限 3 次,超過即拒絕輸出並寫 FAILED 標記。
5. **模型 fallback**:gemini-3.5-flash(2026/05 GA)→ 3.1-flash-lite → flash-latest。
   404/下架類錯誤跳模型,429 額度類輪詢 key。
6. **Session 名稱防呆**:精確對照 → 關鍵字啟發式(應付官方改名如 Shootout↔Qualifying)
   → 未知即跳過 + SESSION_ALERT.txt。啟動自檢缺模板即拒絕啟動。
7. **Pre-flight 資料檢查**:「半套資料比沒資料危險」——車手數/圈數門檻,不足視為
   FastF1 上傳中,跳過待重試。
8. **配圖**:最快圈比較(全 session)、名次變化(R/S)、輪胎策略甘特(R)。
   ~1080x1080 深色 F1 風,英文標籤(避免排程主機無中文字型)。

## 已修復的重大 bug(不要走回頭路)

| Bug | 修法 | 教訓 |
|---|---|---|
| 進站次數灌水 ~2 倍(in-lap+out-lap 各算一次) | 以 PitInTime 非空圈計數 | summary 的數字會進文案,源頭錯全錯 |
| Windows 主控台 cp950 印 `✓` 直接 UnicodeEncodeError 中止 | 啟動時 stdout/stderr `reconfigure(errors="replace")` | 開發環境印得出來≠部署環境印得出來 |
| summary stint 數漏掉「無有效圈速的 stint」(賽末 SC 換胎),與進站次數自相矛盾 | stints/用胎順序改由原始 laps 推導(`derive_stint_overview`)+ factcheck 相等性查核 | 分析用篩選後統計 ≠ 事實陳述,寫進 summary 的事實要從原始資料推導 |
| 退賽開進 pit lane / pit lane 起跑 out-lap 被誤計為進站(ALB 5→6、衝刺 0→1) | `derive_pit_counts`:排除末圈 in-lap 與首圈 out-lap;0 停不列入 Pit Impact | 邊界案例(SC/退賽/pit 起跑)要用真實資料逐車手回歸 |
| 模型把 prompt 格式說明(「Facebook 貼文,約 300~500 字:」)抄進文案 | `strip_template_lines` 後處理剝除 + 靜態規則保底退稿 | prompt 的結構說明都可能被回聲,雙保險 |
| 跨年掃描時警報檔被第二年覆蓋 | 警報改由 run() 彙總一次寫入 | 多年份迴圈中不要在迴圈內寫共用檔 |
| `pd.Timestamp.utcnow()` 棄用 | `pd.Timestamp.now(tz="UTC")` | 測試一律加 `-W error::FutureWarning` |
| 最快圈交叉驗證誤殺(pick_fastest 可能排除被判無效的圈) | 方向性判定:比原始快=錯誤、比原始慢=警告 | **不要改回「不等即錯」** |
| 中文數字停站漏檢(「兩停」「三停」) | `_CN_NUM` 對照併入查核 | 中文語境的 regex 要想到中文數字 |
| 圖例與內容重疊(最快圈圖右下、輪胎圖底部) | 圖例移右上/圖表上方橫排 | 改圖表後要實際 render 目視 |

## 當前狀態(2026-07-06,首次實測完成 + 落差修復完成)

- **實測**:已在使用者本機用真實資料完整跑過——奧地利站 Q/R + 英國站 SQ/S/Q/R
  共六場全數產出(零 FAILED、零 SESSION_ALERT)。守門三關實戰有效:
  S 場與 R 場重跑各有一稿被 AI 審核員以「捏造」退稿後重寫通過。
- **實測落差修復(A/B/D)已完成並驗證**:見上方 bug 表後三列。
  修復後以 `force_rerun=True` 重跑英國站正賽,LEC 顯示 3 stint
  (MEDIUM->HARD->SOFT)與進站 2 次一致;回歸證明兩場正賽完賽者
  進站次數全數不變,變動僅限退賽/pit lane 起跑車手(方向皆為改正)。
- **測試**:`tests/smoke_test.py` 70 項離線檢查全數通過(46 原有 + 16 修正
  A/B/D + 8 DNF 區塊,均含正反兩向)。
- **首次實測觀察點結論**:安全車慢圈通過合理性查核 ✓;賽後改判無時間差問題
  (賽後一天抓已是最終結果)✓;GridPosition=0 視為隊尾起跑正常 ✓;
  文案純秒數格式 ✓;429 輪詢 + 模型 fallback(3.5-flash 免費層 20 次/天
  用盡 → 自動降級 3.1-flash-lite)實戰驗證 ✓。
- **[DNF] 區塊已完成(2026-07-06)**:summary(R/S)新增 `[DNF]` 區塊
  (車手/完賽圈數=最大圈號/Status 官方原文),`derive_dnf_entries` 推導、
  查核 6 相等性驗證、`factcheck_post_numbers` 新增「第 N 圈」溯源
  (順帶堵住「第 17 圈」型捏造);prompt 允許「X 於第 N 圈退賽(官方分類:
  Status)」、禁止推斷退賽原因(寫作規則 + SESSION_FOCUS R + AI 審核員三處)。
  force_rerun 英國正賽驗證:文案正確寫出 VER/ALB/HUL 三位退賽(圈數+官方
  Status,無原因推斷)。
- **注意**:名次變化圖上 DNF 與單純掉名次仍無法區分(圖層未動,只有 summary
  與文案層有 DNF 資訊)。

## 待辦(與使用者確認過的優先序)

1. **「賽事筆記」欄位**(候選功能):summary 只有數據,沒有事故/天氣等
   敘事,文案因此偏乾。構想:使用者提供一段賽事筆記供 AI 引用。**實作約束**:筆記須在
   prompt 中標示為使用者提供之事實、不得繞過數字查核、AI 審核員需同時比對筆記與摘要。
2. 文風微調:守門保證「不會錯」,「寫得好」要看實測文案後調 `SESSION_FOCUS` 與平台規格。
3. `gemini_models` 清單約每年檢視一次(2026-07-06 實測:3.5-flash 免費層
   額度極緊,20 次/天,一個衝刺週末就會觸頂降級)。

## 與使用者協作的方式

- 一律以繁體中文(台灣用語)回覆。
- 使用者重視主動確認:動手前先確認理解一致,有資訊落差就問。
- 修改守門/查核相關程式碼時,必附正反兩向測試(合法通過 + 違規被退),
  並跑 `python -W error::FutureWarning tests/smoke_test.py`。
