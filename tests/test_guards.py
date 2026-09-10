# -*- coding: utf-8 -*-
"""guards.py 兩支守門函式的單元測試。

每支都測兩個方向：**該擋的要擋、不該擋的不能擋**。

「不該擋」那半邊比「該擋」重要。守門誤報的後果是把一篇正確的文案退回修正輪，
兩輪額度燒完之後照樣不出貨（main.py 的收斂失敗處置是「完全不出貨」），
而且錯誤訊息會指向一個根本不存在的問題。

這是本專案第一批 pytest：在守門函式抽到 guards.py 之前，
要測它們就得載入 main.py，而那會連帶拉進 fastf1 與 google.genai、
並在模組層建立 fastf1_cache/ 與 output/ 目錄。抽出後這個檔案只 import guards。
"""
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import guards  # noqa: E402


@dataclass
class FakeConfig:
    """守門只用到 cfg.platforms，不需要真的 AutoConfig（那在 main.py 裡）。"""

    platforms: List[str] = field(default_factory=lambda: ["FB", "IG"])


def both_tags(body: str) -> str:
    """組一篇有齊全平台分隔標記的文案。"""
    return f"=== FB版 ===\n{body}\n\n=== IG版 ===\n{body}"


# =====================================================================
# validate_post_static：格式與 session 身分
# =====================================================================

class TestValidatePostStatic:
    """不花 API 的第一道守門。"""

    # ---- 不該擋 ----

    @pytest.mark.parametrize("session_code, body", [
        ("Q", "Verstappen 拿下排位賽桿位，優勢明顯。"),
        ("SQ", "衝刺排位由 Norris 奪下首位。"),
        ("S", "衝刺賽由 Piastri 收下勝利。"),
        ("R", "精彩的一場比賽，冠軍實至名歸。"),
    ])
    def test_valid_post_passes(self, session_code, body):
        issues = guards.validate_post_static(both_tags(body), FakeConfig(), session_code)
        assert issues == [], issues

    def test_race_post_may_discuss_pit_stops(self):
        """正賽沒有 forbidden 清單——談進站策略是正常的，不可誤擋。"""
        post = both_tags("兩停策略奏效，第二次進站後直接超上去。")
        assert guards.validate_post_static(post, FakeConfig(), "R") == []

    def test_single_platform_only_needs_its_own_tag(self):
        """只要求一個平台時，不該因為缺另一個平台的標記而報錯。"""
        post = "=== FB版 ===\n排位賽桿位由 Leclerc 奪下。"
        assert guards.validate_post_static(post, FakeConfig(platforms=["FB"]), "Q") == []

    def test_qualifying_wording_alternatives_all_accepted(self):
        """required_any 是「群組內至少一個」，四種寫法都該通過。"""
        for word in ("排位", "桿位", "竿位", "Qualifying"):
            post = both_tags(f"這場{word}的結果值得一看。")
            assert guards.validate_post_static(post, FakeConfig(), "Q") == [], word

    # ---- 該擋 ----

    def test_missing_platform_tag_is_reported(self):
        post = "=== FB版 ===\n排位賽桿位由 Hamilton 奪下。"
        issues = guards.validate_post_static(post, FakeConfig(), "Q")
        assert len(issues) == 1
        assert "=== IG版 ===" in issues[0]

    def test_all_platform_tags_missing_reports_each(self):
        issues = guards.validate_post_static("排位賽桿位。", FakeConfig(), "Q")
        assert len(issues) == 2

    def test_template_echo_is_reported(self):
        """模型把 prompt 的格式說明抄進文案——實測發生過，所以有這道保底。"""
        post = both_tags("Facebook 貼文，約 300~500 字：\n排位賽桿位由 Russell 奪下。")
        issues = guards.validate_post_static(post, FakeConfig(), "Q")
        assert any("prompt" in i for i in issues)

    @pytest.mark.parametrize("forbidden", ["進站", "停站", "undercut", "一停", "兩停"])
    def test_qualifying_must_not_mention_pit_strategy(self, forbidden):
        """排位賽時比賽還沒開始，任何進站用語都是文不對題。"""
        post = both_tags(f"排位賽結束，接下來要看{forbidden}怎麼安排。")
        issues = guards.validate_post_static(post, FakeConfig(), "Q")
        assert any(forbidden in i for i in issues), issues

    def test_qualifying_without_self_identification_is_reported(self):
        post = both_tags("Verstappen 拿下首位，優勢明顯。")
        issues = guards.validate_post_static(post, FakeConfig(), "Q")
        assert any("必須出現" in i for i in issues), issues

    @pytest.mark.parametrize("session_code", ["S", "SQ"])
    def test_sprint_sessions_must_say_sprint(self, session_code):
        post = both_tags("這場比賽由 Alonso 奪冠。")
        issues = guards.validate_post_static(post, FakeConfig(), session_code)
        assert any("衝刺" in i for i in issues), issues

    @pytest.mark.parametrize("forbidden", ["大獎賽冠軍", "分站冠軍", "正賽冠軍"])
    def test_sprint_must_not_claim_grand_prix_win(self, forbidden):
        """衝刺賽的贏家不是分站冠軍——這是最容易被混淆的一點。"""
        post = both_tags(f"衝刺賽落幕，Norris 成為{forbidden}。")
        issues = guards.validate_post_static(post, FakeConfig(), "S")
        assert any(forbidden in i for i in issues), issues

    def test_unknown_session_code_does_not_crash(self):
        """未知 session 代碼走 STATIC_RULES 的預設值，只檢查平台標記。"""
        assert guards.validate_post_static(both_tags("內容"), FakeConfig(), "FP1") == []


