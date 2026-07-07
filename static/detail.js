// 詳情頁:文案一鍵複製
function copyText(btn) {
  navigator.clipboard.writeText(btn.dataset.text).then(() => {
    const old = btn.textContent; btn.textContent = "已複製 ✓";
    setTimeout(() => { btn.textContent = old; }, 1500);
  });
}
