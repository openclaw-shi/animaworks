/* ============================================
   Digital Person — Dashboard App (Entry Point)
   ============================================ */

import { state, dom } from "./state.js";
import { api } from "./api.js";
import { loadPersons, selectPerson, renderPersonDropdown } from "./persons.js";
import { sendChat } from "./chat.js";
import { activateMemoryTab } from "./memory.js";
import { hideHistoryDetail, loadSessionList } from "./history.js";
import { connectWebSocket } from "./websocket.js";
import { loadSystemStatus } from "./status.js";
import { loginAs, logout, showLoginScreen, hideLoginScreen, setStartDashboard } from "./login.js";

// ── Right Panel Tab Switching ──────────────

function activateRightTab(tab) {
  state.activeRightTab = tab;
  document.querySelectorAll(".right-tab").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.tab === tab);
  });
  document.querySelectorAll(".tab-pane").forEach((pane) => {
    pane.classList.toggle("active", pane.dataset.tab === tab);
  });

  if (tab === "history" && state.selectedPerson) {
    hideHistoryDetail();
    loadSessionList();
  }
}

// ── Textarea Auto-Resize ────────────────────

function autoResizeTextarea() {
  const el = dom.chatInput;
  el.style.height = "auto";
  el.style.height = Math.min(el.scrollHeight, 200) + "px";
}

function submitChat() {
  const msg = dom.chatInput.value.trim();
  if (!msg) return;
  dom.chatInput.value = "";
  dom.chatInput.style.height = "auto";
  sendChat(msg);
}

// ── Event Bindings ─────────────────────────

function bindEvents() {
  // Person dropdown change
  dom.personDropdown.addEventListener("change", (e) => {
    const name = e.target.value;
    if (name) selectPerson(name);
  });

  // Chat form submit
  dom.chatForm.addEventListener("submit", (e) => {
    e.preventDefault();
    submitChat();
  });

  // Textarea: Ctrl+Enter to send, Enter for newline, auto-resize
  dom.chatInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      submitChat();
    }
  });

  dom.chatInput.addEventListener("input", autoResizeTextarea);

  // Right panel tabs (State / Activity / History)
  document.querySelectorAll(".right-tab").forEach((btn) => {
    btn.addEventListener("click", () => {
      activateRightTab(btn.dataset.tab);
    });
  });

  // Memory tabs
  document.querySelectorAll(".memory-tab").forEach((btn) => {
    btn.addEventListener("click", () => {
      activateMemoryTab(btn.dataset.tab);
    });
  });

  // Memory back button
  dom.memoryBackBtn.addEventListener("click", () => {
    dom.memoryContentArea.style.display = "none";
    dom.memoryFileList.style.display = "";
  });

  // History back button
  dom.historyBackBtn.addEventListener("click", hideHistoryDetail);

  // Login: guest button
  dom.guestLoginBtn.addEventListener("click", () => loginAs("human"));

  // Login: logout button
  dom.logoutBtn.addEventListener("click", logout);
}

// ── Init ───────────────────────────────────

async function startDashboard() {
  await loadPersons();
  loadSystemStatus();
  connectWebSocket();
}

// Wire up login -> dashboard callback
setStartDashboard(startDashboard);

async function init() {
  bindEvents();

  if (state.currentUser) {
    hideLoginScreen();
    await startDashboard();
  } else {
    showLoginScreen();
  }

  // Periodic refresh: person list every 30s, system status every 60s
  setInterval(async () => {
    if (!state.currentUser) return;
    try {
      state.persons = await api("/api/persons");
      renderPersonDropdown();
    } catch { /* ignore */ }
  }, 30000);

  setInterval(loadSystemStatus, 60000);
}

// Start when DOM is ready
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
