# -*- coding: utf-8 -*-
"""
F1_Race_Analysis 前端介面(Flask)
==================================

main.py 的本機操作介面,三件事:
1. 瀏覽 output/ 下所有已處理場次(狀態:完成/失敗/未完成)
2. 檢視單場產出:社群文案(FB/IG 一鍵複製)、summary、事實查核報告、配圖
3. 觸發 `python main.py`(背景子行程,即時 log)

檔案結構:本檔只有路由與邏輯;頁面模板在 templates/,CSS/JS 在 static/。

設計原則:
- 不 import main.py:main.py 有模組層副作用(建目錄、載入 fastf1、
  reconfigure stdout),且執行動輒數分鐘;一律以子行程執行,
  與生產排程/手動執行走完全相同的路徑。
- 唯讀為主:本介面不寫任何 output/ 檔案;冪等契約(social_post.txt
  = 完成標記)由 main.py 自己維護。
- 僅綁定 127.0.0.1:本機工具,不對外服務。

啟動:python app.py → http://127.0.0.1:5000
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from flask import Flask, abort, jsonify, render_template, send_from_directory

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"

ALLOWED_SESSIONS = {"Q", "R", "S", "SQ"}
SESSION_LABEL = {"Q": "排位賽", "R": "正賽", "S": "衝刺賽", "SQ": "衝刺排位"}
# 場次目錄內允許透過 /files 存取的檔名(白名單,防路徑跳脫)
FILE_NAME_RE = re.compile(r"^[A-Za-z0-9_\-]+\.(png|csv|xlsx|txt)$")

app = Flask(__name__)


# =========================================================
# output/ 掃描
# =========================================================

def session_status(sdir: Path) -> str:
    """狀態判定與 main.py 冪等契約一致:social_post.txt 存在 = 完成。"""
    if (sdir / "social_post.txt").exists():
        return "done"
    if (sdir / "FAILED_gemini.txt").exists():
        return "failed"
    return "pending"


def read_event_title(sdir: Path) -> str:
    """summary.txt 第一行是「{year} {EventName} - {session.name} (中文標籤)」。"""
    summary = sdir / "summary.txt"
    if summary.exists():
        try:
            first = summary.read_text(encoding="utf-8", errors="replace").splitlines()
            if first:
                return first[0].strip()
        except OSError:
            pass
    return ""


_ROUND_DIR_RE = re.compile(r"round_(\d{2})(?:_.*)?", re.IGNORECASE)


def scan_output() -> List[Dict[str, Any]]:
    """列出 output/{year}/Round_{NN}[_大獎賽名稱]/{code} 全部場次,新的在前。"""
    entries: List[Dict[str, Any]] = []
    if not OUTPUT_DIR.is_dir():
        return entries
    for ydir in sorted(OUTPUT_DIR.iterdir(), reverse=True):
        if not (ydir.is_dir() and re.fullmatch(r"\d{4}", ydir.name)):
            continue
        for rdir in sorted(ydir.iterdir(), reverse=True):
            m = _ROUND_DIR_RE.fullmatch(rdir.name)
            if not (rdir.is_dir() and m):
                continue
            for sdir in sorted(rdir.iterdir()):
                if not (sdir.is_dir() and sdir.name in ALLOWED_SESSIONS):
                    continue
                entries.append({
                    "year": int(ydir.name),
                    "rnd": int(m.group(1)),
                    "code": sdir.name,
                    "label": SESSION_LABEL[sdir.name],
                    "status": session_status(sdir),
                    "title": read_event_title(sdir),
                })
    return entries


def session_dir(year: int, rnd: int, code: str) -> Optional[Path]:
    """找出該站的資料夾(檔名可能帶大獎賽名稱尾綴),找不到回傳 None。"""
    year_dir = OUTPUT_DIR / str(year)
    if not year_dir.is_dir():
        return None
    matches = sorted(year_dir.glob(f"Round_{rnd:02d}*"))
    return (matches[0] / code) if matches else None


def read_text(path: Path) -> Optional[str]:
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8", errors="replace")


def split_post(post_text: str) -> Tuple[str, List[Tuple[str, str]]]:
    """把 social_post.txt 拆成 (產出資訊標頭, [(平台, 內文), ...])。"""
    parts = re.split(r"^===\s*([A-Za-z]+)版\s*===\s*$", post_text, flags=re.M)
    header = parts[0].strip()
    sections = [(parts[i], parts[i + 1].strip()) for i in range(1, len(parts) - 1, 2)]
    return header, sections


# =========================================================
# 執行 main.py(背景子行程,單一併發)
# =========================================================

_run_lock = threading.Lock()
_run_state: Dict[str, Any] = {"running": False, "lines": [], "returncode": None}
_MAX_LOG_LINES = 2000


def _run_main() -> None:
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    try:
        proc = subprocess.Popen(
            [sys.executable, "-u", str(BASE_DIR / "main.py")],
            cwd=str(BASE_DIR),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", env=env,
        )
        for line in proc.stdout:
            with _run_lock:
                _run_state["lines"].append(line.rstrip("\n"))
                if len(_run_state["lines"]) > _MAX_LOG_LINES:
                    del _run_state["lines"][:-_MAX_LOG_LINES]
        proc.wait()
        rc = proc.returncode
    except Exception as e:  # 子行程啟動失敗也要回報到 log,不讓執行緒無聲死亡
        with _run_lock:
            _run_state["lines"].append(f"[app.py] 執行失敗:{e}")
        rc = -1
    with _run_lock:
        _run_state["running"] = False
        _run_state["returncode"] = rc
        _run_state["lines"].append(f"[app.py] main.py 結束(exit code {rc})")


@app.post("/run")
def trigger_run():
    with _run_lock:
        if _run_state["running"]:
            return jsonify({"ok": False, "error": "main.py 正在執行中,請等它跑完"}), 409
        _run_state.update({"running": True, "lines": [], "returncode": None})
    threading.Thread(target=_run_main, daemon=True).start()
    return jsonify({"ok": True})


@app.get("/run/log")
def run_log():
    with _run_lock:
        return jsonify({
            "running": _run_state["running"],
            "returncode": _run_state["returncode"],
            "lines": list(_run_state["lines"]),
        })


# =========================================================
# 頁面(模板在 templates/,CSS/JS 在 static/)
# =========================================================

@app.get("/")
def index():
    return render_template(
        "index.html", entries=scan_output(),
        alert_text=read_text(OUTPUT_DIR / "SESSION_ALERT.txt"),
    )


@app.get("/session/<int:year>/<int:rnd>/<code>")
def session_detail(year: int, rnd: int, code: str):
    if code not in ALLOWED_SESSIONS:
        abort(404)
    sdir = session_dir(year, rnd, code)
    if sdir is None or not sdir.is_dir():
        abort(404)

    post_header, post_sections = "", []
    post_text = read_text(sdir / "social_post.txt")
    if post_text:
        post_header, post_sections = split_post(post_text)

    charts = sorted(p.name for p in sdir.glob("chart_*.png"))
    downloads = sorted(p.name for p in sdir.iterdir()
                       if p.is_file() and p.suffix in (".csv", ".xlsx"))
    rejected = [(p.name, read_text(p)) for p in sorted(sdir.glob("rejected_draft_*.txt"))]

    title = read_event_title(sdir) or f"{year} Round {rnd:02d} {code}"
    return render_template(
        "detail.html", title=title, status=session_status(sdir),
        year=year, rnd=rnd, code=code,
        post_header=post_header, post_sections=post_sections,
        summary_text=read_text(sdir / "summary.txt"),
        factcheck_text=read_text(sdir / "factcheck_report.txt"),
        failed_text=read_text(sdir / "FAILED_gemini.txt"),
        charts=charts, downloads=downloads, rejected=rejected,
    )


@app.get("/files/<int:year>/<int:rnd>/<code>/<filename>")
def serve_file(year: int, rnd: int, code: str, filename: str):
    if code not in ALLOWED_SESSIONS or not FILE_NAME_RE.fullmatch(filename):
        abort(404)
    sdir = session_dir(year, rnd, code)
    if sdir is None or not (sdir / filename).is_file():
        abort(404)
    return send_from_directory(sdir, filename)


if __name__ == "__main__":
    # 本機工具:只綁 127.0.0.1;debug 關閉(reloader 會讓背景執行緒狀態翻倍混亂)
    app.run(host="127.0.0.1", port=5000, debug=False)
