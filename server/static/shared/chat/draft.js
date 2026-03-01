// ── Shared Draft Persistence ──────────────────────
// LocalStorage-backed draft persistence for chat inputs.
// Namespace distinguishes dashboard-chat vs workspace-conv.

/**
 * Build a localStorage key for a draft.
 * @param {string} namespace - e.g. "dashboard-chat" or "workspace-conv"
 * @param {string} user
 * @param {string} animaName
 * @param {string} [threadId] - optional thread id for per-thread drafts
 */
export function getDraftKey(namespace, user, animaName, threadId) {
  const base = `aw:draft:${namespace}:${user || "guest"}:${animaName || "_"}`;
  return threadId && threadId !== "default" ? `${base}:${threadId}` : base;
}

/**
 * Save draft text to localStorage.
 * @param {string} key - From getDraftKey
 * @param {string} text
 */
export function saveDraft(key, text) {
  if (!key) return;
  localStorage.setItem(key, text || "");
}

/**
 * Load draft text from localStorage.
 * @param {string} key - From getDraftKey
 * @returns {string}
 */
export function loadDraft(key) {
  if (!key) return "";
  return localStorage.getItem(key) || "";
}

/**
 * Clear a draft from localStorage.
 * @param {string} key - From getDraftKey
 */
export function clearDraft(key) {
  if (!key) return;
  localStorage.removeItem(key);
}
