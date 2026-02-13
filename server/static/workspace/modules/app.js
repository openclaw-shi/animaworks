// ── App Entry Point ──────────────────────
// Initialization, screen switching, and event delegation.

import { getState, setState, subscribe } from "./state.js";
import { fetchSystemStatus } from "./api.js";
import { connect, onEvent } from "./websocket.js";
import { initLogin, getCurrentUser, logout } from "./login.js";
import { initPerson, loadPersons, selectPerson, renderPersonSelector, renderStatus } from "./person.js";
import { renderChat, initChat, sendMessage, addMessage, loadConversation } from "./chat.js";
import { initMemory, loadMemoryTab } from "./memory.js";
import { initSession, loadSessions } from "./session.js";
import { escapeHtml } from "./utils.js";
import { initOffice, disposeOffice, getDesks, highlightDesk, clearHighlight, setCharacterClickHandler, getScene, registerClickTarget, unregisterClickTarget, setCharacterUpdateHook } from "./office3d.js";
import { initCharacters, createCharacter, removeCharacter, updateCharacterState, updateAllCharacters, getCharacterMeshes, disposeCharacters } from "./character.js";
import { initBustup, disposeBustup, setCharacter, setExpression, setTalking, onClick as onBustupClick } from "./live2d.js";

// ── DOM References ──────────────────────

const dom = {};

function cacheDom() {
  dom.loginContainer = document.getElementById("wsLogin");
  dom.dashboard = document.getElementById("wsDashboard");
  dom.personSelector = document.getElementById("wsPersonSelector");
  dom.systemStatus = document.getElementById("wsSystemStatus");
  dom.userInfo = document.getElementById("wsUserInfo");
  dom.chatPanel = document.getElementById("wsChatPanel");
  dom.rightTabs = document.getElementById("wsRightTabs");
  dom.tabState = document.getElementById("wsTabState");
  dom.tabActivity = document.getElementById("wsTabActivity");
  dom.tabHistory = document.getElementById("wsTabHistory");
  dom.paneState = document.getElementById("wsPaneState");
  dom.paneActivity = document.getElementById("wsPaneActivity");
  dom.paneHistory = document.getElementById("wsPaneHistory");
  dom.memoryPanel = document.getElementById("wsMemoryPanel");
  dom.logoutBtn = document.getElementById("wsLogoutBtn");

  // Phase 2-3 DOM refs
  dom.viewTabs = document.getElementById("wsViewTabs");
  dom.viewChat = document.getElementById("wsViewChat");
  dom.viewOffice = document.getElementById("wsViewOffice");
  dom.officePanel = document.getElementById("wsOfficePanel");
  dom.officeCanvas = document.getElementById("wsOfficeCanvas");
  dom.conversationOverlay = document.getElementById("wsConversationOverlay");
  dom.convClose = document.getElementById("wsConvClose");
  dom.convStatus = document.getElementById("wsConvStatus");
  dom.convPersonName = document.getElementById("wsConvPersonName");
  dom.convBrain = document.getElementById("wsConvBrain");
  dom.convLocation = document.getElementById("wsConvLocation");
  dom.convTask = document.getElementById("wsConvTask");
  dom.convActions = document.getElementById("wsConvActions");
  dom.convCanvas = document.getElementById("wsConvCanvas");
  dom.convSpeaker = document.getElementById("wsConvSpeaker");
  dom.convText = document.getElementById("wsConvText");
  dom.convInput = document.getElementById("wsConvInput");
  dom.convSend = document.getElementById("wsConvSend");
}

// ── Activity Feed ──────────────────────

const TYPE_ICONS = {
  heartbeat: "\uD83D\uDC93",
  cron: "\u23F0",
  chat: "\uD83D\uDCAC",
  system: "\u2699\uFE0F",
};

