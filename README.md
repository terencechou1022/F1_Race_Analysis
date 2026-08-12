# F1_Race_Analysis

F1 賽後自動分析 + FB/IG 社群文案生成器(萬用賽季版)。

每場排位賽 / 正賽 / 衝刺賽結束後執行,自動產出:分析數據(CSV/Excel)、
文字摘要、發文配圖(PNG)、以及經過三重守門與事實查核的 FB + IG 文案。

## 快速開始

```bash
pip install -r requirements.txt
# 把 Gemini API key 貼進 Gemini_API_Key.txt(多把 key 用換行分隔)
python main.py
```

預設為自動模式:自動偵測目前賽季、找出「最近完賽但未處理」的場次。
建議掛上排程器於比賽日每 2 小時執行(冪等設計,重複執行不浪費 API 額度)。

## 系統架構

```mermaid
flowchart TB
    F1["FastF1 官方計時資料<br/>+ fastf1_cache 本機快取"]
    CFG["AutoConfig<br/>所有可調參數集中於此"]
    NOTE["notes/ 賽事筆記<br/>選用,第二級事實來源"]
    KEY["Gemini_API_Key.txt<br/>可放多把 key"]

    subgraph MAIN["main.py — 單檔管線(刻意不拆模組)"]
        direction TB
        S3["§3 自動偵測<br/>賽季 · 待處理場次 · 名稱分類"]
        S4["§4 三種分析<br/>fastest · strategy · pit"]
        S45["§4.5 pre-flight + 數據層事實查核<br/>事實一律從原始 laps 推導"]
        S5["§5 CSV / Excel · §5.5 配圖 PNG"]
        S6["§6 summary.txt<br/>文案第一級事實來源"]
        S7["§7 文案生成<br/>四套 session 模板 + 筆記區塊"]
        S75["§7.5 守門三關<br/>靜態規則 · 數字溯源 · AI 審核員"]
        S3 --> S4 --> S45 --> S5 --> S6 --> S7 --> S75
    end

    GEM["Gemini API<br/>gemini-flash-latest 滾動別名<br/>寫手 + 審核員,模型 × key 輪詢"]

    subgraph OUT["output/年份/Round_NN_大獎賽/場次代碼/"]
        FILES["summary.txt · *.csv<br/>analysis.xlsx · chart_*.png"]
        REP["factcheck_report.txt<br/>發文前人工複查"]
        POST["social_post.txt<br/>完成標記 = 冪等契約"]
        BAD["FAILED_gemini.txt<br/>rejected_draft_N.txt"]
    end

    WEB["app.py(Flask,選用)<br/>不 import main.py"]
    USER(["使用者:複查後複製文案發文"])

    F1 --> S3
    CFG --> S3
    NOTE --> S7
    KEY --> S7
    S7 -->|"prompt"| GEM
    GEM -->|"草稿文案"| S75
    S75 -->|"退稿重寫"| S7
    S5 --> FILES
    S45 --> REP
    S75 --> POST
    S75 -->|"守門未過"| BAD
    WEB -.->|"子行程 python main.py"| S3
    OUT --> WEB
    POST --> USER
    REP --> USER
```

資料只往一個方向流:**原始資料 → summary.txt → 文案**。文案裡的每個數字都必須
能溯源回 summary(或賽事筆記),這條線是整個系統的核心約束。

## 執行流程

