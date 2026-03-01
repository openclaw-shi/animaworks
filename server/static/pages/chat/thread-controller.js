// ── Thread CRUD / Tab Controller ──────────────
import {
  $, isTabOpen, refreshAnimaUnread, clearUnreadForActiveThread,
  setThreadUnread, threadTimeValue, scheduleSaveChatUiState,
  CONSTANTS,
} from "./ctx.js";
import {
  renderThreadTabsHtml,
  createThread as sharedCreateThread,
  closeThread as sharedCloseThread,
} from "../../shared/chat/thread-logic.js";

export function createThreadController(ctx) {
  const { state, deps } = ctx;
  const { escapeHtml } = deps;

  function renderThreadTabs() {
    const container = $("chatThreadTabs");
    if (!container || !state.selectedAnima) return;

    const list = state.threads[state.selectedAnima] || [{ id: "default", label: "メイン", unread: false }];
    container.innerHTML = renderThreadTabsHtml(list, state.selectedThreadId, {
      escapeHtml,
      maxVisible: CONSTANTS.THREAD_VISIBLE_NON_DEFAULT,
    });

    container.querySelectorAll(".thread-tab").forEach(btn => {
      btn.addEventListener("click", e => {
        const tid = e.target.dataset.thread;
        if (tid) selectThread(tid);
      });
    });
    container.querySelectorAll(".thread-tab-close").forEach(btn => {
      btn.addEventListener("click", e => {
        e.stopPropagation();
        const tid = e.target.dataset.thread;
        if (tid) closeThread(tid);
      });
    });
    const newBtn = $("chatNewThreadBtn");
    if (newBtn) newBtn.addEventListener("click", () => createNewThread());

    const moreSelect = $("chatThreadMoreSelect");
    if (moreSelect) {
      moreSelect.addEventListener("change", e => {
        const tid = e.target.value;
        if (tid) selectThread(tid);
        e.target.value = "";
      });
    }
  }

  async function selectThread(threadId) {
    if (threadId === state.selectedThreadId) return;
    state.selectedThreadId = threadId;
    state.activeThreadByAnima[state.selectedAnima] = threadId;
    clearUnreadForActiveThread(ctx, state.selectedAnima, threadId);
    refreshAnimaUnread(ctx, state.selectedAnima);
    ctx.controllers.anima.renderAnimaTabs();
    renderThreadTabs();

    const name = state.selectedAnima;
    if (!name) return;

    const mgr = state.manager;
    const hs = mgr.getHistoryState(name, threadId);
    const needLoad = !hs || hs.sessions.length === 0;
    ctx.controllers.renderer.renderChat();

    if (needLoad) {
      await mgr.loadHistory(name, threadId, CONSTANTS.HISTORY_PAGE_SIZE);
    }
    ctx.controllers.renderer.renderChat();
    scheduleSaveChatUiState(ctx);
  }

  function createNewThread() {
    if (!state.selectedAnima) return;
    const list = state.threads[state.selectedAnima] || [{ id: "default", label: "メイン", unread: false }];
    const { updatedList, newThreadId } = sharedCreateThread(list, state.selectedAnima);
    state.threads[state.selectedAnima] = updatedList;

    state.manager.setMessages(state.selectedAnima, newThreadId, []);

    renderThreadTabs();
    selectThread(newThreadId);
    scheduleSaveChatUiState(ctx);
  }

  function closeThread(threadId) {
    if (threadId === "default" || !state.selectedAnima) return;
    const list = state.threads[state.selectedAnima];
    if (!list) return;
    if (!list.some(th => th.id === threadId)) return;

    state.threads[state.selectedAnima] = sharedCloseThread(list, threadId);
    state.manager.destroySession(state.selectedAnima, threadId);

    if (state.selectedThreadId === threadId) {
      state.selectedThreadId = "default";
      state.activeThreadByAnima[state.selectedAnima] = "default";
    }
    refreshAnimaUnread(ctx, state.selectedAnima);
    ctx.controllers.anima.renderAnimaTabs();
    renderThreadTabs();
    ctx.controllers.renderer.renderChat();
    scheduleSaveChatUiState(ctx);
  }

  return { renderThreadTabs, selectThread, createNewThread, closeThread };
}
