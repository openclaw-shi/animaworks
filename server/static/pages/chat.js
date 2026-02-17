// ── Chat Page (Self-Contained) ──────────────
import { api } from "../modules/api.js";
import { escapeHtml, renderMarkdown, timeStr } from "../modules/state.js";
import { streamChat } from "../shared/chat-stream.js";
import { createLogger } from "../shared/logger.js";

const logger = createLogger("chat-page");

// ── Local State ────────────────────────────

let _container = null;
let _animas = [];
let _selectedAnima = null;
let _chatHistories = {};
let _animaDetail = null;
let _activeRightTab = "state";
let _activeMemoryTab = "episodes";
let _intervals = [];
let _boundListeners = [];

// ── DOM refs (local) ───────────────────────

function _$(id) { return document.getElementById(id); }

// ── Render ─────────────────────────────────

export function render(container) {
  _container = container;
  _animas = [];
  _selectedAnima = null;
  _chatHistories = {};
  _animaDetail = null;
  _activeRightTab = "state";
  _activeMemoryTab = "episodes";
  _intervals = [];
  _boundListeners = [];

  container.innerHTML = `
    <div style="display:flex; gap:1rem; height:calc(100vh - 140px); min-height:400px;">
      <!-- Left: Chat Panel -->
      <div style="flex:1; display:flex; flex-direction:column; min-width:0;">
        <!-- Anima Selector -->
        <div style="display:flex; align-items:center; gap:0.75rem; padding:0.75rem; border-bottom:1px solid var(--border-color, #eee);">
          <div id="chatPageAvatar" class="anima-avatar-container"></div>
          <select id="chatPageAnimaSelect" class="anima-dropdown" style="flex:1;">
            <option value="" disabled selected>Animaを選択...</option>
          </select>
        </div>

        <!-- Chat Messages -->
        <div id="chatPageMessages" class="chat-messages" style="flex:1; overflow-y:auto; padding:1rem;">
          <div class="chat-empty">Animaを選択してチャットを開始</div>
        </div>

        <!-- Chat Input -->
        <form id="chatPageForm" class="chat-input-form" style="padding:0.75rem; border-top:1px solid var(--border-color, #eee);">
          <textarea
            id="chatPageInput"
            class="chat-input"
            placeholder="メッセージを入力... (Ctrl+Enter で送信)"
            autocomplete="off"
            rows="1"
            disabled
          ></textarea>
          <button type="submit" class="chat-send-btn" id="chatPageSendBtn" disabled>送信</button>
        </form>
      </div>

      <!-- Right: Sidebar -->
      <div style="width:340px; flex-shrink:0; display:flex; flex-direction:column; border-left:1px solid var(--border-color, #eee); overflow:hidden;">
        <!-- Right tabs -->
        <nav class="right-tabs" style="display:flex; border-bottom:1px solid var(--border-color, #eee);">
          <button class="right-tab active" data-tab="state" id="chatTabState">現在の状態</button>
          <button class="right-tab" data-tab="activity" id="chatTabActivity">アクティビティ</button>
          <button class="right-tab" data-tab="history" id="chatTabHistory">会話履歴</button>
        </nav>

        <div id="chatRightTabContent" style="flex:1; overflow-y:auto; padding:0.75rem;">
          <!-- State pane (default) -->
          <div id="chatPaneState">
            <pre class="state-content" id="chatAnimaState" style="white-space:pre-wrap; word-break:break-word; margin:0;">Animaを選択してください</pre>
          </div>
          <!-- Activity pane -->
          <div id="chatPaneActivity" style="display:none;">
            <div id="chatActivityFeed" class="activity-feed">
              <div class="activity-empty">イベントを待機中...</div>
            </div>
          </div>
          <!-- History pane -->
          <div id="chatPaneHistory" style="display:none;">
            <div id="chatHistorySessionList">
              <div class="loading-placeholder">Animaを選択してください</div>
            </div>
            <div id="chatHistoryDetail" style="display:none;">
              <button class="memory-back-btn" id="chatHistoryBackBtn">&larr; 一覧に戻る</button>
              <h3 id="chatHistoryDetailTitle" style="margin:0.5rem 0;"></h3>
              <div id="chatHistoryConversation" style="max-height:400px; overflow-y:auto;"></div>
            </div>
          </div>
        </div>

        <!-- Memory Browser -->
        <div style="border-top:1px solid var(--border-color, #eee); max-height:40%; display:flex; flex-direction:column;">
          <nav class="memory-tabs" style="display:flex; border-bottom:1px solid var(--border-color, #eee);">
            <button class="memory-tab active" data-tab="episodes">エピソード</button>
            <button class="memory-tab" data-tab="knowledge">知識</button>
            <button class="memory-tab" data-tab="procedures">手順書</button>
          </nav>
          <div id="chatMemoryFileList" class="memory-file-list" style="flex:1; overflow-y:auto; padding:0.5rem;">
            <div class="loading-placeholder">Animaを選択してください</div>
          </div>
          <div id="chatMemoryContentArea" style="display:none; flex:1; overflow-y:auto; padding:0.5rem;">
            <button class="memory-back-btn" id="chatMemoryBackBtn">&larr; 一覧に戻る</button>
            <h3 id="chatMemoryContentTitle" style="margin:0.5rem 0;"></h3>
            <pre id="chatMemoryContentBody" class="memory-content-body" style="white-space:pre-wrap; word-break:break-word;"></pre>
          </div>
        </div>
      </div>
    </div>
  `;

  _bindEvents();
  _loadAnimas();

  // Auto-refresh activity
  const actInterval = setInterval(_loadActivity, 30000);
  _intervals.push(actInterval);
}

