# f1_race_analysis

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

## 測試

```bash
python tests/smoke_test.py
```

離線執行,不需網路與 API key。

## 開發

