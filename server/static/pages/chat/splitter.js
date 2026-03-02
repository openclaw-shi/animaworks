// ── Splitter — drag-resizable divider between chat panes ──

export function initSplitter(splitterEl, hostEl, { onResize } = {}) {
  let dragging = false;
  let startX = 0;
  let leftPane = null;
  let rightPane = null;
  let leftStart = 0;
  let rightStart = 0;
  let totalWidth = 0;

  function _getPanes() {
    const prev = splitterEl.previousElementSibling;
    const next = splitterEl.nextElementSibling;
    if (!prev?.classList.contains("chat-pane") || !next?.classList.contains("chat-pane")) {
      return null;
    }
    return { left: prev, right: next };
  }

  function onPointerDown(e) {
    const panes = _getPanes();
    if (!panes) return;
    e.preventDefault();
    dragging = true;
    startX = e.clientX;
    leftPane = panes.left;
    rightPane = panes.right;
    leftStart = leftPane.getBoundingClientRect().width;
    rightStart = rightPane.getBoundingClientRect().width;
    totalWidth = leftStart + rightStart;

    splitterEl.classList.add("active");
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";

    document.addEventListener("pointermove", onPointerMove);
    document.addEventListener("pointerup", onPointerUp);
  }

  function onPointerMove(e) {
    if (!dragging) return;
    const dx = e.clientX - startX;
    const MIN_PANE = 200;
    let newLeft = leftStart + dx;
    let newRight = rightStart - dx;
    if (newLeft < MIN_PANE) { newLeft = MIN_PANE; newRight = totalWidth - MIN_PANE; }
    if (newRight < MIN_PANE) { newRight = MIN_PANE; newLeft = totalWidth - MIN_PANE; }
    const leftRatio = newLeft / totalWidth;
    const rightRatio = newRight / totalWidth;
    leftPane.style.flex = `${leftRatio} 0 0%`;
    rightPane.style.flex = `${rightRatio} 0 0%`;
  }

  function onPointerUp() {
    if (!dragging) return;
    dragging = false;
    splitterEl.classList.remove("active");
    document.body.style.cursor = "";
    document.body.style.userSelect = "";
    document.removeEventListener("pointermove", onPointerMove);
    document.removeEventListener("pointerup", onPointerUp);

    _persistLayout();
  }

  function _persistLayout() {
    if (onResize) {
      const allPanes = hostEl.querySelectorAll(".chat-pane");
      const widths = Array.from(allPanes).map(p => p.style.flex || "");
      onResize(widths);
    }
  }

  splitterEl.addEventListener("pointerdown", onPointerDown);

  splitterEl.addEventListener("dblclick", () => {
    const panes = _getPanes();
    if (!panes) return;
    panes.left.style.flex = "1 0 0%";
    panes.right.style.flex = "1 0 0%";
    _persistLayout();
  });
}
