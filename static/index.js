// 首頁:觸發 main.py 執行與即時 log 輪詢
const btn = document.getElementById("runbtn");
const msg = document.getElementById("runmsg");
const logEl = document.getElementById("runlog");
let timer = null;

async function poll() {
  const r = await fetch("/run/log"); const d = await r.json();
  logEl.style.display = "block";
  logEl.textContent = d.lines.join("\n");
  logEl.scrollTop = logEl.scrollHeight;
  if (!d.running) {
    clearInterval(timer); timer = null;
    btn.disabled = false;
    msg.textContent = d.returncode === 0 ? "執行完成,重新整理頁面查看新場次" : "執行結束(exit code " + d.returncode + ")";
  }
}
async function startRun() {
  const r = await fetch("/run", {method: "POST"});
  if (!r.ok) { msg.textContent = (await r.json()).error || "觸發失敗"; return; }
  btn.disabled = true; msg.textContent = "執行中…";
  timer = setInterval(poll, 2000); poll();
}
// 頁面載入時若已在執行,接上進度
fetch("/run/log").then(r => r.json()).then(d => {
  if (d.running) { btn.disabled = true; msg.textContent = "執行中…"; timer = setInterval(poll, 2000); poll(); }
});
