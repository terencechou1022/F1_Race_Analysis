# -*- coding: utf-8 -*-
"""文案守門:不呼叫 API、不碰網路的確定性檢查。

從 main.py 抽出來的原因有兩個:

1. **可獨立引用。** main.py 在模組層就 import fastf1 與 google.genai、
   建立 fastf1_cache/ 與 output/ 目錄。這兩支守門函式本身完全不需要那些東西——
   一個只看字串樣式、一個只做數字溯源。抽出來之後,單元測試
   能只載入這個模組。
2. **可單獨測試。** 兩者都是純函式(輸入字串、輸出問題清單),
   tests/test_guards.py 對每支都測「該擋」與「不該擋」兩個方向。

行為與抽出前完全相同,只是換了檔案。main.py 改為從這裡 import。
"""
from typing import Any, Dict, List, Protocol

import re


class _HasPlatforms(Protocol):
    """validate_post_static 只用到 cfg.platforms。

    不直接 import main.AutoConfig:那會造成循環匯入,
    而且守門邏輯本來就只需要「有 platforms 這個屬性」這一個條件。
    """

    platforms: List[str]


SESSION_LABEL = {"Q": "排位賽", "R": "正賽", "S": "衝刺賽", "SQ": "衝刺排位"}


# ---- [需求2·文案層] 貼文數字查核 ----

_DECIMAL_RE = re.compile(r"\d+\.\d{1,3}")


def _extract_decimals(text: str) -> List[float]:
    return [float(x) for x in _DECIMAL_RE.findall(text)]


def _extract_stop_claims(text: str) -> set:
    """抓「N停」「進站N次」「N次進站」宣稱(含中文數字:一停/兩停/三停...)。"""
    _CN_NUM = {"一": "1", "二": "2", "兩": "2", "三": "3", "四": "4", "五": "5"}
    stops = set(re.findall(r"(\d+)\s*停(?!站)", text))
    stops |= set(re.findall(r"進站\s*(\d+)\s*次", text))
    stops |= set(re.findall(r"(\d+)\s*次進站", text))
    for cn, dig in _CN_NUM.items():
        if re.search(rf"{cn}\s*停(?!站)", text) or re.search(rf"進站\s*{cn}\s*次", text) \
                or re.search(rf"{cn}\s*次進站", text):
            stops.add(dig)
    return stops


def factcheck_post_numbers(post: str, summary_text: str, notes_text: str = "") -> List[str]:
    """
    [需求2·文案層] 確定性數字查核(不靠 AI):
    - 文案中每個小數(秒數)必須「直接出現在來源」或
      「等於來源中兩個時間相減的差」(容許 ±0.002s,涵蓋合法的秒差敘述)
    - 文案中的名次(P幾)必須出現在來源
    - 文案中的進站次數(N停 / 進站N次)必須與來源一致
    - 文案中的「第 N 圈」必須溯源至摘要「完賽圈數 N」或筆記中的「第 N 圈」
    [賽事筆記] 溯源集合 = summary ∪ notes(notes_text 預設空字串,
    無筆記時行為與加入筆記功能前完全一致)。
    回傳問題清單,空 = 通過。
    """
    issues: List[str] = []
    src_label = "摘要+筆記" if notes_text else "摘要"
    src_text = summary_text + ("\n" + notes_text if notes_text else "")
    s_nums = _extract_decimals(src_text)

    for x in _extract_decimals(post):
        direct = any(abs(x - s) <= 0.0015 for s in s_nums)
        derived = any(abs(abs(a - b) - x) <= 0.003 for i, a in enumerate(s_nums)
                      for b in s_nums[i + 1:])
        if not (direct or derived):
            issues.append(
                f"文案中的數字 {x} 在{src_label}中找不到依據(也不是任兩個時間之差),"
                f"疑似捏造,請改用{src_label}中的實際數據或刪除"
            )

    post_pos = set(re.findall(r"[PpＰ](\d{1,2})\b", post))
    summ_pos = set(re.findall(r"P(\d{1,2})\b", src_text))
    for p in sorted(post_pos - summ_pos, key=int):
        issues.append(f"文案提到名次 P{p},但{src_label}中沒有這個名次,請核對")

    # 進站次數:摘要的「進站次數 N」+ 筆記中的停站宣稱皆為合法來源
    post_stops = _extract_stop_claims(post)
    summ_stops = set(re.findall(r"進站次數\s*(\d+)", summary_text))
    if notes_text:
        summ_stops |= _extract_stop_claims(notes_text)
    for c in sorted(post_stops - summ_stops, key=int):
        issues.append(f"文案提到「{c} 停/進站 {c} 次」,但{src_label}中沒有依據")

    # [C·DNF 區塊] 圈號引用:「第 N 圈」必須溯源至摘要的「完賽圈數 N」
    # 或筆記中明寫的「第 N 圈」。堵住「第 17 圈」型捏造——把輪胎壽命
    # 或編造的圈號寫成比賽圈數(首次實測 S 場退稿原因之一)。
    summ_laps = set(re.findall(r"完賽圈數\s*(\d+)", summary_text))
    if notes_text:
        summ_laps |= set(re.findall(r"第\s*(\d+)\s*圈", notes_text))
    post_laps = set(re.findall(r"第\s*(\d+)\s*圈", post))
    for n in sorted(post_laps - summ_laps, key=int):
        issues.append(f"文案提到「第 {n} 圈」,但{src_label}中沒有可溯源的圈號,請刪除或改寫")

    return issues



