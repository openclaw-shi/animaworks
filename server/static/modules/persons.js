/* ── Person Dropdown, Selection, Avatar ────── */

import { state, dom, escapeHtml } from "./state.js";
import { api } from "./api.js";
import { renderChat } from "./chat.js";
import { loadMemoryTab } from "./memory.js";
import { hideHistoryDetail, loadSessionList } from "./history.js";

export async function loadPersons() {
  try {
    state.persons = await api("/api/persons");
    renderPersonDropdown();
    if (state.persons.length > 0 && !state.selectedPerson) {
      selectPerson(state.persons[0].name);
    }
  } catch (err) {
    console.error("Failed to load persons:", err);
  }
}

export function renderPersonDropdown() {
  const dropdown = dom.personDropdown;

  let html = '<option value="" disabled>パーソンを選択...</option>';
  for (const p of state.persons) {
    const statusLabel = p.status ? ` (${p.status})` : "";
    const selected = p.name === state.selectedPerson ? " selected" : "";
    html += `<option value="${escapeHtml(p.name)}"${selected}>${escapeHtml(p.name)}${statusLabel}</option>`;
  }
  dropdown.innerHTML = html;
}

export async function selectPerson(name) {
  state.selectedPerson = name;

  // Update dropdown
  dom.personDropdown.value = name;

  // Enable chat
  dom.chatInput.disabled = false;
  dom.chatSendBtn.disabled = false;
  dom.chatInput.placeholder = `${name} にメッセージ...`;

  // Pre-populate chat with server-side conversation history if empty
  if (!state.chatHistories[name] || state.chatHistories[name].length === 0) {
    try {
      const conv = await api(`/api/persons/${encodeURIComponent(name)}/conversation/full?limit=20`);
      if (conv.turns && conv.turns.length > 0) {
        state.chatHistories[name] = conv.turns.map((t) => ({
          role: t.role === "human" ? "user" : "assistant",
          text: t.content,
        }));
      }
    } catch { /* silent fail - chat starts empty */ }
  }

  // Render chat history
  renderChat();

  // Load detail
  try {
    state.personDetail = await api(`/api/persons/${encodeURIComponent(name)}`);
    renderPersonState();
    loadMemoryTab(state.activeMemoryTab);
  } catch (err) {
    console.error("Failed to load person detail:", err);
    state.personDetail = null;
    dom.personStateContent.textContent = "詳細の読み込み失敗";
    dom.memoryFileList.innerHTML = '<div class="loading-placeholder">詳細の読み込み失敗</div>';
  }

  // Load session list if history tab is active
  if (state.activeRightTab === "history") {
    hideHistoryDetail();
    loadSessionList();
  }

  // Update avatar thumbnail
  updatePersonAvatar();
}

// ── Person Avatar ───────────────────────────

export async function updatePersonAvatar() {
  const container = dom.personAvatar;
  if (!container) return;

  const name = state.selectedPerson;
  if (!name) {
    container.innerHTML = "";
    return;
  }

  // Try bust-up first, then chibi
  const candidates = ["avatar_bustup.png", "avatar_chibi.png"];
  for (const filename of candidates) {
    const url = `/api/persons/${encodeURIComponent(name)}/assets/${encodeURIComponent(filename)}`;
    try {
      const resp = await fetch(url, { method: "HEAD" });
      if (resp.ok) {
        container.innerHTML = `<img src="${escapeHtml(url)}" alt="${escapeHtml(name)}" class="person-avatar-img">`;
        return;
      }
    } catch { /* try next */ }
  }

  // Fallback: initial letter
  container.innerHTML = `<div class="person-avatar-placeholder">${escapeHtml(name.charAt(0).toUpperCase())}</div>`;
}

// ── Person State ───────────────────────────

export function renderPersonState() {
  const d = state.personDetail;
  if (!d || !d.state) {
    dom.personStateContent.textContent = "状態情報なし";
    return;
  }
  const stateText = typeof d.state === "string" ? d.state : JSON.stringify(d.state, null, 2);
  dom.personStateContent.textContent = stateText;
}

export async function refreshSelectedPerson() {
  if (!state.selectedPerson) return;
  try {
    state.personDetail = await api(`/api/persons/${encodeURIComponent(state.selectedPerson)}`);
    renderPersonState();
  } catch {
    // Silently ignore refresh errors
  }
}
