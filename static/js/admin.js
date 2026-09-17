document.addEventListener('click', async (event) => {
  const btn = event.target.closest('[data-copy]');
  if (!btn) return;
  try {
    await navigator.clipboard.writeText(btn.dataset.copy);
    const old = btn.textContent;
    btn.textContent = '已复制';
    setTimeout(() => btn.textContent = old, 1200);
  } catch (_) {
    alert('复制失败，请手动复制');
  }
});
