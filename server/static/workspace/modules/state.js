// ── State Management ──────────────────────
// Simple Pub/Sub state store. No framework needed.

let state = {
  currentUser: localStorage.getItem("animaworks_user") || null,
  persons: [],
  selectedPerson: null,
  personDetail: null,
  chatMessages: [],
  wsConnected: false,
  activeRightTab: "state",
  activeMemoryTab: "episodes",
  sessionList: null,
  viewMode: "chat",              // "chat" | "office"
  officeInitialized: false,      // Whether 3D office has been initialized
  conversationOverlay: false,    // Whether conversation overlay is open
  conversationPerson: null,      // Person name shown in conversation overlay
  characterStates: {},           // Map: personName → animationState (idle/working/thinking/error/sleeping)
};

const listeners = new Set();

export function getState() {
  return state;
}

export function setState(partial) {
  state = { ...state, ...partial };
  listeners.forEach((fn) => fn(state));
}

export function subscribe(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}