# =====================================================================
# factcheck_post_numbers：數字必須能溯源
# =====================================================================

SUMMARY = """
=== 數據摘要 ===
最快單圈 P1 Verstappen 1:29.708
第二名 P2 Norris 1:30.112
進站次數 2
完賽圈數 57
"""


class TestFactcheckPostNumbers:
    """確定性數字查核：每個小數、名次、停站數、圈號都要能對回來源。"""

    # ---- 不該擋 ----

    def test_numbers_copied_from_summary_pass(self):
        post = "最快單圈 1:29.708 由 P1 Verstappen 拿下，P2 是 Norris 的 1:30.112。"
        assert guards.factcheck_post_numbers(post, SUMMARY) == []

    def test_derived_difference_passes(self):
        """1:30.112 − 1:29.708 = 0.404，秒差敘述是合法的。"""
        post = "兩人差距僅 0.404 秒。"
        assert guards.factcheck_post_numbers(post, SUMMARY) == []

    def test_pit_stop_count_from_summary_passes(self):
        for phrasing in ("採兩停策略", "進站 2 次", "2 次進站"):
            assert guards.factcheck_post_numbers(phrasing, SUMMARY) == [], phrasing

    def test_lap_number_matching_finish_laps_passes(self):
        assert guards.factcheck_post_numbers("撐到第 57 圈", SUMMARY) == []

    def test_notes_widen_the_traceable_set(self):
        """有筆記時，溯源集合是「摘要 ∪ 筆記」。"""
        notes = "第 17 圈發生碰撞。"
        post = "第 17 圈的碰撞改變了戰局。"
        assert guards.factcheck_post_numbers(post, SUMMARY) != []          # 沒筆記時該擋
        assert guards.factcheck_post_numbers(post, SUMMARY, notes) == []   # 有筆記時放行

    def test_post_without_any_number_passes(self):
        assert guards.factcheck_post_numbers("一場精彩的比賽。", SUMMARY) == []

    # ---- 該擋 ----

    def test_fabricated_decimal_is_reported(self):
        issues = guards.factcheck_post_numbers("他跑出 1:28.001 的驚人成績。", SUMMARY)
        assert any("28.001" in i for i in issues), issues

    def test_unknown_position_is_reported(self):
        issues = guards.factcheck_post_numbers("P9 的表現令人驚豔。", SUMMARY)
        assert any("P9" in i for i in issues), issues

    def test_wrong_pit_stop_count_is_reported(self):
        issues = guards.factcheck_post_numbers("三停策略是關鍵。", SUMMARY)
        assert any("3" in i for i in issues), issues

    def test_untraceable_lap_number_is_reported(self):
        """實測退稿原因之一：把輪胎壽命或編造的圈號寫成比賽圈數。"""
        issues = guards.factcheck_post_numbers("第 17 圈的進站是轉折點。", SUMMARY)
        assert any("第 17 圈" in i for i in issues), issues

    def test_notes_do_not_authorise_arbitrary_numbers(self):
        """筆記擴大的是溯源集合，不是免檢通行證。"""
        notes = "第 17 圈發生碰撞。"
        issues = guards.factcheck_post_numbers("他在第 42 圈退賽。", SUMMARY, notes)
        assert any("第 42 圈" in i for i in issues), issues

    def test_multiple_problems_all_reported(self):
        post = "P9 的他在第 17 圈以 1:28.001 的成績完成三停。"
        issues = guards.factcheck_post_numbers(post, SUMMARY)
        assert len(issues) >= 4, issues
