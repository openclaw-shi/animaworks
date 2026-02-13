/* ── System Status ─────────────────────────── */

import { state, dom } from "./state.js";
import { api } from "./api.js";

export async function loadSystemStatus() {
  try {
    const data = await api("/api/system/status");
    const personCount = data.persons || 0;
    const schedulerRunning = data.scheduler_running;
    const dot = dom.systemStatus.querySelector(".status-dot");
    if (schedulerRunning) {
      dot.className = "status-dot status-idle";
      dom.systemStatusText.textContent = `稼働中 (${personCount}名)`;
    } else {
      dot.className = "status-dot status-error";
      dom.systemStatusText.textContent = "スケジューラ停止";
    }
  } catch {
    updateSystemStatus();
  }
}

export function updateSystemStatus() {
  const dot = dom.systemStatus.querySelector(".status-dot");
  if (state.wsConnected) {
    dot.className = "status-dot status-idle";
    dom.systemStatusText.textContent = `接続済 (${state.persons.length}名)`;
  } else {
    dot.className = "status-dot status-offline";
    dom.systemStatusText.textContent = "再接続中...";
  }
}