function addActivity(type, personName, summary) {
  if (!dom.paneActivity) return;

  const now = new Date();
  const ts = now.toLocaleTimeString("ja-JP", { hour: "2-digit", minute: "2-digit" });
  const icon = TYPE_ICONS[type] || "\u2022";

  const entry = document.createElement("div");
  entry.className = "activity-entry";
  entry.innerHTML = `
    <span class="activity-time">${ts}</span>
    <span class="activity-icon">${icon}</span>
    <span class="activity-person">${escapeHtml(personName)}</span>
    <span class="activity-summary">${escapeHtml(summary)}</span>`;

  dom.paneActivity.prepend(entry);

  // Cap at 200 entries
  while (dom.paneActivity.children.length > 200) {
    dom.paneActivity.removeChild(dom.paneActivity.lastChild);
  }
}

// ── Right Panel Tabs ──────────────────────

function activateRightTab(tab) {
  setState({ activeRightTab: tab });

  [dom.tabState, dom.tabActivity, dom.tabHistory].forEach((btn) => {
    btn?.classList.toggle("active", btn.dataset.tab === tab);
  });

  [dom.paneState, dom.paneActivity, dom.paneHistory].forEach((pane) => {
    if (pane) pane.style.display = pane.dataset.pane === tab ? "" : "none";
  });

  if (tab === "history") {
    loadSessions();
  }
}

// ── View Mode Switching ──────────────────────

function switchView(mode) {
  setState({ viewMode: mode });

  // Update tab buttons
  [dom.viewChat, dom.viewOffice].forEach((btn) => {
    btn?.classList.toggle("active", btn.dataset.view === mode);
  });

  if (mode === "chat") {
    dom.chatPanel?.classList.remove("hidden");
    dom.officePanel?.classList.add("hidden");
  } else if (mode === "office") {
    dom.chatPanel?.classList.add("hidden");
    dom.officePanel?.classList.remove("hidden");
    initOfficeIfNeeded();
  }
}

async function initOfficeIfNeeded() {
  if (getState().officeInitialized) return;
  setState({ officeInitialized: true });

  try {
    // Initialize 3D scene
    initOffice(dom.officeCanvas);

    // Initialize characters in the scene
    const scene = getScene();
    initCharacters(scene);

    // Register character animation update in the render loop
    setCharacterUpdateHook(updateAllCharacters);

    // Create characters for all known persons
    // Desk keys are role-based; map person names to desk positions by index
    const desks = getDesks();
    const deskKeys = Object.keys(desks);
    const { persons } = getState();
    for (let i = 0; i < persons.length; i++) {
      const p = persons[i];
      const deskKey = deskKeys[i % deskKeys.length];
      const deskPos = desks[deskKey];
      if (deskPos) {
        const group = createCharacter(p.name, { x: deskPos.x, y: deskPos.y + 0.4, z: deskPos.z - 0.3 });
        if (group) {
          // Register for raycasting
          group.traverse((child) => {
            if (child.isMesh) {
              registerClickTarget(p.name, child);
            }
          });
        }
        // Set initial animation state
        const animState = mapPersonStatusToAnim(p.status);
        updateCharacterState(p.name, animState);
      }
    }

    // Handle character clicks
    setCharacterClickHandler((personName) => {
      selectPerson(personName);
      openConversation(personName);
    });

    // Highlight selected person's desk
    const { selectedPerson } = getState();
    if (selectedPerson) {
      highlightDesk(selectedPerson);
    }
  } catch (err) {
    console.error("[office] Failed to initialize 3D office:", err);
    setState({ officeInitialized: false });
  }
}

function mapPersonStatusToAnim(status) {
  if (!status) return "idle";
  const s = typeof status === "object" ? status.state || status.status || "idle" : String(status);
  const lower = s.toLowerCase();
  if (lower.includes("think") || lower.includes("process")) return "thinking";
  if (lower.includes("work") || lower.includes("busy") || lower.includes("running")) return "working";
  if (lower.includes("error") || lower.includes("fail")) return "error";
  if (lower.includes("sleep") || lower.includes("stop") || lower.includes("inactive")) return "sleeping";
  if (lower.includes("talk") || lower.includes("chat")) return "talking";
  if (lower.includes("report")) return "reporting";
  return "idle";
}

