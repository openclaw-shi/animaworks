/* ── Memory Browser ────────────────────────── */

import { state, dom, escapeHtml } from "./state.js";
import { api } from "./api.js";

export function activateMemoryTab(tab) {
  state.activeMemoryTab = tab;
  document.querySelectorAll(".memory-tab").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.tab === tab);
  });
  // Hide content detail, show list
  dom.memoryContentArea.style.display = "none";
  dom.memoryFileList.style.display = "";
  loadMemoryTab(tab);
}

export async function loadMemoryTab(tab) {
  const name = state.selectedPerson;
  if (!name) {
    dom.memoryFileList.innerHTML = '<div class="loading-placeholder">パーソンを選択してください</div>';
    return;
  }

  dom.memoryFileList.innerHTML = '<div class="loading-placeholder">読み込み中...</div>';

  let endpoint;
  if (tab === "episodes") endpoint = `/api/persons/${encodeURIComponent(name)}/episodes`;
  else if (tab === "knowledge") endpoint = `/api/persons/${encodeURIComponent(name)}/knowledge`;
  else endpoint = `/api/persons/${encodeURIComponent(name)}/procedures`;

  try {
    const data = await api(endpoint);
    const files = data.files || [];
    if (files.length === 0) {
      dom.memoryFileList.innerHTML = '<div class="loading-placeholder">ファイルがありません</div>';
      return;
    }
    dom.memoryFileList.innerHTML = files.map((f) =>
      `<div class="memory-file-item" data-file="${escapeHtml(f)}" data-tab="${tab}">${escapeHtml(f)}</div>`
    ).join("");

    dom.memoryFileList.querySelectorAll(".memory-file-item").forEach((item) => {
      item.addEventListener("click", () => {
        loadMemoryContent(item.dataset.tab, item.dataset.file);
      });
    });
  } catch (err) {
    console.error("Failed to load memory files:", err);
    dom.memoryFileList.innerHTML = '<div class="loading-placeholder">読み込み失敗</div>';
  }
}

async function loadMemoryContent(tab, file) {
  const name = state.selectedPerson;
  if (!name) return;

  let endpoint;
  if (tab === "episodes") endpoint = `/api/persons/${encodeURIComponent(name)}/episodes/${encodeURIComponent(file)}`;
  else if (tab === "knowledge") endpoint = `/api/persons/${encodeURIComponent(name)}/knowledge/${encodeURIComponent(file)}`;
  else endpoint = `/api/persons/${encodeURIComponent(name)}/procedures/${encodeURIComponent(file)}`;

  dom.memoryFileList.style.display = "none";
  dom.memoryContentArea.style.display = "";
  dom.memoryContentTitle.textContent = file;
  dom.memoryContentBody.textContent = "読み込み中...";

  try {
    const data = await api(endpoint);
    dom.memoryContentBody.textContent = data.content || "(内容なし)";
  } catch (err) {
    dom.memoryContentBody.textContent = `[エラー] ${err.message}`;
  }
}