export function destroy() {
  for (const id of _intervals) clearInterval(id);
  _intervals = [];
  for (const { el, event, handler } of _boundListeners) {
    el.removeEventListener(event, handler);
  }
  _boundListeners = [];
  _container = null;
  _animas = [];
  _selectedAnima = null;
  _chatHistories = {};
  _animaDetail = null;
}

// ── Event Binding ──────────────────────────

function _bindEvents() {
  // Anima selector
  _addListener("chatPageAnimaSelect", "change", (e) => {
    const name = e.target.value;
    if (name) _selectAnima(name);
  });

  // Chat form submit
  _addListener("chatPageForm", "submit", (e) => {
    e.preventDefault();
    _submitChat();
  });

  // Textarea: Ctrl+Enter
  _addListener("chatPageInput", "keydown", (e) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      _submitChat();
    }
  });

  // Auto-resize textarea
  _addListener("chatPageInput", "input", () => {
    const el = _$("chatPageInput");
    if (el) {
      el.style.height = "auto";
      el.style.height = Math.min(el.scrollHeight, 200) + "px";
    }
  });

  // Right tab switching
  for (const tabId of ["chatTabState", "chatTabActivity", "chatTabHistory"]) {
    _addListener(tabId, "click", (e) => {
      const tab = e.target.dataset.tab;
      _switchRightTab(tab);
    });
  }

  // Memory tabs
  _container.querySelectorAll(".memory-tab").forEach(btn => {
    const handler = () => {
      _activeMemoryTab = btn.dataset.tab;
      _container.querySelectorAll(".memory-tab").forEach(b => b.classList.toggle("active", b.dataset.tab === _activeMemoryTab));
      const contentArea = _$("chatMemoryContentArea");
      const fileList = _$("chatMemoryFileList");
      if (contentArea) contentArea.style.display = "none";
      if (fileList) fileList.style.display = "";
      _loadMemoryTab();
    };
    btn.addEventListener("click", handler);
    _boundListeners.push({ el: btn, event: "click", handler });
  });

  // Memory back button
  _addListener("chatMemoryBackBtn", "click", () => {
    const contentArea = _$("chatMemoryContentArea");
    const fileList = _$("chatMemoryFileList");
    if (contentArea) contentArea.style.display = "none";
    if (fileList) fileList.style.display = "";
  });

  // History back button
  _addListener("chatHistoryBackBtn", "click", () => {
    const detail = _$("chatHistoryDetail");
    const list = _$("chatHistorySessionList");
    if (detail) detail.style.display = "none";
    if (list) list.style.display = "";
  });
}