// ── Conversation Overlay ──────────────────────

let bustupInitialized = false;
let convStreamController = null;

function openConversation(personName) {
  if (!dom.conversationOverlay) return;

  setState({ conversationOverlay: true, conversationPerson: personName });
  dom.conversationOverlay.classList.remove("hidden");

  // Update person name display
  if (dom.convPersonName) dom.convPersonName.textContent = personName;
  if (dom.convSpeaker) dom.convSpeaker.textContent = personName;
  if (dom.convText) dom.convText.textContent = "…";

  // Initialize bust-up canvas (once)
  if (!bustupInitialized && dom.convCanvas) {
    initBustup(dom.convCanvas);
    bustupInitialized = true;

    onBustupClick(() => {
      // Character clicked — show surprised, then revert
      setExpression("surprised");
      setTimeout(() => setExpression("happy"), 1200);
      setTimeout(() => setExpression("normal"), 2500);
    });
  }

  // Set character and expression
  setCharacter(personName);
  setExpression("normal");

  // Update status panel
  updateConversationStatus(personName);
}

function closeConversation() {
  if (!dom.conversationOverlay) return;
  dom.conversationOverlay.classList.add("hidden");
  setState({ conversationOverlay: false, conversationPerson: null });
  setTalking(false);

  // Abort any active stream
  if (convStreamController) {
    convStreamController.abort();
    convStreamController = null;
  }
}

async function updateConversationStatus(personName) {
  const { personDetail, persons } = getState();
  const person = persons.find((p) => p.name === personName);

  if (dom.convBrain) {
    dom.convBrain.textContent = personDetail?.execution_mode || "Mode A1 (Claude)";
  }
  if (dom.convLocation) {
    dom.convLocation.textContent = "localhost:18500";
  }
  if (dom.convTask) {
    const taskInfo = personDetail?.state;
    dom.convTask.textContent = taskInfo
      ? (typeof taskInfo === "object" ? JSON.stringify(taskInfo, null, 1) : String(taskInfo))
      : "待機中";
  }
  if (dom.convActions) {
    dom.convActions.textContent = "—";
  }
}

/**
 * Parse SSE events from a buffer, properly associating event types with data payloads.
 * Uses "\n\n" as the block delimiter (standard SSE format).
 * @param {string} buffer - Raw SSE text
 * @returns {{ parsed: Array<{event: string, data: Object}>, remaining: string }}
 */
function parseConvSSE(buffer) {
  const parsed = [];
  const parts = buffer.split("\n\n");
  const remaining = parts.pop() || "";

  for (const part of parts) {
    if (!part.trim()) continue;
    let eventName = "message";
    const dataLines = [];
    for (const line of part.split("\n")) {
      if (line.startsWith("event: ")) {
        eventName = line.slice(7).trim();
      } else if (line.startsWith("data: ")) {
        dataLines.push(line.slice(6));
      }
    }
    if (dataLines.length > 0) {
      try {
        parsed.push({ event: eventName, data: JSON.parse(dataLines.join("\n")) });
      } catch { /* skip non-JSON data */ }
    }
  }
  return { parsed, remaining };
}