# 各 session 的硬規則:
# required_any = 每個群組中「至少一個」關鍵字必須出現(自我標示身分)
# forbidden    = 絕不可出現的字(不屬於此 session 的概念)
STATIC_RULES: Dict[str, Dict[str, Any]] = {
    # 排位賽:比賽還沒開始,任何進站/停站策略用語都是文不對題
    "Q":  {"required_any": [["排位", "桿位", "竿位", "Qualifying"]],
           "forbidden": ["進站", "停站", "undercut", "Undercut", "UNDERCUT",
                         "overcut", "Overcut", "換胎策略", "一停", "兩停", "三停"]},
    # 衝刺排位:必須自我標示為「衝刺」,同樣不得談進站
    "SQ": {"required_any": [["衝刺"]],
           "forbidden": ["進站", "停站", "undercut", "Undercut", "正賽桿位"]},
    # 衝刺賽:必須自我標示為「衝刺」,不得自稱大獎賽冠軍
    "S":  {"required_any": [["衝刺"]],
           "forbidden": ["大獎賽冠軍", "分站冠軍", "正賽冠軍"]},
    # 正賽:無硬性關鍵字(內容查核交給 AI 審核員)
    "R":  {"required_any": [], "forbidden": []},
}


# [實測修正D] 模型偶爾把 prompt 的平台格式說明抄進文案開頭
# (如「Facebook 貼文,約 300~500 字:」)。雙保險:
# 1. strip_template_lines 後處理剝除獨立成行的已知樣板句
# 2. validate_post_static 保底:內文仍殘留樣板句 → 退稿
_TEMPLATE_ECHO_LINE_RE = re.compile(r"^\s*(Facebook|Instagram)\s*貼文[^\n]{0,15}字\s*[::]?\s*$")
_TEMPLATE_ECHO_ANY_RE = re.compile(r"(Facebook|Instagram)\s*貼文[^\n]{0,15}字")


def strip_template_lines(post: str) -> str:
    """後處理:剝除模型抄進文案、獨立成行的 prompt 格式說明。"""
    lines = [ln for ln in post.splitlines() if not _TEMPLATE_ECHO_LINE_RE.match(ln)]
    return "\n".join(lines).strip()


def validate_post_static(post: str, cfg: _HasPlatforms, session_code: str) -> List[str]:
    """第一道守門:不花 API 的規則檢查。回傳問題清單,空 = 通過。"""
    issues: List[str] = []

    # [實測修正D保底] prompt 格式說明殘留(剝除後仍在,例如混進句子裡)
    if _TEMPLATE_ECHO_ANY_RE.search(post):
        issues.append("文案殘留 prompt 的格式說明(如「Facebook 貼文,約 300~500 字:」),"
                      "不要輸出任何說明文字,只輸出貼文內容")

    # 格式:平台分隔標記必須齊全,否則無法複製貼上
    for p in cfg.platforms:
        tag = f"=== {p.upper()}版 ==="
        if tag not in post:
            issues.append(f"缺少分隔標記「{tag}」,格式不符無法直接複製")

    label = SESSION_LABEL.get(session_code, session_code)
    rules = STATIC_RULES.get(session_code, {"required_any": [], "forbidden": []})
    for group in rules["required_any"]:
        if not any(kw in post for kw in group):
            issues.append(
                f"這是{label}文案,必須出現 {group} 其中之一以標明賽事類型,目前都沒有"
            )
    for kw in rules["forbidden"]:
        if kw in post:
            issues.append(f"這是{label}文案,不得出現「{kw}」(該概念不屬於{label})")

    return issues
