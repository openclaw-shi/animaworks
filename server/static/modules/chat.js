/* ── Chat ──────────────────────────────────── */

import { state, dom, escapeHtml, renderMarkdown } from "./state.js";
import { addActivity } from "./activity.js";
import { streamChat } from "../shared/chat-stream.js";
import { createLogger } from "../shared/logger.js";

const logger = createLogger("chat");

// ── Render ─────────────────────────────────

export function renderChat() {
  const chatMessages = dom.chatMessages || document.getElementById("chatMessages");
  if (!chatMessages) return; // Chat not in DOM (page not active)

  const name = state.selectedAnima;
  const history = state.chatHistories[name] || [];
  if (history.length === 0) {
    chatMessages.innerHTML = '<div class="chat-empty">メッセージはまだありません</div>';
    return;
  }
  chatMessages.innerHTML = history.map((m) => {
    if (m.role === "thinking") {
      return `<div class="chat-bubble thinking"><span class="thinking-animation">考え中</span></div>`;
    }
    if (m.role === "assistant") {
      const streamClass = m.streaming ? " streaming" : "";
      const notifClass = m.notification ? " notification" : "";
      let content = "";
      if (m.text) {
        content = renderMarkdown(m.text);
      } else if (m.streaming) {
        content = '<span class="cursor-blink"></span>';
      }
      const bootstrapHtml = m.bootstrapping
        ? `<div class="bootstrap-indicator"><span class="tool-spinner"></span>初期化中...</div>`
        : "";
      const toolHtml = m.activeTool
        ? `<div class="tool-indicator"><span class="tool-spinner"></span>${escapeHtml(m.activeTool)} を実行中...</div>`
        : "";
      return `<div class="chat-bubble assistant${streamClass}${notifClass}">${content}${bootstrapHtml}${toolHtml}</div>`;
    }
    return `<div class="chat-bubble user">${escapeHtml(m.text)}</div>`;
  }).join("");
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

// ── SSE Streaming ─────────────────────────

function renderStreamingBubble(msg) {
  const chatMessages = dom.chatMessages || document.getElementById("chatMessages");
  if (!chatMessages) return;
  const bubble = chatMessages.querySelector(".chat-bubble.assistant.streaming");
  if (!bubble) return;

  let html = "";

  if (msg.heartbeatRelay) {
    html += '<div class="heartbeat-relay-indicator"><span class="tool-spinner"></span>ハートビート処理中...</div>';
    if (msg.heartbeatText) {
      html += `<div class="heartbeat-relay-text">${escapeHtml(msg.heartbeatText)}</div>`;
    }
  } else if (msg.text) {
    try {
      html = marked.parse(msg.text, { breaks: true });
    } catch {
      html = escapeHtml(msg.text);
    }
  } else {
    html = '<span class="cursor-blink"></span>';
  }

  if (msg.bootstrapping) {
    html += `<div class="bootstrap-indicator"><span class="tool-spinner"></span>初期化中...</div>`;
  }

  if (msg.activeTool) {
    html += `<div class="tool-indicator"><span class="tool-spinner"></span>${escapeHtml(msg.activeTool)} を実行中...</div>`;
  }

  bubble.innerHTML = html;
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

export async function sendChat(message) {
  const name = state.selectedAnima;
  if (!name || !message.trim()) return;

  // Guard: block sending to bootstrapping animas
  const currentAnima = state.animas.find((p) => p.name === name);
  if (currentAnima?.status === "bootstrapping" || currentAnima?.bootstrapping) {
    const chatMessages = dom.chatMessages || document.getElementById("chatMessages");
    if (chatMessages) {
      const systemMsg = document.createElement("div");
      systemMsg.className = "chat-bubble assistant";
      systemMsg.textContent = "このキャラクターは現在制作中です。完了までお待ちください。";
      chatMessages.appendChild(systemMsg);
      chatMessages.scrollTop = chatMessages.scrollHeight;
    }
    return;
  }

  if (!state.chatHistories[name]) state.chatHistories[name] = [];
  const history = state.chatHistories[name];

  // Add user message + empty streaming bubble
  history.push({ role: "user", text: message });
  const streamingMsg = { role: "assistant", text: "", streaming: true, activeTool: null };
  history.push(streamingMsg);
  renderChat();

  const chatInput = dom.chatInput || document.getElementById("chatInput");
  const chatSendBtn = dom.chatSendBtn || document.getElementById("chatSendBtn");
  if (chatInput) chatInput.disabled = true;
  if (chatSendBtn) chatSendBtn.disabled = true;
  addActivity("chat", name, `ユーザー: ${message}`);

  try {
    const body = JSON.stringify({ message, from_person: state.currentUser || "human" });

    await streamChat(name, body, null, {
      onTextDelta: (text) => {
        streamingMsg.text += text;
        renderStreamingBubble(streamingMsg);
      },
      onToolStart: (toolName) => {
        streamingMsg.activeTool = toolName;
        renderStreamingBubble(streamingMsg);
      },
      onToolEnd: () => {
        // Keep last tool indicator visible — cleared on done
      },
      onBootstrap: (data) => {
        if (data.status === "started") {
          streamingMsg.bootstrapping = true;
          renderStreamingBubble(streamingMsg);
        } else if (data.status === "completed") {
          streamingMsg.bootstrapping = false;
          renderStreamingBubble(streamingMsg);
        } else if (data.status === "busy") {
          streamingMsg.text = data.message || "現在初期化中です。しばらくお待ちください。";
          streamingMsg.streaming = false;
          streamingMsg.bootstrapping = false;
          renderChat();
          addActivity("system", name, "ブートストラップ中のため応答保留");
        }
      },
      onChainStart: () => {},
      onHeartbeatRelayStart: ({ message }) => {
        streamingMsg.heartbeatRelay = true;
        streamingMsg.heartbeatText = "";
        streamingMsg.text = "";
        renderStreamingBubble(streamingMsg);
        addActivity("system", name, `ハートビート中継: ${message}`);
      },
      onHeartbeatRelay: ({ text }) => {
        streamingMsg.heartbeatText = (streamingMsg.heartbeatText || "") + text;
        renderStreamingBubble(streamingMsg);
      },
      onHeartbeatRelayDone: () => {
        streamingMsg.heartbeatRelay = false;
        streamingMsg.heartbeatText = "";
        streamingMsg.text = "";
        renderStreamingBubble(streamingMsg);
      },
      onError: ({ message: errorMsg }) => {
        streamingMsg.text += `\n[エラー] ${errorMsg}`;
        streamingMsg.streaming = false;
        renderChat();
      },
      onDone: ({ summary }) => {
        const text = summary || streamingMsg.text;
        streamingMsg.text = text || "(空の応答)";
        streamingMsg.streaming = false;
        streamingMsg.activeTool = null;
        streamingMsg.heartbeatRelay = false;
        streamingMsg.heartbeatText = "";
        renderChat();
        addActivity("chat", name, `応答: ${streamingMsg.text.slice(0, 100)}`);
      },
    });

    // Ensure streaming is finalized if stream ended without done event
    if (streamingMsg.streaming) {
      streamingMsg.streaming = false;
      if (!streamingMsg.text) streamingMsg.text = "(空の応答)";
      renderChat();
    }
  } catch (err) {
    if (err.name !== "AbortError") {
      logger.error("Chat stream error", { anima: name, error: err.message, name: err.name });
    }
    streamingMsg.text = `[エラー] ${err.message}`;
    streamingMsg.streaming = false;
    streamingMsg.activeTool = null;
    renderChat();
  } finally {
    const chatInput = dom.chatInput || document.getElementById("chatInput");
    const chatSendBtn = dom.chatSendBtn || document.getElementById("chatSendBtn");
    if (chatInput) {
      chatInput.disabled = false;
      chatInput.focus();
    }
    if (chatSendBtn) chatSendBtn.disabled = false;
  }
}