async function sendConversationMessage() {
  const text = dom.convInput?.value?.trim();
  if (!text) return;

  const personName = getState().conversationPerson;
  if (!personName) return;

  // Clear input
  dom.convInput.value = "";
  dom.convInput.disabled = true;
  dom.convSend.disabled = true;

  // Show user message briefly
  if (dom.convSpeaker) dom.convSpeaker.textContent = getCurrentUser() || "You";
  if (dom.convText) dom.convText.textContent = text;

  // Start talking animation
  setExpression("normal");

  // Create AbortController for cancellable streaming
  convStreamController = new AbortController();

  try {
    // Use SSE streaming
    const userName = getCurrentUser() || "guest";
    const resp = await fetch(`/api/persons/${encodeURIComponent(personName)}/chat/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, from_person: userName }),
      signal: convStreamController.signal,
    });

    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);

    if (dom.convSpeaker) dom.convSpeaker.textContent = personName;
    if (dom.convText) dom.convText.textContent = "";

    setTalking(true);
    setExpression("normal");

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let fullText = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const { parsed, remaining } = parseConvSSE(buffer);
      buffer = remaining;

      for (const { event: evt, data } of parsed) {
        if (evt === "text_delta" && data.text) {
          fullText += data.text;
          if (dom.convText) dom.convText.textContent = fullText;
        } else if (evt === "tool_start") {
          setExpression("thinking");
        } else if (evt === "tool_end") {
          setExpression("normal");
        } else if (evt === "done") {
          setExpression("happy");
          setTimeout(() => setExpression("normal"), 2000);
        } else if (evt === "error") {
          setExpression("troubled");
          if (data.error || data.message) {
            fullText += `\n[エラー: ${data.error || data.message}]`;
            if (dom.convText) dom.convText.textContent = fullText;
          }
        }
      }
    }

    setTalking(false);

    // Sync to main chat via direct state push (avoids streaming guard in addMessage)
    const { chatMessages } = getState();
    setState({
      chatMessages: [
        ...chatMessages,
        { role: "user", text },
        { role: "assistant", text: fullText },
      ],
    });
  } catch (err) {
    if (err.name === "AbortError") return; // User closed overlay
    console.error("[conversation] Stream error:", err);
    if (dom.convText) dom.convText.textContent = `エラー: ${err.message}`;
    setExpression("troubled");
    setTalking(false);
  } finally {
    convStreamController = null;
    if (dom.convInput) dom.convInput.disabled = false;
    if (dom.convSend) dom.convSend.disabled = false;
    dom.convInput?.focus();
  }
}

// ── System Status ──────────────────────

async function loadSystemStatus() {
  if (!dom.systemStatus) return;
  try {
    const data = await fetchSystemStatus();
    updateStatusDisplay(
      data.scheduler_running,
      `${data.scheduler_running ? "稼働中" : "停止"} (${data.persons}名)`
    );
  } catch {
    updateStatusDisplay(false, "接続失敗");
  }
}

function updateStatusDisplay(ok, text) {
  if (!dom.systemStatus) return;
  const dot = dom.systemStatus.querySelector(".status-dot");
  const label = dom.systemStatus.querySelector(".status-text");
  if (dot) dot.className = `status-dot ${ok ? "status-idle" : "status-error"}`;
  if (label) label.textContent = text;
}

// ── WebSocket Handlers ──────────────────────

const wsUnsubscribers = [];

function setupWebSocket() {
  // Clean up previous handlers
  wsUnsubscribers.forEach((fn) => fn());
  wsUnsubscribers.length = 0;

  connect();

  wsUnsubscribers.push(onEvent("person.status", (data) => {
    const { persons, selectedPerson } = getState();
    const idx = persons.findIndex((p) => p.name === data.name);
    if (idx >= 0) {
      persons[idx] = { ...persons[idx], ...data };
      setState({ persons: [...persons] });
      renderPersonSelector(dom.personSelector);
    }
    if (data.name === selectedPerson) {
      renderStatus(dom.paneState);
    }
    // Update 3D character animation
    if (getState().officeInitialized) {
      const animState = mapPersonStatusToAnim(data.status);
      updateCharacterState(data.name, animState);
      setState({ characterStates: { ...getState().characterStates, [data.name]: animState } });
    }
    // Update conversation overlay expression
    if (getState().conversationPerson === data.name) {
      const animState = mapPersonStatusToAnim(data.status);
      if (animState === "error") setExpression("troubled");
      else if (animState === "working") setExpression("thinking");
    }
    addActivity("system", data.name, `Status: ${data.status}`);
  }));

  wsUnsubscribers.push(onEvent("person.heartbeat", (data) => {
    addActivity("heartbeat", data.name, data.summary || "heartbeat completed");
    const { selectedPerson } = getState();
    if (data.name === selectedPerson) {
      renderStatus(dom.paneState);
    }
  }));

  wsUnsubscribers.push(onEvent("person.cron", (data) => {
    addActivity("cron", data.name, data.summary || `cron: ${data.job || ""}`);
  }));

  wsUnsubscribers.push(onEvent("chat.response", (data) => {
    const personName = data.person || data.name;
    const msg = data.response || data.message || "";
    const { selectedPerson } = getState();
    if (personName === selectedPerson) {
      addMessage("assistant", msg);
    }
    addActivity("chat", personName, msg.slice(0, 60));
  }));

  // Track connection state for status indicator
  wsUnsubscribers.push(subscribe((state) => {
    if (state.wsConnected) {
      updateStatusDisplay(true, `接続済 (${state.persons.length}名)`);
    } else {
      updateStatusDisplay(false, "再接続中...");
    }
  }));
}

// ── Dashboard Bootstrap ──────────────────────

let dashboardInitialized = false;

async function startDashboard() {
  if (!dom.dashboard) return;

  // Show dashboard, update user info
  dom.dashboard.classList.remove("hidden");
  if (dom.userInfo) {
    dom.userInfo.textContent = getCurrentUser() || "";
  }

  if (dashboardInitialized) {
    // Re-login: just refresh data
    await loadPersons();
    await loadSystemStatus();
    return;
  }
  dashboardInitialized = true;

  // Initialize sub-modules
  initPerson(dom.personSelector, dom.paneState, onPersonSelected);
  renderChat(dom.chatPanel);
  initChat(dom.chatPanel);
  initMemory(dom.memoryPanel);
  initSession(dom.paneHistory);

  // Bind right-panel tabs
  [dom.tabState, dom.tabActivity, dom.tabHistory].forEach((btn) => {
    btn?.addEventListener("click", () => activateRightTab(btn.dataset.tab));
  });

  // Bind view mode tabs
  [dom.viewChat, dom.viewOffice].forEach((btn) => {
    btn?.addEventListener("click", () => switchView(btn.dataset.view));
  });

  // Bind conversation overlay events
  dom.convClose?.addEventListener("click", closeConversation);
  dom.convSend?.addEventListener("click", sendConversationMessage);
  dom.convInput?.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
      e.preventDefault();
      sendConversationMessage();
    }
  });

  // Close conversation overlay with Escape
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && getState().conversationOverlay) {
      closeConversation();
    }
  });

  // Bind logout
  dom.logoutBtn?.addEventListener("click", () => {
    dom.dashboard.classList.add("hidden");
    logout();
  });

  // Load data
  await loadPersons();
  await loadSystemStatus();

  // Connect WebSocket
  setupWebSocket();

  // Activate default right tab
  activateRightTab("state");
}

// ── Person Selection Callback ──────────────────────

async function onPersonSelected(name) {
  // Update 3D office highlight
  if (getState().officeInitialized) {
    highlightDesk(name);
  }

  // Load conversation + memory + sessions in parallel
  await Promise.all([
    loadConversation(),
    loadMemoryTab(getState().activeMemoryTab),
    loadSessions(),
  ]);
}

// ── Main Init ──────────────────────

export function init() {
  cacheDom();

  const savedUser = getCurrentUser();
  if (savedUser) {
    // Already logged in — render login (hidden) and go to dashboard
    initLogin(dom.loginContainer, onLoginSuccess);
    startDashboard();
  } else {
    // Show login screen
    dom.dashboard?.classList.add("hidden");
    initLogin(dom.loginContainer, onLoginSuccess);
  }
}

function onLoginSuccess(_username) {
  startDashboard();
}

// Auto-init on DOM ready
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