function _addListener(id, event, handler) {
  const el = _$(id);
  if (el) {
    el.addEventListener(event, handler);
    _boundListeners.push({ el, event, handler });
  }
}

// ── Anima Selection ───────────────────────

async function _loadAnimas() {
  try {
    _animas = await api("/api/animas");
    _renderAnimaDropdown();
    if (_animas.length > 0 && !_selectedAnima) {
      _selectAnima(_animas[0].name);
    }
  } catch (err) {
    logger.error("Failed to load animas", err);
  }
}

function _renderAnimaDropdown() {
  const select = _$("chatPageAnimaSelect");
  if (!select) return;

  let html = '<option value="" disabled>Animaを選択...</option>';
  for (const p of _animas) {
    const selected = p.name === _selectedAnima ? " selected" : "";
    if (p.status === "bootstrapping" || p.bootstrapping) {
      html += `<option value="${escapeHtml(p.name)}"${selected} disabled>\u23F3 ${escapeHtml(p.name)} (制作中...)</option>`;
    } else if (p.status === "not_found" || p.status === "stopped") {
      html += `<option value="${escapeHtml(p.name)}"${selected}>\uD83D\uDCA4 ${escapeHtml(p.name)} (停止中)</option>`;
    } else {
      const statusLabel = p.status ? ` (${p.status})` : "";
      html += `<option value="${escapeHtml(p.name)}"${selected}>${escapeHtml(p.name)}${statusLabel}</option>`;
    }
  }
  select.innerHTML = html;
}

async function _selectAnima(name) {
  _selectedAnima = name;

  const select = _$("chatPageAnimaSelect");
  if (select) select.value = name;

  const input = _$("chatPageInput");
  const sendBtn = _$("chatPageSendBtn");
  if (input) { input.disabled = false; input.placeholder = `${name} にメッセージ...`; }
  if (sendBtn) sendBtn.disabled = false;

  // Load conversation history + anima detail in parallel
  const needConv = !_chatHistories[name] || _chatHistories[name].length === 0;
  const convPromise = needConv
    ? api(`/api/animas/${encodeURIComponent(name)}/conversation/full?limit=20`).catch(() => null)
    : Promise.resolve(null);
  const detailPromise = api(`/api/animas/${encodeURIComponent(name)}`).catch(() => null);

  const [conv, detail] = await Promise.all([convPromise, detailPromise]);

  // Apply conversation history
  if (conv && conv.turns && conv.turns.length > 0) {
    _chatHistories[name] = conv.turns.map(t => ({
      role: t.role === "human" ? "user" : "assistant",
      text: t.content,
    }));
  }

  _renderChat();

  // Apply anima detail
  if (detail) {
    _animaDetail = detail;
    _renderAnimaState();
  } else {
    _animaDetail = null;
    const stateEl = _$("chatAnimaState");
    if (stateEl) stateEl.textContent = "詳細の読み込み失敗";
  }

  // Load secondary data in parallel
  const secondaryPromises = [_updateAvatar(), _loadMemoryTab(), _loadActivity()];
  if (_activeRightTab === "history") secondaryPromises.push(_loadSessionList());
  await Promise.all(secondaryPromises);
}

// ── Avatar ─────────────────────────────────

async function _updateAvatar() {
  const container = _$("chatPageAvatar");
  if (!container || !_selectedAnima) {
    if (container) container.innerHTML = "";
    return;
  }

  const name = _selectedAnima;
  const candidates = ["avatar_bustup.png", "avatar_chibi.png"];
  for (const filename of candidates) {
    const url = `/api/animas/${encodeURIComponent(name)}/assets/${encodeURIComponent(filename)}`;
    try {
      const resp = await fetch(url, { method: "HEAD" });
      if (resp.ok) {
        container.innerHTML = `<img src="${escapeHtml(url)}" alt="${escapeHtml(name)}" class="anima-avatar-img">`;
        return;
      }
    } catch { /* try next */ }
  }
  container.innerHTML = `<div class="anima-avatar-placeholder">${escapeHtml(name.charAt(0).toUpperCase())}</div>`;
}

// ── Chat Rendering ─────────────────────────

