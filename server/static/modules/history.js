/* ── History Panel ─────────────────────────── */

import { state, dom, timeStr, escapeHtml, renderMarkdown } from "./state.js";
import { api } from "./api.js";

export async function loadSessionList() {
  const name = state.selectedPerson;
  if (!name) {
    dom.historySessionList.innerHTML = '<div class="loading-placeholder">パーソンを選択してください</div>';
    return;
  }
  dom.historySessionList.innerHTML = '<div class="loading-placeholder">読み込み中...</div>';
  try {
    const data = await api(`/api/persons/${encodeURIComponent(name)}/sessions`);
    state.sessionList = data;
    renderSessionList(data);
  } catch (err) {
    dom.historySessionList.innerHTML = `<div class="loading-placeholder">読み込み失敗: ${escapeHtml(err.message)}</div>`;
  }
}

function renderSessionList(data) {
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
          ${ac.total_turn_count}ターン ${ac.has_summary ? "(要約あり)" : ""}
          | 最終: ${lastTime}
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

  if (!html) {
    html = '<div class="loading-placeholder">履歴がありません</div>';
  }

  dom.historySessionList.innerHTML = html;

  // Bind click handlers
  dom.historySessionList.querySelectorAll(".session-item").forEach((item) => {
    item.addEventListener("click", () => {
      const type = item.dataset.type;
      if (type === "active") loadActiveConversation();
      else if (type === "archive") loadArchivedSession(item.dataset.id);
      else if (type === "transcript") loadTranscriptInHistory(item.dataset.date);
      else if (type === "episode") loadEpisodeInHistory(item.dataset.date);
    });
  });
}

export function showHistoryDetail(title) {
  dom.historySessionList.style.display = "none";
  dom.historyDetail.style.display = "";
  dom.historyDetailTitle.textContent = title;
}

export function hideHistoryDetail() {
  dom.historyDetail.style.display = "none";
  dom.historySessionList.style.display = "";
}

async function loadActiveConversation() {
  const name = state.selectedPerson;
  if (!name) return;

  showHistoryDetail("進行中の会話");
  dom.historyConversation.innerHTML = '<div class="loading-placeholder">読み込み中...</div>';

  try {
    const data = await api(`/api/persons/${encodeURIComponent(name)}/conversation/full?limit=50`);
    renderConversationDetail(data);
  } catch (err) {
    dom.historyConversation.innerHTML = '<div class="loading-placeholder">読み込み失敗</div>';
  }
}

function renderConversationDetail(data) {
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

  if (!html) {
    html = '<div class="loading-placeholder">会話データがありません</div>';
  }

  dom.historyConversation.innerHTML = html;
  dom.historyConversation.scrollTop = dom.historyConversation.scrollHeight;
}

async function loadArchivedSession(sessionId) {
  const name = state.selectedPerson;
  if (!name) return;

  showHistoryDetail(`セッション: ${sessionId}`);
  dom.historyConversation.innerHTML = '<div class="loading-placeholder">読み込み中...</div>';

  try {
    const data = await api(`/api/persons/${encodeURIComponent(name)}/sessions/${encodeURIComponent(sessionId)}`);
    renderArchivedSessionDetail(data);
  } catch (err) {
    dom.historyConversation.innerHTML = '<div class="loading-placeholder">読み込み失敗</div>';
  }
}

function renderArchivedSessionDetail(data) {
  if (data.markdown) {
    dom.historyConversation.innerHTML = `<div class="history-markdown">${renderMarkdown(data.markdown)}</div>`;
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
    dom.historyConversation.innerHTML = html;
  } else {
    dom.historyConversation.innerHTML = '<div class="loading-placeholder">データがありません</div>';
  }
}

async function loadTranscriptInHistory(date) {
  const name = state.selectedPerson;
  if (!name) return;

  showHistoryDetail(`会話ログ: ${date}`);
  dom.historyConversation.innerHTML = '<div class="loading-placeholder">読み込み中...</div>';

  try {
    const data = await api(`/api/persons/${encodeURIComponent(name)}/transcripts/${encodeURIComponent(date)}`);
    renderConversationDetail(data);
  } catch (err) {
    dom.historyConversation.innerHTML = '<div class="loading-placeholder">読み込み失敗</div>';
  }
}

async function loadEpisodeInHistory(date) {
  const name = state.selectedPerson;
  if (!name) return;

  showHistoryDetail(`エピソード: ${date}`);
  dom.historyConversation.innerHTML = '<div class="loading-placeholder">読み込み中...</div>';

  try {
    const data = await api(`/api/persons/${encodeURIComponent(name)}/episodes/${encodeURIComponent(date)}`);
    dom.historyConversation.innerHTML = `<div class="history-markdown">${renderMarkdown(data.content || "(内容なし)")}</div>`;
  } catch (err) {
    dom.historyConversation.innerHTML = '<div class="loading-placeholder">読み込み失敗</div>';
  }
}
