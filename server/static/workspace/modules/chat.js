// ── Chat Module ──────────────────────────────────
// Chat UI + SSE streaming display.

import { getState, setState } from "./state.js";
import { sendChatStream, fetchConversationFull } from "./api.js";
import { escapeHtml, renderSimpleMarkdown } from "./utils.js";
import { parseConvSSE as parseSSEEvents, getErrorMessage } from "../../shared/sse-parser.js";

// ── Constants ──────────────────────────────────

const EMPTY_MSG = "メッセージはまだありません";
const PLACEHOLDER_DEFAULT = "Animaを選択してください";

// ── DOM References ──────────────────────────────

let messagesEl = null;
let inputEl = null;
let sendBtnEl = null;

// ── Render Helpers ──────────────────────────────

function renderBubble(msg) {
  if (msg.role === "user") {
    return `<div class="chat-bubble user">${escapeHtml(msg.text)}</div>`;
  }

  // Assistant bubble
  const streamClass = msg.streaming ? " streaming" : "";
  let content = "";

  if (msg.text) {
    content = renderSimpleMarkdown(msg.text);
  } else if (msg.streaming) {
    content = '<span class="cursor-blink"></span>';
  }

  const toolHtml = msg.activeTool
    ? `<div class="tool-indicator"><span class="tool-spinner"></span>${escapeHtml(msg.activeTool)} を実行中...</div>`
    : "";

  return `<div class="chat-bubble assistant${streamClass}">${content}${toolHtml}</div>`;
}

function renderAllMessages() {
  if (!messagesEl) return;

  const { chatMessages } = getState();

  if (chatMessages.length === 0) {
    messagesEl.innerHTML = `<div class="chat-empty">${EMPTY_MSG}</div>`;
    return;
  }

  messagesEl.innerHTML = chatMessages.map(renderBubble).join("");
  requestAnimationFrame(() => {
    const last = messagesEl.lastElementChild;
    if (last) last.scrollIntoView({ block: "end", behavior: "instant" });
  });
}

// ── Streaming update with rAF throttle ──────────────────────

let _chatRafPending = false;
let _chatLatestStreamingMsg = null;
let _isSseStreaming = false;

function scheduleStreamingUpdate(msg) {
  _chatLatestStreamingMsg = msg;
  if (_chatRafPending) return;
  _chatRafPending = true;
  requestAnimationFrame(() => {
    _chatRafPending = false;
    if (_chatLatestStreamingMsg) {
      updateStreamingBubble(_chatLatestStreamingMsg);
    }
  });
}

function updateStreamingBubble(msg) {
  if (!messagesEl) return;

  const bubble = messagesEl.querySelector(".chat-bubble.assistant.streaming");
  if (!bubble) return;

  let html = "";
  if (msg.text) {
    html = renderSimpleMarkdown(msg.text);
  } else {
    html = '<span class="cursor-blink"></span>';
  }

  if (msg.activeTool) {
    html += `<div class="tool-indicator"><span class="tool-spinner"></span>${escapeHtml(msg.activeTool)} を実行中...</div>`;
  }

  bubble.innerHTML = html;
  requestAnimationFrame(() => {
    bubble.scrollIntoView({ block: "end", behavior: "instant" });
  });
}

function updateInputState() {
  if (!inputEl || !sendBtnEl) return;

  const { selectedAnima } = getState();
  const disabled = !selectedAnima;

  inputEl.disabled = disabled;
  sendBtnEl.disabled = disabled;
  const mobile = window.matchMedia("(max-width: 768px)").matches;
  const shortcut = mobile ? "Enter" : "Ctrl+Enter";
  inputEl.placeholder = selectedAnima
    ? `${selectedAnima} にメッセージ... (${shortcut} で送信)`
    : PLACEHOLDER_DEFAULT;
}

// ── Public API ──────────────────────────────────

/**
 * Build full chat UI (messages area + input form) into the container.
 */
export function renderChat(container) {
  container.innerHTML = `
    <div class="chat-container">
      <div class="chat-messages"></div>
      <div class="chat-input-area">
        <textarea class="chat-input" rows="1" placeholder="${PLACEHOLDER_DEFAULT}" disabled></textarea>
        <button class="chat-send-btn" disabled>送信</button>
      </div>
    </div>
  `;

  messagesEl = container.querySelector(".chat-messages");
  inputEl = container.querySelector(".chat-input");
  sendBtnEl = container.querySelector(".chat-send-btn");
}

/**
 * Bind event listeners after renderChat.
 */