function _renderChat() {
  const messagesEl = _$("chatPageMessages");
  if (!messagesEl) return;

  const name = _selectedAnima;
  const history = _chatHistories[name] || [];

  if (history.length === 0) {
    messagesEl.innerHTML = '<div class="chat-empty">メッセージはまだありません</div>';
    return;
  }

  messagesEl.innerHTML = history.map(m => {
    if (m.role === "thinking") {
      return '<div class="chat-bubble thinking"><span class="thinking-animation">考え中</span></div>';
    }
    if (m.role === "assistant") {
      const streamClass = m.streaming ? " streaming" : "";
      let content = "";
      if (m.text) {
        content = renderMarkdown(m.text);
      } else if (m.streaming) {
        content = '<span class="cursor-blink"></span>';
      }
      const toolHtml = m.activeTool
        ? `<div class="tool-indicator"><span class="tool-spinner"></span>${escapeHtml(m.activeTool)} を実行中...</div>`
        : "";
      return `<div class="chat-bubble assistant${streamClass}">${content}${toolHtml}</div>`;
    }
    return `<div class="chat-bubble user">${escapeHtml(m.text)}</div>`;
  }).join("");
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

// ── SSE Streaming Chat ─────────────────────

function _renderStreamingBubble(msg) {
  const messagesEl = _$("chatPageMessages");
  if (!messagesEl) return;
  const bubble = messagesEl.querySelector(".chat-bubble.assistant.streaming");
  if (!bubble) return;

  let html = "";

  if (msg.heartbeatRelay) {
    html += '<div class="heartbeat-relay-indicator"><span class="tool-spinner"></span>ハートビート処理中...</div>';
    if (msg.heartbeatText) {
      html += `<div class="heartbeat-relay-text">${escapeHtml(msg.heartbeatText)}</div>`;
    }
  } else if (msg.text) {
    try { html = marked.parse(msg.text, { breaks: true }); }
    catch { html = escapeHtml(msg.text); }
  } else {
    html = '<span class="cursor-blink"></span>';
  }

  if (msg.activeTool) {
    html += `<div class="tool-indicator"><span class="tool-spinner"></span>${escapeHtml(msg.activeTool)} を実行中...</div>`;
  }

  bubble.innerHTML = html;
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function _submitChat() {
  const input = _$("chatPageInput");
  if (!input) return;
  const msg = input.value.trim();
  if (!msg) return;
  input.value = "";
  input.style.height = "auto";
  _sendChat(msg);
}

async function _sendChat(message) {
  const name = _selectedAnima;
  if (!name || !message.trim()) return;

  // Guard: block sending to bootstrapping animas
  const currentAnima = _animas.find((p) => p.name === name);
  if (currentAnima?.status === "bootstrapping" || currentAnima?.bootstrapping) {
    const msgs = _$("chatPageMessages");
    if (msgs) {
      const systemMsg = document.createElement("div");
      systemMsg.className = "chat-bubble assistant";
      systemMsg.textContent = "このキャラクターは現在制作中です。完了までお待ちください。";
      msgs.appendChild(systemMsg);
      msgs.scrollTop = msgs.scrollHeight;
    }
    return;
  }

  if (!_chatHistories[name]) _chatHistories[name] = [];
  const history = _chatHistories[name];

  history.push({ role: "user", text: message });
  const streamingMsg = { role: "assistant", text: "", streaming: true, activeTool: null };
  history.push(streamingMsg);
  _renderChat();

  const input = _$("chatPageInput");
  const sendBtn = _$("chatPageSendBtn");
  if (input) input.disabled = true;
  if (sendBtn) sendBtn.disabled = true;

  _addLocalActivity("chat", name, `ユーザー: ${message}`);

  try {
    const currentUser = localStorage.getItem("animaworks_user") || "human";
    const body = JSON.stringify({ message, from_person: currentUser });

    await streamChat(name, body, null, {
      onTextDelta: (text) => {
        streamingMsg.text += text;
        _renderStreamingBubble(streamingMsg);
      },
      onToolStart: (toolName) => {
        streamingMsg.activeTool = toolName;
        _renderStreamingBubble(streamingMsg);
      },
      onToolEnd: () => {
        streamingMsg.activeTool = null;
        _renderStreamingBubble(streamingMsg);
      },
      onChainStart: () => {},
      onHeartbeatRelayStart: ({ message }) => {
        streamingMsg.heartbeatRelay = true;
        streamingMsg.heartbeatText = "";
        streamingMsg.text = "";
        _renderStreamingBubble(streamingMsg);
        _addLocalActivity("system", name, `ハートビート中継: ${message}`);
      },
      onHeartbeatRelay: ({ text }) => {
        streamingMsg.heartbeatText = (streamingMsg.heartbeatText || "") + text;
        _renderStreamingBubble(streamingMsg);
      },
      onHeartbeatRelayDone: () => {
        streamingMsg.heartbeatRelay = false;
        streamingMsg.heartbeatText = "";
        streamingMsg.text = "";
        _renderStreamingBubble(streamingMsg);
      },
      onError: ({ message: errorMsg }) => {
        streamingMsg.text += `\n[エラー] ${errorMsg}`;
        streamingMsg.streaming = false;
        _renderChat();
      },
      onDone: ({ summary }) => {
        const text = summary || streamingMsg.text;
        streamingMsg.text = text || "(空の応答)";
        streamingMsg.streaming = false;
        streamingMsg.activeTool = null;
        streamingMsg.heartbeatRelay = false;
        streamingMsg.heartbeatText = "";
        _renderChat();
        _addLocalActivity("chat", name, `応答: ${streamingMsg.text.slice(0, 100)}`);
      },
    });

    // Ensure streaming is finalized if stream ended without done event
    if (streamingMsg.streaming) {
      streamingMsg.streaming = false;
      if (!streamingMsg.text) streamingMsg.text = "(空の応答)";
      _renderChat();
    }
  } catch (err) {
    if (err.name !== "AbortError") {
      logger.error("Chat stream error", { anima: name, error: err.message, name: err.name });
    }
    streamingMsg.text = `[エラー] ${err.message}`;
    streamingMsg.streaming = false;
    streamingMsg.activeTool = null;
    _renderChat();
  } finally {
    if (input) { input.disabled = false; input.focus(); }
    if (sendBtn) sendBtn.disabled = false;
  }
}

// ── Right Tab Switching ────────────────────

function _switchRightTab(tab) {
  _activeRightTab = tab;
  const tabs = { state: "chatPaneState", activity: "chatPaneActivity", history: "chatPaneHistory" };

  for (const btn of (_container?.querySelectorAll(".right-tab") || [])) {
    btn.classList.toggle("active", btn.dataset.tab === tab);
  }
  for (const [key, id] of Object.entries(tabs)) {
    const el = _$(id);
    if (el) el.style.display = key === tab ? "" : "none";
  }

  if (tab === "history" && _selectedAnima) {
    const detail = _$("chatHistoryDetail");
    const list = _$("chatHistorySessionList");
    if (detail) detail.style.display = "none";
    if (list) list.style.display = "";
    _loadSessionList();
  }
  if (tab === "activity") _loadActivity();
}

// ── Anima State ───────────────────────────

function _renderAnimaState() {
  const el = _$("chatAnimaState");
  if (!el) return;

  const d = _animaDetail;
  if (!d || !d.state) {
    el.textContent = "状態情報なし";
    return;
  }
  el.textContent = typeof d.state === "string" ? d.state : JSON.stringify(d.state, null, 2);
}

// ── Activity Feed ──────────────────────────

const _TYPE_ICONS = {
  heartbeat: "\uD83D\uDC93",
  cron: "\u23F0",
  chat: "\uD83D\uDCAC",
  system: "\u2699\uFE0F",
};

function _addLocalActivity(type, animaName, summary) {
  const feed = _$("chatActivityFeed");
  if (!feed) return;

  // Remove empty state
  const empty = feed.querySelector(".activity-empty");
  if (empty) empty.remove();

  const icon = _TYPE_ICONS[type] || _TYPE_ICONS.system;
  const ts = new Date().toLocaleTimeString("ja-JP", { hour: "2-digit", minute: "2-digit", second: "2-digit" });

  const entry = document.createElement("div");
  entry.className = "activity-entry";
  entry.innerHTML = `
    <span class="activity-icon">${icon}</span>
    <span class="activity-time">${ts}</span>
    <div class="activity-body">
      <span class="activity-anima">${escapeHtml(animaName)}</span>
      <span class="activity-summary"> ${escapeHtml(summary)}</span>
    </div>`;
  feed.appendChild(entry);
  feed.scrollTop = feed.scrollHeight;

  while (feed.children.length > 200) {
    feed.removeChild(feed.firstChild);
  }
}

async function _loadActivity() {
  if (!_selectedAnima) return;

  try {
    const data = await api(`/api/activity/recent?hours=6&anima=${encodeURIComponent(_selectedAnima)}`);
    const events = data.events || [];
    const feed = _$("chatActivityFeed");
    if (!feed) return;

    if (events.length === 0) {
      feed.innerHTML = '<div class="activity-empty">アクティビティなし</div>';
      return;
    }

    feed.innerHTML = events.slice(0, 50).map(evt => {
      const icon = _TYPE_ICONS[evt.type] || _TYPE_ICONS.system;
      const ts = timeStr(evt.timestamp);
      const summary = evt.summary || evt.message || "";
      return `
        <div class="activity-entry">
          <span class="activity-icon">${icon}</span>
          <span class="activity-time">${escapeHtml(ts)}</span>
          <div class="activity-body">
            <span class="activity-anima">${escapeHtml(evt.anima || "")}</span>
            <span class="activity-summary"> ${escapeHtml(summary)}</span>
          </div>
        </div>`;
    }).join("");
  } catch {
    // Silent fail — keep existing content
  }
}

// ── History Panel ──────────────────────────

async function _loadSessionList() {
  const list = _$("chatHistorySessionList");
  if (!list || !_selectedAnima) {
    if (list) list.innerHTML = '<div class="loading-placeholder">Animaを選択してください</div>';
    return;
  }

  list.innerHTML = '<div class="loading-placeholder">読み込み中...</div>';

  try {
    const data = await api(`/api/animas/${encodeURIComponent(_selectedAnima)}/sessions`);
    let html = "";

    // Active Conversation
    if (data.active_conversation) {
      const ac = data.active_conversation;
      const lastTime = ac.last_timestamp ? timeStr(ac.last_timestamp) : "--:--";
      html += `
        <div class="session-section-header">現在の会話</div>
        <div class="session-item session-active" data-type="active">
          <div class="session-item-title">進行中の会話</div>
          <div class="session-item-meta">
            ${ac.total_turn_count}ターン ${ac.has_summary ? "(要約あり)" : ""} | 最終: ${lastTime}
          </div>
        </div>`;
    }

    // Archived Sessions
    if (data.archived_sessions && data.archived_sessions.length > 0) {
      html += '<div class="session-section-header">セッションアーカイブ</div>';
      for (const s of data.archived_sessions) {
        const ts = s.timestamp ? timeStr(s.timestamp) : s.id;
        html += `
          <div class="session-item" data-type="archive" data-id="${escapeHtml(s.id)}">
            <div class="session-item-title">${escapeHtml(s.trigger || "セッション")} (${s.turn_count}ターン)</div>
            <div class="session-item-meta">${ts} | ctx: ${(s.context_usage_ratio * 100).toFixed(0)}%</div>
            ${s.original_prompt_preview ? `<div class="session-item-preview">${escapeHtml(s.original_prompt_preview)}</div>` : ""}
          </div>`;
      }
    }

    // Transcripts
    if (data.transcripts && data.transcripts.length > 0) {
      html += '<div class="session-section-header">会話ログ</div>';
      for (const t of data.transcripts) {
        html += `
          <div class="session-item" data-type="transcript" data-date="${escapeHtml(t.date)}">
            <div class="session-item-title">${escapeHtml(t.date)}</div>
            <div class="session-item-meta">${t.message_count}メッセージ</div>
          </div>`;
      }
    }

    // Episodes
    if (data.episodes && data.episodes.length > 0) {
      html += '<div class="session-section-header">エピソードログ</div>';
      for (const e of data.episodes) {
        html += `
          <div class="session-item" data-type="episode" data-date="${escapeHtml(e.date)}">
            <div class="session-item-title">${escapeHtml(e.date)}</div>
            <div class="session-item-preview">${escapeHtml(e.preview)}</div>
          </div>`;
      }
    }

    if (!html) html = '<div class="loading-placeholder">履歴がありません</div>';
    list.innerHTML = html;

    // Bind click handlers
    list.querySelectorAll(".session-item").forEach(item => {
      item.addEventListener("click", () => {
        const type = item.dataset.type;
        if (type === "active") _loadActiveConversation();
        else if (type === "archive") _loadArchivedSession(item.dataset.id);
        else if (type === "transcript") _loadTranscript(item.dataset.date);
        else if (type === "episode") _loadEpisode(item.dataset.date);
      });
    });
  } catch (err) {
    list.innerHTML = `<div class="loading-placeholder">読み込み失敗: ${escapeHtml(err.message)}</div>`;
  }
}

function _showHistoryDetail(title) {
  const list = _$("chatHistorySessionList");
  const detail = _$("chatHistoryDetail");
  const titleEl = _$("chatHistoryDetailTitle");
  if (list) list.style.display = "none";
  if (detail) detail.style.display = "";
  if (titleEl) titleEl.textContent = title;
}

async function _loadActiveConversation() {
  if (!_selectedAnima) return;
  _showHistoryDetail("進行中の会話");
  const conv = _$("chatHistoryConversation");
  if (conv) conv.innerHTML = '<div class="loading-placeholder">読み込み中...</div>';

  try {
    const data = await api(`/api/animas/${encodeURIComponent(_selectedAnima)}/conversation/full?limit=50`);
    _renderConversationDetail(data);
  } catch {
    if (conv) conv.innerHTML = '<div class="loading-placeholder">読み込み失敗</div>';
  }
}

function _renderConversationDetail(data) {
  const conv = _$("chatHistoryConversation");
  if (!conv) return;

  let html = "";
  if (data.has_summary && data.compressed_summary) {
    html += `<div class="history-summary">
      <div class="history-summary-label">要約 (${data.compressed_turn_count}ターン分)</div>
      <div class="history-summary-body">${renderMarkdown(data.compressed_summary)}</div>
    </div>`;
  }

  if (data.turns && data.turns.length > 0) {
    for (const t of data.turns) {
      const ts = t.timestamp ? timeStr(t.timestamp) : "";
      const bubbleClass = t.role === "assistant" ? "assistant" : "user";
      const roleLabel = t.role === "human" ? "ユーザー" : t.role;
      const content = t.role === "assistant" ? renderMarkdown(t.content) : escapeHtml(t.content);
      html += `
        <div class="history-turn">
          <div class="history-turn-meta">${ts} - ${escapeHtml(roleLabel)}</div>
          <div class="chat-bubble ${bubbleClass}">${content}</div>
        </div>`;
    }
  }

  if (!html) html = '<div class="loading-placeholder">会話データがありません</div>';
  conv.innerHTML = html;
  conv.scrollTop = conv.scrollHeight;
}

async function _loadArchivedSession(sessionId) {
  if (!_selectedAnima) return;
  _showHistoryDetail(`セッション: ${sessionId}`);
  const conv = _$("chatHistoryConversation");
  if (conv) conv.innerHTML = '<div class="loading-placeholder">読み込み中...</div>';

  try {
    const data = await api(`/api/animas/${encodeURIComponent(_selectedAnima)}/sessions/${encodeURIComponent(sessionId)}`);
    if (data.markdown) {
      if (conv) conv.innerHTML = `<div class="history-markdown">${renderMarkdown(data.markdown)}</div>`;
    } else if (data.data) {
      const d = data.data;
      let html = `<div class="history-session-meta">
        <div><strong>トリガー:</strong> ${escapeHtml(d.trigger || "不明")}</div>
        <div><strong>ターン数:</strong> ${d.turn_count || 0}</div>
        <div><strong>コンテキスト使用率:</strong> ${((d.context_usage_ratio || 0) * 100).toFixed(0)}%</div>
      </div>`;
      if (d.original_prompt) {
        html += `<div class="history-section"><div class="history-section-label">依頼内容</div><pre class="history-pre">${escapeHtml(d.original_prompt)}</pre></div>`;
      }
      if (d.accumulated_response) {
        html += `<div class="history-section"><div class="history-section-label">応答</div><div>${renderMarkdown(d.accumulated_response)}</div></div>`;
      }
      if (conv) conv.innerHTML = html;
    } else {
      if (conv) conv.innerHTML = '<div class="loading-placeholder">データがありません</div>';
    }
  } catch {
    if (conv) conv.innerHTML = '<div class="loading-placeholder">読み込み失敗</div>';
  }
}

async function _loadTranscript(date) {
  if (!_selectedAnima) return;
  _showHistoryDetail(`会話ログ: ${date}`);
  const conv = _$("chatHistoryConversation");
  if (conv) conv.innerHTML = '<div class="loading-placeholder">読み込み中...</div>';

  try {
    const data = await api(`/api/animas/${encodeURIComponent(_selectedAnima)}/transcripts/${encodeURIComponent(date)}`);
    _renderConversationDetail(data);
  } catch {
    if (conv) conv.innerHTML = '<div class="loading-placeholder">読み込み失敗</div>';
  }
}

async function _loadEpisode(date) {
  if (!_selectedAnima) return;
  _showHistoryDetail(`エピソード: ${date}`);
  const conv = _$("chatHistoryConversation");
  if (conv) conv.innerHTML = '<div class="loading-placeholder">読み込み中...</div>';

  try {
    const data = await api(`/api/animas/${encodeURIComponent(_selectedAnima)}/episodes/${encodeURIComponent(date)}`);
    if (conv) conv.innerHTML = `<div class="history-markdown">${renderMarkdown(data.content || "(内容なし)")}</div>`;
  } catch {
    if (conv) conv.innerHTML = '<div class="loading-placeholder">読み込み失敗</div>';
  }
}

// ── Memory Browser ─────────────────────────

async function _loadMemoryTab() {
  const fileList = _$("chatMemoryFileList");
  if (!fileList) return;

  if (!_selectedAnima) {
    fileList.innerHTML = '<div class="loading-placeholder">Animaを選択してください</div>';
    return;
  }

  fileList.innerHTML = '<div class="loading-placeholder">読み込み中...</div>';

  const endpoint = `/api/animas/${encodeURIComponent(_selectedAnima)}/${_activeMemoryTab}`;

  try {
    const data = await api(endpoint);
    const files = data.files || [];
    if (files.length === 0) {
      fileList.innerHTML = '<div class="loading-placeholder">ファイルがありません</div>';
      return;
    }

    fileList.innerHTML = files.map(f =>
      `<div class="memory-file-item" data-file="${escapeHtml(f)}" data-tab="${_activeMemoryTab}">${escapeHtml(f)}</div>`
    ).join("");

    fileList.querySelectorAll(".memory-file-item").forEach(item => {
      item.addEventListener("click", () => {
        _loadMemoryContent(item.dataset.tab, item.dataset.file);
      });
    });
  } catch (err) {
    fileList.innerHTML = `<div class="loading-placeholder">読み込み失敗: ${escapeHtml(err.message)}</div>`;
  }
}

async function _loadMemoryContent(tab, file) {
  if (!_selectedAnima) return;

  const fileList = _$("chatMemoryFileList");
  const contentArea = _$("chatMemoryContentArea");
  const titleEl = _$("chatMemoryContentTitle");
  const bodyEl = _$("chatMemoryContentBody");

  if (fileList) fileList.style.display = "none";
  if (contentArea) contentArea.style.display = "";
  if (titleEl) titleEl.textContent = file;
  if (bodyEl) bodyEl.textContent = "読み込み中...";

  const endpoint = `/api/animas/${encodeURIComponent(_selectedAnima)}/${tab}/${encodeURIComponent(file)}`;

  try {
    const data = await api(endpoint);
    if (bodyEl) bodyEl.textContent = data.content || "(内容なし)";
  } catch (err) {
    if (bodyEl) bodyEl.textContent = `[エラー] ${err.message}`;
  }
}
