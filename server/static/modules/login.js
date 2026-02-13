/* ── Login / Logout ────────────────────────── */

import { state, dom, escapeHtml } from "./state.js";
import { api } from "./api.js";

let _startDashboard = null;

export function setStartDashboard(fn) {
  _startDashboard = fn;
}

export async function loadSharedUsers() {
  try {
    const users = await api("/api/shared/users");
    let html = "";
    for (const name of users) {
      html += `<button class="user-btn" data-user="${escapeHtml(name)}">${escapeHtml(name)}</button>`;
    }
    if (!users.length) {
      html = '<p style="color:#999;font-size:0.85rem;">登録ユーザーがありません</p>';
    }
    dom.userList.innerHTML = html;

    dom.userList.querySelectorAll(".user-btn").forEach((btn) => {
      btn.addEventListener("click", () => loginAs(btn.dataset.user));
    });
  } catch (err) {
    dom.userList.innerHTML = '<p style="color:#ef4444;">ユーザー一覧の取得に失敗しました</p>';
  }
}

export function loginAs(username) {
  state.currentUser = username;
  localStorage.setItem("animaworks_user", username);
  hideLoginScreen();
  if (_startDashboard) _startDashboard();
}

export function logout() {
  state.currentUser = null;
  localStorage.removeItem("animaworks_user");
  showLoginScreen();
}

export function showLoginScreen() {
  dom.loginScreen.classList.remove("hidden");
  loadSharedUsers();
}

export function hideLoginScreen() {
  dom.loginScreen.classList.add("hidden");
  const label = state.currentUser === "human" ? "ゲスト" : state.currentUser;
  dom.currentUserLabel.textContent = label;
}