export function initChat(container) {
  if (!inputEl || !sendBtnEl) {
    // Ensure DOM refs if renderChat wasn't called
    messagesEl = container.querySelector(".chat-messages");
    inputEl = container.querySelector(".chat-input");
    sendBtnEl = container.querySelector(".chat-send-btn");
  }

  if (!inputEl || !sendBtnEl) return;

  // Auto-resize textarea (100px on mobile, 200px on desktop)
  inputEl.addEventListener("input", () => {
    inputEl.style.height = "auto";
    const mobile = window.matchMedia("(max-width: 768px)").matches;
    const maxH = mobile ? 100 : 200;
    inputEl.style.height = Math.min(inputEl.scrollHeight, maxH) + "px";
  });

  // Enter key handling: mobile vs desktop
  inputEl.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      const mobile = window.matchMedia("(max-width: 768px)").matches;
      if (mobile) {
        // Mobile: Enter sends, Shift+Enter for newline
        if (!e.shiftKey) {
          e.preventDefault();
          submitFromInput();
        }
      } else {
        // Desktop: Ctrl/Cmd+Enter sends
        if (e.ctrlKey || e.metaKey) {
          e.preventDefault();
          submitFromInput();
        }
      }
    }
  });

  // Mobile keyboard: keep input visible above virtual keyboard
  if (window.visualViewport) {
    window.visualViewport.addEventListener("resize", () => {
      if (document.activeElement === inputEl) {
        requestAnimationFrame(() => {
          inputEl.scrollIntoView({ block: "nearest" });
        });
      }
    });
  }

  // Send button click
  sendBtnEl.addEventListener("click", (e) => {
    e.preventDefault();
    submitFromInput();
  });

  // Initial render
  updateInputState();
  renderAllMessages();
}

/**
 * Send a message and begin SSE streaming.
 */
export async function sendMessage(text) {
  const { selectedAnima, currentUser } = getState();
  if (!selectedAnima || !text.trim()) return;

  const trimmed = text.trim();

  // Add user message + empty streaming assistant bubble (immutable)
  const userMsg = { role: "user", text: trimmed };
  const streamingMsg = { role: "assistant", text: "", streaming: true, activeTool: null };
  const updated = [...getState().chatMessages, userMsg, streamingMsg];
  setState({ chatMessages: updated });
  renderAllMessages();

  // Disable input during streaming
  setInputEnabled(false);
  _isSseStreaming = true;

  try {
    const response = await sendChatStream(selectedAnima, trimmed, currentUser || "human");
    if (!response.ok) {
      throw new Error(`API ${response.status}: ${response.statusText}`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const { parsed, remaining } = parseSSEEvents(buffer);
      buffer = remaining;

      for (const evt of parsed) {
        switch (evt.event) {
          case "text_delta":
            streamingMsg.text += evt.data.text;
            scheduleStreamingUpdate(streamingMsg);
            break;

          case "tool_start":
            streamingMsg.activeTool = evt.data.tool_name;
            updateStreamingBubble(streamingMsg);
            break;

          case "tool_end":
            // Keep last tool indicator visible — cleared on done
            break;

          case "chain_start":
            // Session continuation — stream continues
            break;

          case "error":
            streamingMsg.text += `\n[エラー] ${getErrorMessage(evt.data)}`;
            streamingMsg.streaming = false;
            streamingMsg.activeTool = null;
            setState({ chatMessages: [...getState().chatMessages] });
            renderAllMessages();
            break;

          case "done": {
            const summary = evt.data && evt.data.summary;
            if (summary) {
              streamingMsg.text = summary;
            }
            if (!streamingMsg.text) {
              streamingMsg.text = "(空の応答)";
            }
            streamingMsg.streaming = false;
            streamingMsg.activeTool = null;
            setState({ chatMessages: [...getState().chatMessages] });
            renderAllMessages();
            break;
          }
        }
      }
    }

    // Ensure finalized if stream ended without done event
    if (streamingMsg.streaming) {
      streamingMsg.streaming = false;
      if (!streamingMsg.text) streamingMsg.text = "(空の応答)";
      setState({ chatMessages: [...getState().chatMessages] });
      renderAllMessages();
    }
  } catch (err) {
    streamingMsg.text = `[エラー] ${err.message}`;
    streamingMsg.streaming = false;
    streamingMsg.activeTool = null;
    setState({ chatMessages: [...getState().chatMessages] });
    renderAllMessages();
  } finally {
    _isSseStreaming = false;
    setInputEnabled(true);
    if (inputEl) inputEl.focus();
  }
}

/**
 * Add a message from external source (e.g. WebSocket push).
 */
export function addMessage(role, text) {
  const { chatMessages } = getState();

  // Skip if SSE streaming is active (SSE handles display)
  if (_isSseStreaming) return;

  // Avoid duplicating the last message
  const last = chatMessages[chatMessages.length - 1];
  if (last && last.role === role && last.text === text) return;

  setState({ chatMessages: [...chatMessages, { role, text }] });
  renderAllMessages();
}

/**
 * Load full conversation history from server.
 */
export async function loadConversation() {
  const { selectedAnima } = getState();
  if (!selectedAnima) return;

  try {
    const data = await fetchConversationFull(selectedAnima);
    if (data.turns && data.turns.length > 0) {
      const messages = data.turns.map((t) => ({
        role: t.role === "human" ? "user" : "assistant",
        text: t.content || "",
      }));
      setState({ chatMessages: messages });
    } else {
      setState({ chatMessages: [] });
    }
  } catch (err) {
    console.error("Failed to load conversation:", err);
    setState({ chatMessages: [] });
  }

  renderAllMessages();
  updateInputState();
}

// ── Internal Helpers ────────────────────────────

function submitFromInput() {
  if (!inputEl) return;
  const text = inputEl.value.trim();
  if (!text) return;

  inputEl.value = "";
  inputEl.style.height = "auto";
  sendMessage(text);
}

function setInputEnabled(enabled) {
  if (inputEl) inputEl.disabled = !enabled;
  if (sendBtnEl) sendBtnEl.disabled = !enabled;
}