```mermaid
flowchart TD
    A(["python main.py"]) --> B{"啟動自檢<br/>session 定義齊全?"}
    B -->|"缺模板或規則"| B1["拒絕啟動(刻意設計)"]
    B -->|"通過"| C["自動偵測待處理場次<br/>賽季(1-2 月連去年掃)· 完賽 2 小時緩衝 · 7 天回溯窗口"]
    C --> E{"該場 social_post.txt<br/>已存在?"}
    E -->|"是"| E1["跳過:不重跑,不耗 API 額度"]
    E -->|"否"| F["safe_session_load<br/>FastF1 抓取"]
    F --> G{"pre-flight<br/>資料完整?"}
    G -->|"不完整,疑似還在上傳"| G1["本場跳過,下次執行自動重試"]
    G -->|"完整"| H["三種分析 → CSV / Excel"]
    H --> I{"factcheck_data<br/>產出 vs 原始 laps 交叉驗證"}
    I -->|"有錯誤"| I1["中止本場:寫查核報告,絕不進文案"]
    I -->|"通過(警告僅記錄)"| K["配圖 PNG + summary.txt<br/>summary = 唯一事實來源"]
    K --> M["Gemini 生成文案<br/>摘要 + session 模板 + 筆記(若有)<br/>404 換模型 · 429 換 key"]
    M --> N["strip_template_lines<br/>剝除模型抄來的格式說明"]
    N --> O{"守門一:靜態規則<br/>身分關鍵字 / 禁字 / 樣板句"}
    O -->|"退稿"| R
    O -->|"通過"| P{"守門二:數字溯源<br/>秒數 / 名次 / 停站數 / 圈數"}
    P -->|"退稿"| R
    P -->|"通過"| Q{"守門三:AI 審核員<br/>比對摘要與筆記"}
    Q -->|"退稿"| R["rejected_draft_N.txt<br/>問題回饋給模型重寫"]
    Q -->|"通過"| S["寫入 social_post.txt<br/>+ factcheck_report.txt"]
    R --> T{"重寫次數用盡?"}
    T -->|"否"| M
    T -->|"是"| U["寧缺勿錯:不產出文案<br/>寫 FAILED_gemini.txt,重跑自動重試"]
    S --> V(["人工複查查核報告 → 複製文案發文"])
```

每一條「跳過 / 中止」的分支都不會留下 `social_post.txt`,所以重複執行永遠安全:
資料還沒上齊、額度用盡、守門退稿,下次跑就自動重試。

## 網頁介面(選用)

```bash
python app.py
```

開啟 http://127.0.0.1:5000(僅本機):瀏覽所有場次產出、
FB/IG 文案一鍵複製、檢視配圖與事實查核報告、一鍵觸發執行並看即時 log。

## 賽事筆記(選用)

summary 只有數據,沒有事故/天氣/罰時等敘事。想讓文案提到這些,
在專案根目錄建 `notes/{年份}_round{站次兩位數}_{場次代碼}.txt`,
例如英國站正賽:`notes/2026_round09_R.txt`(場次代碼:Q / R / SQ / S)。

```
VER 於 Stowe 彎撞車,引發末段安全車。
比賽最後在安全車下結束。
Antonelli 因前輪擋板故障失速。
Antonelli 賽後被加罰 5 秒。
Leclerc 拿下銀石首勝。
```

適合寫:事故與退賽原因、天氣、安全車/紅旗時機、罰時、你自己的觀點。

**寫作指引:一行一個事實**。避免用「並」「因此」或逗號在同一行串接多件事;
想表達因果就明確寫出(「A 導致 B」),沒寫因果的並列事實,AI 會被禁止自行連成因果。

反例(一行塞兩件事,AI 會焊成因果):

```
Antonelli 因前輪擋板故障失速,賽後被加罰 5 秒。
→ 文案寫成「因前輪擋板故障失速被加罰 5 秒」(把故障當成罰時的原因,筆記並沒有這麼說)
```

規則(系統會強制執行):

- 筆記是**第二級事實來源**:與數據摘要矛盾時,一律以摘要為準。
- AI 只會引用筆記寫明的事實,不會延伸推論;筆記裡的指令性文字會被忽略。
- 上限 2000 字元,超過會截斷並在查核報告標注。
- 筆記全文會引錄在 `factcheck_report.txt` 的 [5] 區段,發文前可核對。

**改筆記後想重生文案**:刪除該場的 `social_post.txt` 再跑一次,
或以 `force_rerun=True` 執行(已產出的場次預設會跳過,這是冪等設計)。

## 測試

```bash
python tests/smoke_test.py    # 單元:分析管線與守門
python tests/e2e_test.py      # 端到端:全管線 + 產出比對查核
python tests/webapp_test.py   # 網頁介面
```

皆為離線執行,不需網路與 API key。

## 開發

本專案以 Claude Code 維護。架構、設計原則與不可違反的規則見 `CLAUDE.md`。
