// ── Live2D Bust-up Module ──────────────────────
// Canvas 2D character bust-up renderer with expressions, lip-sync, and blinking.
// Placeholder for real Live2D integration — same export API for seamless swap.

// ── Character Profiles ──────────────────────

/**
 * @typedef {Object} CharacterProfile
 * @property {string} hair    - Hair color hex
 * @property {string} eyes    - Iris color hex
 * @property {string} clothing - Clothing color hex
 * @property {string} skin    - Skin tone hex
 */

/** @type {Record<string, CharacterProfile>} */
const PROFILES = {
  sakura: { hair: "#1a1a2e", eyes: "#cc3333", clothing: "#8b0000", skin: "#f5e6d3" },
  kotoha: { hair: "#c4956a", eyes: "#d4a040", clothing: "#ff8c69", skin: "#fff0e0" },
  mio:    { hair: "#1a1a3e", eyes: "#7788aa", clothing: "#4a5568", skin: "#f0e8f0" },
  alice:  { hair: "#f0e68c", eyes: "#4477cc", clothing: "#6495ed", skin: "#fff8f0" },
  rin:    { hair: "#0a0a2a", eyes: "#33aa55", clothing: "#2d5a3d", skin: "#f5f0e8" },
  rei:    { hair: "#d0d0e0", eyes: "#cc3344", clothing: "#800020", skin: "#f0f0f8" },
  kaede:  { hair: "#8b4513", eyes: "#daa520", clothing: "#b8860b", skin: "#f8ece0" },
};

/** Valid expression names. */
const EXPRESSIONS = ["normal", "happy", "troubled", "angry", "surprised", "thinking"];

// ── Private State ──────────────────────

/** @type {HTMLCanvasElement|null} */
let _canvas = null;

/** @type {CanvasRenderingContext2D|null} */
let _ctx = null;

/** @type {number} */
let _animFrameId = 0;

/** @type {ResizeObserver|null} */
let _resizeObserver = null;

/** @type {string|null} */
let _characterName = null;

/** @type {CharacterProfile|null} */
let _profile = null;

/** @type {string} */
let _expression = "normal";

/** @type {string} */
let _prevExpression = "normal";

/** @type {number} */
let _expressionTransitionStart = 0;

/** @type {boolean} */
let _isTalking = false;

/** @type {function|null} */
let _clickCallback = null;

/** @type {number} Canvas logical width. */
let _width = 0;

/** @type {number} Canvas logical height. */
let _height = 0;

/** @type {number} Device pixel ratio. */
let _dpr = 1;

// ── Animation Timing State ──────────────────────
// Reusable objects to minimise GC pressure.

const _blink = {
  /** Next blink timestamp (ms). */
  nextAt: 0,
  /** Whether currently in a blink. */
  active: false,
  /** Timestamp when current blink started. */
  startedAt: 0,
  /** Duration of a single blink in ms. */
  duration: 150,
};

const _breath = {
  /** Period of one breathing cycle (ms). */
  period: 3000,
  /** Pixel amplitude of the breathing offset. */
  amplitude: 2,
};

const _lipSync = {
  /** Current mouth openness 0-1. */
  openness: 0,
  /** Timestamp of last mouth state change. */
  lastChange: 0,
  /** Duration for the current mouth phase. */
  phaseDuration: 100,
  /** Whether mouth is currently open. */
  isOpen: false,
  /** Index into the rhythm pattern. */
  patternIndex: 0,
  /** Open/close durations for a natural cadence. */
  pattern: [100, 80, 120, 100, 90, 110, 80, 100],
};

/** @type {number} Timestamp of last rendered frame. */
let _lastFrameTime = 0;

/** Minimum ms between frames (~30 fps). */
const FRAME_INTERVAL = 1000 / 30;

/** Expression transition duration (ms). */
const EXPR_TRANSITION_MS = 200;

// ── Deterministic Hash ──────────────────────

/**
 * Simple deterministic hash from a string (djb2).
 * Returns an unsigned 32-bit integer.
 * @param {string} str
 * @returns {number}
 */
function hashString(str) {
  let h = 5381;
  for (let i = 0; i < str.length; i++) {
    h = ((h << 5) + h + str.charCodeAt(i)) >>> 0;
  }
  return h;
}

/**
 * Generate a deterministic profile for unknown character names.
 * @param {string} name
 * @returns {CharacterProfile}
 */
function generateProfile(name) {
  const h = hashString(name);
  const hue1 = h % 360;
  const hue2 = (h * 7 + 123) % 360;
  const hue3 = (h * 13 + 47) % 360;
  const lightness = 20 + (h % 30);

  return {
    hair: `hsl(${hue1}, 40%, ${lightness}%)`,
    eyes: `hsl(${hue2}, 60%, 45%)`,
    clothing: `hsl(${hue3}, 50%, 35%)`,
    skin: `hsl(${(hue1 + 30) % 360}, 30%, 92%)`,
  };
}

// ── Canvas Sizing ──────────────────────

/**
 * Synchronise the canvas buffer size with its CSS container, respecting devicePixelRatio.
 */
function syncCanvasSize() {
  if (!_canvas) return;

  const parent = _canvas.parentElement;
  if (!parent) return;

  const rect = parent.getBoundingClientRect();
  _dpr = window.devicePixelRatio || 1;
  _width = rect.width;
  _height = rect.height;

  _canvas.width = Math.round(_width * _dpr);
  _canvas.height = Math.round(_height * _dpr);
  _canvas.style.width = `${_width}px`;
  _canvas.style.height = `${_height}px`;

  if (_ctx) {
    _ctx.setTransform(_dpr, 0, 0, _dpr, 0, 0);
  }
}

// ── Color Helpers ──────────────────────

/**
 * Parse a hex color (#rrggbb) into [r, g, b].
 * Falls through to [128,128,128] for hsl() or invalid values.
 * @param {string} hex
 * @returns {[number, number, number]}
 */
function hexToRgb(hex) {
  if (!hex || hex.charAt(0) !== "#") return [128, 128, 128];
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

/**
 * Darken a CSS color string by a factor (0 = black, 1 = original).
 * Works for hex colours; for hsl strings it returns unchanged.
 * @param {string} color
 * @param {number} factor
 * @returns {string}
 */
function darken(color, factor) {
  if (!color || color.charAt(0) !== "#") return color;
  const [r, g, b] = hexToRgb(color);
  const dr = Math.round(r * factor);
  const dg = Math.round(g * factor);
  const db = Math.round(b * factor);
  return `rgb(${dr},${dg},${db})`;
}

/**
 * Lighten a CSS color string by mixing towards white.
 * @param {string} color
 * @param {number} amount 0-1 (0 = original, 1 = white)
 * @returns {string}
 */
function lighten(color, amount) {
  if (!color || color.charAt(0) !== "#") return color;
  const [r, g, b] = hexToRgb(color);
  const lr = Math.round(r + (255 - r) * amount);
  const lg = Math.round(g + (255 - g) * amount);
  const lb = Math.round(b + (255 - b) * amount);
  return `rgb(${lr},${lg},${lb})`;
}

/**
 * Create a semi-transparent version of a colour.
 * @param {string} color
 * @param {number} alpha 0-1
 * @returns {string}
 */
function withAlpha(color, alpha) {
  if (!color || color.charAt(0) !== "#") return color;
  const [r, g, b] = hexToRgb(color);
  return `rgba(${r},${g},${b},${alpha})`;
}

// ── Coordinate Helpers ──────────────────────
// All positions are expressed as fractions of canvas width/height (0-1).
// The `r` helper converts them to pixel coords at draw time.

/**
 * Convert a fractional X to logical pixels.
 * @param {number} frac 0-1
 * @returns {number}
 */
function rx(frac) {
  return frac * _width;
}

/**
 * Convert a fractional Y to logical pixels.
 * @param {number} frac 0-1
 * @returns {number}
 */
function ry(frac) {
  return frac * _height;
}

/**
 * Scale value by the smaller canvas dimension (for radius etc.)
 * @param {number} frac
 * @returns {number}
 */
function rs(frac) {
  return frac * Math.min(_width, _height);
}

// ── Drawing Primitives ──────────────────────

/**
 * Draw a filled ellipse.
 * @param {number} cx - centre X
 * @param {number} cy - centre Y
 * @param {number} radX - horizontal radius
 * @param {number} radY - vertical radius
 * @param {string} color
 */
function fillEllipse(cx, cy, radX, radY, color) {
  _ctx.beginPath();
  _ctx.ellipse(cx, cy, Math.abs(radX), Math.abs(radY), 0, 0, Math.PI * 2);
  _ctx.fillStyle = color;
  _ctx.fill();
}

/**
 * Draw a stroked ellipse.
 * @param {number} cx
 * @param {number} cy
 * @param {number} radX
 * @param {number} radY
 * @param {string} color
 * @param {number} lineWidth
 */
function strokeEllipse(cx, cy, radX, radY, color, lineWidth) {
  _ctx.beginPath();
  _ctx.ellipse(cx, cy, Math.abs(radX), Math.abs(radY), 0, 0, Math.PI * 2);
  _ctx.strokeStyle = color;
  _ctx.lineWidth = lineWidth;
  _ctx.stroke();
}

// ── Expression Interpolation ──────────────────────

/**
 * Compute the expression transition factor (0 = old expression, 1 = new expression).
 * @param {number} now - current timestamp
 * @returns {number} 0-1
 */
function expressionFactor(now) {
  if (_expression === _prevExpression) return 1;
  const elapsed = now - _expressionTransitionStart;
  if (elapsed >= EXPR_TRANSITION_MS) return 1;
  return elapsed / EXPR_TRANSITION_MS;
}

/**
 * Linearly interpolate between two values.
 * @param {number} a
 * @param {number} b
 * @param {number} t 0-1
 * @returns {number}
 */
function lerp(a, b, t) {
  return a + (b - a) * t;
}

// ── Blink Logic ──────────────────────

/**
 * Schedule the next blink at a random future time (2-5 seconds).
 * @param {number} now
 */
function scheduleNextBlink(now) {
  _blink.nextAt = now + 2000 + Math.random() * 3000;
  _blink.active = false;
}

/**
 * Update blink state. Returns the blink factor (0 = eyes open, 1 = eyes fully closed).
 * @param {number} now
 * @returns {number}
 */
function updateBlink(now) {
  if (!_blink.active) {
    if (now >= _blink.nextAt) {
      _blink.active = true;
      _blink.startedAt = now;
    }
    return 0;
  }
  const elapsed = now - _blink.startedAt;
  if (elapsed >= _blink.duration) {
    scheduleNextBlink(now);
    return 0;
  }
  // Triangle wave: 0 → 1 → 0 over duration
  const half = _blink.duration / 2;
  return elapsed < half ? elapsed / half : 1 - (elapsed - half) / half;
}

// ── Lip-sync Logic ──────────────────────

/**
 * Update the lip-sync mouth openness value.
 * @param {number} now
 * @returns {number} 0-1 openness
 */
function updateLipSync(now) {
  if (!_isTalking) {
    _lipSync.openness = 0;
    return 0;
  }

  if (now - _lipSync.lastChange >= _lipSync.phaseDuration) {
    _lipSync.isOpen = !_lipSync.isOpen;
    _lipSync.patternIndex = (_lipSync.patternIndex + 1) % _lipSync.pattern.length;
    _lipSync.phaseDuration = _lipSync.pattern[_lipSync.patternIndex];
    _lipSync.lastChange = now;
  }

  // Smooth transition
  const target = _lipSync.isOpen ? 0.7 + Math.random() * 0.3 : 0;
  _lipSync.openness += (target - _lipSync.openness) * 0.3;
  return _lipSync.openness;
}

// ── Breathing ──────────────────────

/**
 * Compute the vertical breathing offset in logical pixels.
 * @param {number} now
 * @returns {number}
 */
function breathOffset(now) {
  return Math.sin((now / _breath.period) * Math.PI * 2) * _breath.amplitude;
}

// ── Character Drawing ──────────────────────

/**
 * Draw the background gradient themed to the character.
 * @param {CharacterProfile} prof
 */
function drawBackground(prof) {
  const grad = _ctx.createLinearGradient(0, 0, 0, _height);
  grad.addColorStop(0, lighten(prof.clothing, 0.85));
  grad.addColorStop(1, lighten(prof.clothing, 0.70));
  _ctx.fillStyle = grad;
  _ctx.fillRect(0, 0, _width, _height);
}

/**
 * Draw the hair behind the head (back portion).
 * @param {CharacterProfile} prof
 * @param {number} headCx
 * @param {number} headCy
 * @param {number} headRx
 * @param {number} headRy
 */
function drawHairBack(prof, headCx, headCy, headRx, headRy) {
  // Back hair extends wider and lower than the head
  fillEllipse(headCx, headCy + headRy * 0.1, headRx * 1.25, headRy * 1.35, prof.hair);

  // Side hair flowing down
  const sideWidth = headRx * 0.35;
  const sideLen = headRy * 1.8;

  // Left side hair
  _ctx.beginPath();
  _ctx.moveTo(headCx - headRx * 1.05, headCy - headRy * 0.2);
  _ctx.quadraticCurveTo(
    headCx - headRx * 1.3, headCy + sideLen * 0.5,
    headCx - headRx * 0.8, headCy + sideLen
  );
  _ctx.lineTo(headCx - headRx * 0.8 + sideWidth, headCy + sideLen * 0.9);
  _ctx.quadraticCurveTo(
    headCx - headRx * 1.0, headCy + sideLen * 0.3,
    headCx - headRx * 0.8, headCy - headRy * 0.2
  );
  _ctx.fillStyle = prof.hair;
  _ctx.fill();

  // Right side hair
  _ctx.beginPath();
  _ctx.moveTo(headCx + headRx * 1.05, headCy - headRy * 0.2);
  _ctx.quadraticCurveTo(
    headCx + headRx * 1.3, headCy + sideLen * 0.5,
    headCx + headRx * 0.8, headCy + sideLen
  );
  _ctx.lineTo(headCx + headRx * 0.8 - sideWidth, headCy + sideLen * 0.9);
  _ctx.quadraticCurveTo(
    headCx + headRx * 1.0, headCy + sideLen * 0.3,
    headCx + headRx * 0.8, headCy - headRy * 0.2
  );
  _ctx.fillStyle = prof.hair;
  _ctx.fill();
}

/**
 * Draw shoulders and upper body.
 * @param {CharacterProfile} prof
 * @param {number} neckCx
 * @param {number} neckBottom
 */
function drawBody(prof, neckCx, neckBottom) {
  const shoulderWidth = rs(0.38);
  const bodyHeight = ry(0.30);
  const bodyBottom = neckBottom + bodyHeight;

  // Trapezoid shoulders
  _ctx.beginPath();
  _ctx.moveTo(neckCx - rs(0.06), neckBottom);
  _ctx.lineTo(neckCx - shoulderWidth, bodyBottom);
  _ctx.lineTo(neckCx + shoulderWidth, bodyBottom);
  _ctx.lineTo(neckCx + rs(0.06), neckBottom);
  _ctx.closePath();
  _ctx.fillStyle = prof.clothing;
  _ctx.fill();

  // Collar / neckline detail
  _ctx.beginPath();
  _ctx.moveTo(neckCx - rs(0.05), neckBottom);
  _ctx.quadraticCurveTo(neckCx, neckBottom + rs(0.06), neckCx + rs(0.05), neckBottom);
  _ctx.strokeStyle = darken(prof.clothing, 0.7);
  _ctx.lineWidth = rs(0.004);
  _ctx.stroke();
}

/**
 * Draw the neck.
 * @param {CharacterProfile} prof
 * @param {number} cx
 * @param {number} top
 * @param {number} bottom
 */
function drawNeck(prof, cx, top, bottom) {
  const neckW = rs(0.045);
  _ctx.beginPath();
  _ctx.moveTo(cx - neckW, top);
  _ctx.lineTo(cx - neckW * 1.15, bottom);
  _ctx.lineTo(cx + neckW * 1.15, bottom);
  _ctx.lineTo(cx + neckW, top);
  _ctx.closePath();
  _ctx.fillStyle = prof.skin;
  _ctx.fill();
}

/**
 * Draw the head (skin oval).
 * @param {CharacterProfile} prof
 * @param {number} cx
 * @param {number} cy
 * @param {number} radX
 * @param {number} radY
 */
function drawHead(prof, cx, cy, radX, radY) {
  fillEllipse(cx, cy, radX, radY, prof.skin);
}

/**
 * Draw front bangs over the forehead.
 * @param {CharacterProfile} prof
 * @param {number} headCx
 * @param {number} headCy
 * @param {number} headRx
 * @param {number} headRy
 */
function drawHairFront(prof, headCx, headCy, headRx, headRy) {
  const bangTop = headCy - headRy * 1.05;
  const bangBottom = headCy - headRy * 0.25;
  const bangWidth = headRx * 1.15;

  // Main bangs shape
  _ctx.beginPath();
  _ctx.moveTo(headCx - bangWidth, bangBottom);
  _ctx.quadraticCurveTo(headCx - bangWidth, bangTop - headRy * 0.15, headCx, bangTop);
  _ctx.quadraticCurveTo(headCx + bangWidth, bangTop - headRy * 0.15, headCx + bangWidth, bangBottom);

  // Jagged bang tips (5 points)
  const segments = 5;
  for (let i = segments; i >= 0; i--) {
    const frac = i / segments;
    const bx = headCx - bangWidth + frac * bangWidth * 2;
    const tipOffset = (i % 2 === 0) ? rs(0.02) : -rs(0.015);
    _ctx.lineTo(bx, bangBottom + tipOffset);
  }
  _ctx.closePath();
  _ctx.fillStyle = prof.hair;
  _ctx.fill();

  // Hair highlight
  _ctx.beginPath();
  _ctx.moveTo(headCx - bangWidth * 0.4, bangTop + headRy * 0.15);
  _ctx.quadraticCurveTo(
    headCx - bangWidth * 0.1, bangTop + headRy * 0.05,
    headCx + bangWidth * 0.2, bangTop + headRy * 0.2
  );
  _ctx.strokeStyle = lighten(prof.hair, 0.3);
  _ctx.lineWidth = rs(0.006);
  _ctx.lineCap = "round";
  _ctx.stroke();
}

// ── Expression-Specific Drawing ──────────────────────

/**
 * @typedef {Object} ExpressionGeometry
 * @property {function} drawEyes
 * @property {function} drawEyebrows
 * @property {function} drawMouth
 * @property {function} drawExtras
 */

/**
 * Get expression drawing functions for a given expression name.
 * @param {string} expr
 * @returns {ExpressionGeometry}
 */
function getExpressionDrawers(expr) {
  switch (expr) {
    case "happy":    return { drawEyes: drawEyesHappy, drawEyebrows: drawEyebrowsHappy, drawMouth: drawMouthHappy, drawExtras: drawExtrasHappy };
    case "troubled": return { drawEyes: drawEyesTroubled, drawEyebrows: drawEyebrowsTroubled, drawMouth: drawMouthTroubled, drawExtras: drawExtrasTroubled };
    case "angry":    return { drawEyes: drawEyesAngry, drawEyebrows: drawEyebrowsAngry, drawMouth: drawMouthAngry, drawExtras: drawExtrasNone };
    case "surprised":return { drawEyes: drawEyesSurprised, drawEyebrows: drawEyebrowsSurprised, drawMouth: drawMouthSurprised, drawExtras: drawExtrasNone };
    case "thinking": return { drawEyes: drawEyesThinking, drawEyebrows: drawEyebrowsThinking, drawMouth: drawMouthThinking, drawExtras: drawExtrasThinking };
    default:         return { drawEyes: drawEyesNormal, drawEyebrows: drawEyebrowsNormal, drawMouth: drawMouthNormal, drawExtras: drawExtrasNone };
  }
}

// ── Eyes ──────────────────────

/**
 * Draw normal relaxed eyes.
 * @param {CharacterProfile} prof
 * @param {number} cx - face centre X
 * @param {number} cy - eye vertical centre Y
 * @param {number} scale - overall face scale
 * @param {number} blinkFactor - 0=open, 1=closed
 */
function drawEyesNormal(prof, cx, cy, scale, blinkFactor) {
  const eyeSpacing = scale * 0.28;
  const eyeW = scale * 0.13;
  const eyeH = scale * 0.10;
  const openH = eyeH * (1 - blinkFactor);

  for (const side of [-1, 1]) {
    const ex = cx + eyeSpacing * side;

    if (openH < scale * 0.01) {
      // Closed — thin line
      _ctx.beginPath();
      _ctx.moveTo(ex - eyeW, cy);
      _ctx.lineTo(ex + eyeW, cy);
      _ctx.strokeStyle = darken(prof.hair, 0.5);
      _ctx.lineWidth = rs(0.005);
      _ctx.lineCap = "round";
      _ctx.stroke();
    } else {
      // White
      fillEllipse(ex, cy, eyeW, openH, "#ffffff");
      strokeEllipse(ex, cy, eyeW, openH, darken(prof.hair, 0.4), rs(0.003));
      // Iris
      const irisR = openH * 0.6;
      fillEllipse(ex, cy, irisR, irisR, prof.eyes);
      // Pupil
      fillEllipse(ex, cy, irisR * 0.45, irisR * 0.45, "#111111");
      // Highlight
      fillEllipse(ex + irisR * 0.3, cy - irisR * 0.3, irisR * 0.25, irisR * 0.25, "rgba(255,255,255,0.85)");
    }
  }
}

/**
 * Draw happy eyes (curved arcs — smiling eyes).
 */
function drawEyesHappy(prof, cx, cy, scale, blinkFactor) {
  const eyeSpacing = scale * 0.28;
  const eyeW = scale * 0.12;

  if (blinkFactor > 0.7) {
    drawEyesNormal(prof, cx, cy, scale, 1);
    return;
  }

  for (const side of [-1, 1]) {
    const ex = cx + eyeSpacing * side;
    _ctx.beginPath();
    _ctx.arc(ex, cy + scale * 0.02, eyeW, Math.PI * 1.1, Math.PI * 1.9);
    _ctx.strokeStyle = darken(prof.hair, 0.4);
    _ctx.lineWidth = rs(0.006);
    _ctx.lineCap = "round";
    _ctx.stroke();
  }
}

/**
 * Draw troubled/worried eyes (slightly drooped).
 */
function drawEyesTroubled(prof, cx, cy, scale, blinkFactor) {
  const eyeSpacing = scale * 0.28;
  const eyeW = scale * 0.12;
  const eyeH = scale * 0.08 * (1 - blinkFactor);

  for (const side of [-1, 1]) {
    const ex = cx + eyeSpacing * side;
    const droop = scale * 0.015 * side;

    if (eyeH < scale * 0.01) {
      _ctx.beginPath();
      _ctx.moveTo(ex - eyeW, cy + droop);
      _ctx.lineTo(ex + eyeW, cy - droop);
      _ctx.strokeStyle = darken(prof.hair, 0.5);
      _ctx.lineWidth = rs(0.005);
      _ctx.lineCap = "round";
      _ctx.stroke();
    } else {
      _ctx.save();
      _ctx.translate(ex, cy);
      _ctx.rotate(droop * 0.02);
      fillEllipse(0, 0, eyeW, eyeH, "#ffffff");
      strokeEllipse(0, 0, eyeW, eyeH, darken(prof.hair, 0.4), rs(0.003));
      const irisR = eyeH * 0.55;
      fillEllipse(0, irisR * 0.15, irisR, irisR, prof.eyes);
      fillEllipse(0, irisR * 0.15, irisR * 0.4, irisR * 0.4, "#111111");
      fillEllipse(irisR * 0.25, -irisR * 0.2, irisR * 0.2, irisR * 0.2, "rgba(255,255,255,0.7)");
      _ctx.restore();
    }
  }
}

/**
 * Draw angry/sharp narrow eyes.
 */
function drawEyesAngry(prof, cx, cy, scale, blinkFactor) {
  const eyeSpacing = scale * 0.28;
  const eyeW = scale * 0.14;
  const eyeH = scale * 0.06 * (1 - blinkFactor);

  for (const side of [-1, 1]) {
    const ex = cx + eyeSpacing * side;

    if (eyeH < scale * 0.01) {
      _ctx.beginPath();
      _ctx.moveTo(ex - eyeW, cy);
      _ctx.lineTo(ex + eyeW, cy);
      _ctx.strokeStyle = darken(prof.hair, 0.5);
      _ctx.lineWidth = rs(0.006);
      _ctx.lineCap = "round";
      _ctx.stroke();
    } else {
      // Sharper, narrower shape
      _ctx.beginPath();
      _ctx.moveTo(ex - eyeW, cy + eyeH * 0.3 * side);
      _ctx.quadraticCurveTo(ex, cy - eyeH, ex + eyeW, cy - eyeH * 0.3 * side);
      _ctx.quadraticCurveTo(ex, cy + eyeH * 0.6, ex - eyeW, cy + eyeH * 0.3 * side);
      _ctx.fillStyle = "#ffffff";
      _ctx.fill();
      _ctx.strokeStyle = darken(prof.hair, 0.4);
      _ctx.lineWidth = rs(0.003);
      _ctx.stroke();

      // Small intense iris
      const irisR = eyeH * 0.5;
      fillEllipse(ex, cy, irisR, irisR, prof.eyes);
      fillEllipse(ex, cy, irisR * 0.5, irisR * 0.5, "#111111");
    }
  }
}

/**
 * Draw surprised wide round eyes.
 */
function drawEyesSurprised(prof, cx, cy, scale, blinkFactor) {
  const eyeSpacing = scale * 0.28;
  const eyeW = scale * 0.15;
  const eyeH = scale * 0.14 * (1 - blinkFactor);

  for (const side of [-1, 1]) {
    const ex = cx + eyeSpacing * side;

    if (eyeH < scale * 0.01) {
      _ctx.beginPath();
      _ctx.moveTo(ex - eyeW, cy);
      _ctx.lineTo(ex + eyeW, cy);
      _ctx.strokeStyle = darken(prof.hair, 0.5);
      _ctx.lineWidth = rs(0.005);
      _ctx.lineCap = "round";
      _ctx.stroke();
    } else {
      fillEllipse(ex, cy, eyeW, eyeH, "#ffffff");
      strokeEllipse(ex, cy, eyeW, eyeH, darken(prof.hair, 0.4), rs(0.003));
      const irisR = eyeH * 0.55;
      fillEllipse(ex, cy, irisR, irisR, prof.eyes);
      fillEllipse(ex, cy, irisR * 0.4, irisR * 0.4, "#111111");
      // Double highlight for surprised look
      fillEllipse(ex + irisR * 0.3, cy - irisR * 0.35, irisR * 0.28, irisR * 0.28, "rgba(255,255,255,0.9)");
      fillEllipse(ex - irisR * 0.15, cy + irisR * 0.2, irisR * 0.15, irisR * 0.15, "rgba(255,255,255,0.5)");
    }
  }
}

/**
 * Draw thinking eyes (one narrowed).
 */
function drawEyesThinking(prof, cx, cy, scale, blinkFactor) {
  const eyeSpacing = scale * 0.28;

  // Left eye — slightly narrowed
  {
    const ex = cx - eyeSpacing;
    const eyeW = scale * 0.11;
    const eyeH = scale * 0.06 * (1 - blinkFactor);

    if (eyeH < scale * 0.01) {
      _ctx.beginPath();
      _ctx.moveTo(ex - eyeW, cy);
      _ctx.lineTo(ex + eyeW, cy);
      _ctx.strokeStyle = darken(prof.hair, 0.5);
      _ctx.lineWidth = rs(0.005);
      _ctx.lineCap = "round";
      _ctx.stroke();
    } else {
      fillEllipse(ex, cy, eyeW, eyeH, "#ffffff");
      strokeEllipse(ex, cy, eyeW, eyeH, darken(prof.hair, 0.4), rs(0.003));
      const irisR = eyeH * 0.6;
      fillEllipse(ex + irisR * 0.3, cy, irisR, irisR, prof.eyes);
      fillEllipse(ex + irisR * 0.3, cy, irisR * 0.4, irisR * 0.4, "#111111");
    }
  }

  // Right eye — normal open, looking up-right
  {
    const ex = cx + eyeSpacing;
    const eyeW = scale * 0.13;
    const eyeH = scale * 0.10 * (1 - blinkFactor);

    if (eyeH < scale * 0.01) {
      _ctx.beginPath();
      _ctx.moveTo(ex - eyeW, cy);
      _ctx.lineTo(ex + eyeW, cy);
      _ctx.strokeStyle = darken(prof.hair, 0.5);
      _ctx.lineWidth = rs(0.005);
      _ctx.lineCap = "round";
      _ctx.stroke();
    } else {
      fillEllipse(ex, cy, eyeW, eyeH, "#ffffff");
      strokeEllipse(ex, cy, eyeW, eyeH, darken(prof.hair, 0.4), rs(0.003));
      const irisR = eyeH * 0.55;
      // Looking upper-right
      fillEllipse(ex + irisR * 0.4, cy - irisR * 0.3, irisR, irisR, prof.eyes);
      fillEllipse(ex + irisR * 0.4, cy - irisR * 0.3, irisR * 0.4, irisR * 0.4, "#111111");
      fillEllipse(ex + irisR * 0.6, cy - irisR * 0.6, irisR * 0.22, irisR * 0.22, "rgba(255,255,255,0.8)");
    }
  }
}

// ── Eyebrows ──────────────────────

/**
 * Draw neutral eyebrow arcs.
 */
function drawEyebrowsNormal(prof, cx, cy, scale) {
  const spacing = scale * 0.28;
  const browW = scale * 0.12;

  for (const side of [-1, 1]) {
    const bx = cx + spacing * side;
    const by = cy - scale * 0.14;
    _ctx.beginPath();
    _ctx.moveTo(bx - browW * side, by + scale * 0.01);
    _ctx.quadraticCurveTo(bx, by - scale * 0.02, bx + browW * side, by + scale * 0.005);
    _ctx.strokeStyle = darken(prof.hair, 0.6);
    _ctx.lineWidth = rs(0.006);
    _ctx.lineCap = "round";
    _ctx.stroke();
  }
}

/**
 * Draw raised happy eyebrows.
 */
function drawEyebrowsHappy(prof, cx, cy, scale) {
  const spacing = scale * 0.28;
  const browW = scale * 0.11;

  for (const side of [-1, 1]) {
    const bx = cx + spacing * side;
    const by = cy - scale * 0.17;
    _ctx.beginPath();
    _ctx.moveTo(bx - browW * side, by + scale * 0.015);
    _ctx.quadraticCurveTo(bx, by - scale * 0.025, bx + browW * side, by + scale * 0.01);
    _ctx.strokeStyle = darken(prof.hair, 0.6);
    _ctx.lineWidth = rs(0.005);
    _ctx.lineCap = "round";
    _ctx.stroke();
  }
}

/**
 * Draw worried/angled eyebrows.
 */
function drawEyebrowsTroubled(prof, cx, cy, scale) {
  const spacing = scale * 0.28;
  const browW = scale * 0.12;

  for (const side of [-1, 1]) {
    const bx = cx + spacing * side;
    const by = cy - scale * 0.14;
    // Inner end raised, outer end lowered
    _ctx.beginPath();
    _ctx.moveTo(bx - browW * side, by + scale * 0.025);
    _ctx.quadraticCurveTo(bx, by - scale * 0.03, bx + browW * side, by - scale * 0.015 * side);
    _ctx.strokeStyle = darken(prof.hair, 0.6);
    _ctx.lineWidth = rs(0.006);
    _ctx.lineCap = "round";
    _ctx.stroke();
  }
}

/**
 * Draw V-shaped angry eyebrows.
 */
function drawEyebrowsAngry(prof, cx, cy, scale) {
  const spacing = scale * 0.28;
  const browW = scale * 0.13;

  for (const side of [-1, 1]) {
    const bx = cx + spacing * side;
    const by = cy - scale * 0.13;
    // Sharp V angled inward-down
    _ctx.beginPath();
    _ctx.moveTo(bx + browW * side, by + scale * 0.02);
    _ctx.lineTo(bx - browW * 0.3 * side, by - scale * 0.035);
    _ctx.strokeStyle = darken(prof.hair, 0.5);
    _ctx.lineWidth = rs(0.007);
    _ctx.lineCap = "round";
    _ctx.stroke();
  }
}

/**
 * Draw surprised raised-high eyebrows.
 */
function drawEyebrowsSurprised(prof, cx, cy, scale) {
  const spacing = scale * 0.28;
  const browW = scale * 0.12;

  for (const side of [-1, 1]) {
    const bx = cx + spacing * side;
    const by = cy - scale * 0.19;
    _ctx.beginPath();
    _ctx.moveTo(bx - browW * side, by + scale * 0.01);
    _ctx.quadraticCurveTo(bx, by - scale * 0.03, bx + browW * side, by + scale * 0.005);
    _ctx.strokeStyle = darken(prof.hair, 0.6);
    _ctx.lineWidth = rs(0.006);
    _ctx.lineCap = "round";
    _ctx.stroke();
  }
}

/**
 * Draw thinking eyebrows (one raised higher).
 */
function drawEyebrowsThinking(prof, cx, cy, scale) {
  const spacing = scale * 0.28;
  const browW = scale * 0.11;

  // Left — lower, slightly furrowed
  {
    const bx = cx - spacing;
    const by = cy - scale * 0.13;
    _ctx.beginPath();
    _ctx.moveTo(bx + browW, by + scale * 0.01);
    _ctx.quadraticCurveTo(bx, by - scale * 0.01, bx - browW, by + scale * 0.015);
    _ctx.strokeStyle = darken(prof.hair, 0.6);
    _ctx.lineWidth = rs(0.006);
    _ctx.lineCap = "round";
    _ctx.stroke();
  }

  // Right — raised high
  {
    const bx = cx + spacing;
    const by = cy - scale * 0.18;
    _ctx.beginPath();
    _ctx.moveTo(bx - browW, by + scale * 0.01);
    _ctx.quadraticCurveTo(bx, by - scale * 0.03, bx + browW, by + scale * 0.005);
    _ctx.strokeStyle = darken(prof.hair, 0.6);
    _ctx.lineWidth = rs(0.006);
    _ctx.lineCap = "round";
    _ctx.stroke();
  }
}

// ── Mouth ──────────────────────

/**
 * Draw a normal slight smile.
 * @param {CharacterProfile} prof
 * @param {number} cx
 * @param {number} cy - mouth centre Y
 * @param {number} scale
 * @param {number} openness - lip-sync openness 0-1
 */
function drawMouthNormal(prof, cx, cy, scale, openness) {
  const mw = scale * 0.08;

  if (openness > 0.1) {
    // Open mouth
    const mh = scale * 0.03 * openness;
    fillEllipse(cx, cy, mw * (0.6 + openness * 0.4), mh + scale * 0.01, "#cc6666");
    fillEllipse(cx, cy + mh * 0.3, mw * 0.4 * openness, mh * 0.5, "#993333");
  } else {
    // Slight smile curve
    _ctx.beginPath();
    _ctx.moveTo(cx - mw, cy);
    _ctx.quadraticCurveTo(cx, cy + scale * 0.025, cx + mw, cy);
    _ctx.strokeStyle = "#cc8888";
    _ctx.lineWidth = rs(0.004);
    _ctx.lineCap = "round";
    _ctx.stroke();
  }
}

/**
 * Draw a wide happy smile.
 */
function drawMouthHappy(prof, cx, cy, scale, openness) {
  const mw = scale * 0.10;

  if (openness > 0.1) {
    const mh = scale * 0.04 * openness;
    fillEllipse(cx, cy, mw * (0.7 + openness * 0.3), mh + scale * 0.015, "#cc6666");
    fillEllipse(cx, cy + mh * 0.3, mw * 0.4 * openness, mh * 0.4, "#993333");
  } else {
    _ctx.beginPath();
    _ctx.moveTo(cx - mw, cy - scale * 0.005);
    _ctx.quadraticCurveTo(cx, cy + scale * 0.04, cx + mw, cy - scale * 0.005);
    _ctx.strokeStyle = "#cc7777";
    _ctx.lineWidth = rs(0.005);
    _ctx.lineCap = "round";
    _ctx.stroke();
  }
}

/**
 * Draw a small troubled frown.
 */
function drawMouthTroubled(prof, cx, cy, scale, openness) {
  const mw = scale * 0.06;

  if (openness > 0.1) {
    const mh = scale * 0.025 * openness;
    fillEllipse(cx, cy, mw * 0.5, mh + scale * 0.008, "#cc7777");
  } else {
    _ctx.beginPath();
    _ctx.moveTo(cx - mw, cy + scale * 0.005);
    _ctx.quadraticCurveTo(cx, cy - scale * 0.015, cx + mw, cy + scale * 0.005);
    _ctx.strokeStyle = "#cc8888";
    _ctx.lineWidth = rs(0.004);
    _ctx.lineCap = "round";
    _ctx.stroke();
  }
}

/**
 * Draw a tight angry line mouth.
 */
function drawMouthAngry(prof, cx, cy, scale, openness) {
  const mw = scale * 0.09;

  if (openness > 0.1) {
    const mh = scale * 0.02 * openness;
    // Slightly bared teeth look
    _ctx.beginPath();
    _ctx.moveTo(cx - mw * 0.6, cy - mh);
    _ctx.lineTo(cx + mw * 0.6, cy - mh);
    _ctx.lineTo(cx + mw * 0.5, cy + mh);
    _ctx.lineTo(cx - mw * 0.5, cy + mh);
    _ctx.closePath();
    _ctx.fillStyle = "#cc5555";
    _ctx.fill();
  } else {
    _ctx.beginPath();
    _ctx.moveTo(cx - mw, cy);
    _ctx.lineTo(cx + mw, cy);
    _ctx.strokeStyle = "#bb6666";
    _ctx.lineWidth = rs(0.005);
    _ctx.lineCap = "round";
    _ctx.stroke();
  }
}

/**
 * Draw a surprised open O-shape mouth.
 */
function drawMouthSurprised(prof, cx, cy, scale, openness) {
  const baseOpen = 0.5;
  const effectiveOpen = Math.max(baseOpen, openness);
  const mw = scale * 0.05 * (0.7 + effectiveOpen * 0.3);
  const mh = scale * 0.055 * effectiveOpen;

  fillEllipse(cx, cy, mw, mh, "#cc6666");
  fillEllipse(cx, cy + mh * 0.1, mw * 0.6, mh * 0.5, "#993333");
}

/**
 * Draw a thinking "hmm" mouth (small, offset).
 */
function drawMouthThinking(prof, cx, cy, scale, openness) {
  const mw = scale * 0.05;
  const offsetX = scale * 0.04;

  if (openness > 0.1) {
    const mh = scale * 0.02 * openness;
    fillEllipse(cx + offsetX, cy, mw * 0.5, mh + scale * 0.006, "#cc7777");
  } else {
    _ctx.beginPath();
    _ctx.moveTo(cx + offsetX - mw, cy);
    _ctx.quadraticCurveTo(cx + offsetX, cy - scale * 0.01, cx + offsetX + mw, cy + scale * 0.005);
    _ctx.strokeStyle = "#cc8888";
    _ctx.lineWidth = rs(0.004);
    _ctx.lineCap = "round";
    _ctx.stroke();
  }
}

// ── Nose ──────────────────────

/**
 * Draw a minimal anime nose (small line).
 * @param {number} cx
 * @param {number} cy
 * @param {number} scale
 */
function drawNose(cx, cy, scale) {
  _ctx.beginPath();
  _ctx.moveTo(cx, cy);
  _ctx.lineTo(cx - scale * 0.01, cy + scale * 0.02);
  _ctx.strokeStyle = "rgba(180,140,120,0.4)";
  _ctx.lineWidth = rs(0.003);
  _ctx.lineCap = "round";
  _ctx.stroke();
}

// ── Expression Extras ──────────────────────

/** No-op extras. */
function drawExtrasNone() {}

/**
 * Draw blush marks for happy expression.
 * @param {CharacterProfile} prof
 * @param {number} cx
 * @param {number} cy - cheek centre Y
 * @param {number} scale
 */
function drawExtrasHappy(prof, cx, cy, scale) {
  const spacing = scale * 0.30;
  const cheekY = cy + scale * 0.06;
  const blushR = scale * 0.045;

  for (const side of [-1, 1]) {
    fillEllipse(cx + spacing * side, cheekY, blushR, blushR * 0.6, "rgba(255,150,150,0.35)");
  }
}

/**
 * Draw a sweat drop for troubled expression.
 */
function drawExtrasTroubled(prof, cx, cy, scale) {
  const dx = cx + scale * 0.32;
  const dy = cy - scale * 0.14;
  const dropH = scale * 0.05;
  const dropW = scale * 0.02;

  _ctx.beginPath();
  _ctx.moveTo(dx, dy - dropH * 0.5);
  _ctx.quadraticCurveTo(dx + dropW, dy + dropH * 0.2, dx, dy + dropH * 0.5);
  _ctx.quadraticCurveTo(dx - dropW, dy + dropH * 0.2, dx, dy - dropH * 0.5);
  _ctx.fillStyle = "rgba(150,200,255,0.6)";
  _ctx.fill();
  _ctx.strokeStyle = "rgba(100,160,220,0.5)";
  _ctx.lineWidth = rs(0.002);
  _ctx.stroke();
}

/**
 * Draw thinking extras (small thought dots).
 */
function drawExtrasThinking(prof, cx, cy, scale) {
  // Three small circles above/beside head suggesting thought
  const baseX = cx + scale * 0.35;
  const baseY = cy - scale * 0.25;

  fillEllipse(baseX, baseY, scale * 0.015, scale * 0.015, "rgba(200,200,220,0.5)");
  fillEllipse(baseX + scale * 0.04, baseY - scale * 0.05, scale * 0.02, scale * 0.02, "rgba(200,200,220,0.45)");
  fillEllipse(baseX + scale * 0.09, baseY - scale * 0.10, scale * 0.028, scale * 0.028, "rgba(200,200,220,0.4)");
}

// ── Main Draw Routine ──────────────────────

/**
 * Render a single frame of the character.
 * @param {number} now - performance.now() timestamp
 */
function drawFrame(now) {
  if (!_ctx || !_profile || _width <= 0 || _height <= 0) return;

  const prof = _profile;

  // Clear
  _ctx.clearRect(0, 0, _width, _height);

  // 1. Background
  drawBackground(prof);

  // Animation values
  const bOffset = breathOffset(now);
  const blinkVal = updateBlink(now);
  const mouthOpen = updateLipSync(now);
  const exprT = expressionFactor(now);

  // Character geometry — all relative to canvas
  const centerX = _width * 0.5;
  const charTop = _height * 0.05;
  const charHeight = _height * 0.80;

  // Apply breathing offset to entire character
  const yOff = bOffset;

  // Head proportions (head is ~1/3 of visible area)
  const headRy = charHeight * 0.20;
  const headRx = headRy * 0.82;
  const headCy = charTop + charHeight * 0.28 + yOff;
  const headCx = centerX;

  // Neck
  const neckTop = headCy + headRy * 0.85;
  const neckBottom = headCy + headRy * 1.15;

  // Face reference points
  const faceCx = headCx;
  const eyeCy = headCy - headRy * 0.05;
  const noseCy = headCy + headRy * 0.25;
  const mouthCy = headCy + headRy * 0.48;
  const faceScale = headRy * 2;

  // Get expression drawers
  const curDrawers = getExpressionDrawers(_expression);
  const prevDrawers = getExpressionDrawers(_prevExpression);

  // 2. Hair back
  drawHairBack(prof, headCx, headCy, headRx, headRy);

  // 3. Body
  drawBody(prof, centerX, neckBottom + yOff);

  // 4. Neck
  drawNeck(prof, centerX, neckTop, neckBottom + yOff);

  // 5. Head
  drawHead(prof, headCx, headCy, headRx, headRy);

  // 6. Hair front (bangs)
  drawHairFront(prof, headCx, headCy, headRx, headRy);

  // 7. Eyes — with optional cross-fade
  if (exprT >= 1) {
    curDrawers.drawEyes(prof, faceCx, eyeCy, faceScale, blinkVal);
  } else {
    // Cross-fade: draw previous at (1-t) alpha, then current at t alpha
    _ctx.save();
    _ctx.globalAlpha = 1 - exprT;
    prevDrawers.drawEyes(prof, faceCx, eyeCy, faceScale, blinkVal);
    _ctx.globalAlpha = exprT;
    curDrawers.drawEyes(prof, faceCx, eyeCy, faceScale, blinkVal);
    _ctx.restore();
  }

  // 8. Eyebrows
  if (exprT >= 1) {
    curDrawers.drawEyebrows(prof, faceCx, eyeCy, faceScale);
  } else {
    _ctx.save();
    _ctx.globalAlpha = 1 - exprT;
    prevDrawers.drawEyebrows(prof, faceCx, eyeCy, faceScale);
    _ctx.globalAlpha = exprT;
    curDrawers.drawEyebrows(prof, faceCx, eyeCy, faceScale);
    _ctx.restore();
  }

  // 9. Nose
  drawNose(faceCx, noseCy, faceScale);

  // 10. Mouth
  if (exprT >= 1) {
    curDrawers.drawMouth(prof, faceCx, mouthCy, faceScale, mouthOpen);
  } else {
    _ctx.save();
    _ctx.globalAlpha = 1 - exprT;
    prevDrawers.drawMouth(prof, faceCx, mouthCy, faceScale, mouthOpen);
    _ctx.globalAlpha = exprT;
    curDrawers.drawMouth(prof, faceCx, mouthCy, faceScale, mouthOpen);
    _ctx.restore();
  }

  // 11. Expression extras
  if (exprT >= 1) {
    curDrawers.drawExtras(prof, faceCx, eyeCy, faceScale);
  } else if (exprT > 0.5) {
    _ctx.save();
    _ctx.globalAlpha = (exprT - 0.5) * 2;
    curDrawers.drawExtras(prof, faceCx, eyeCy, faceScale);
    _ctx.restore();
  }
}

// ── Silhouette Fallback ──────────────────────

/**
 * Draw a generic grey silhouette when no character is loaded.
 */
function drawSilhouette() {
  if (!_ctx || _width <= 0 || _height <= 0) return;

  _ctx.clearRect(0, 0, _width, _height);

  // Soft grey background
  const grad = _ctx.createLinearGradient(0, 0, 0, _height);
  grad.addColorStop(0, "#e8e8ec");
  grad.addColorStop(1, "#d0d0d8");
  _ctx.fillStyle = grad;
  _ctx.fillRect(0, 0, _width, _height);

  const cx = _width * 0.5;
  const headCy = _height * 0.32;
  const headR = Math.min(_width, _height) * 0.14;

  // Head silhouette
  fillEllipse(cx, headCy, headR, headR * 1.1, "#b0b0b8");

  // Body silhouette
  const bodyTop = headCy + headR * 1.1;
  _ctx.beginPath();
  _ctx.moveTo(cx - headR * 0.5, bodyTop);
  _ctx.lineTo(cx - headR * 2.2, _height);
  _ctx.lineTo(cx + headR * 2.2, _height);
  _ctx.lineTo(cx + headR * 0.5, bodyTop);
  _ctx.closePath();
  _ctx.fillStyle = "#b0b0b8";
  _ctx.fill();

  // Question mark
  _ctx.font = `${headR * 0.8}px sans-serif`;
  _ctx.fillStyle = "#9090a0";
  _ctx.textAlign = "center";
  _ctx.textBaseline = "middle";
  _ctx.fillText("?", cx, headCy);
}

// ── Animation Loop ──────────────────────

/**
 * The main requestAnimationFrame callback. Throttles to ~30 fps.
 * @param {number} timestamp
 */
function animationLoop(timestamp) {
  _animFrameId = requestAnimationFrame(animationLoop);

  if (timestamp - _lastFrameTime < FRAME_INTERVAL) return;
  _lastFrameTime = timestamp;

  if (!_profile) {
    drawSilhouette();
    return;
  }

  drawFrame(timestamp);
}

// ── Click Handler ──────────────────────

/**
 * Internal click event handler.
 * @param {MouseEvent} e
 */
function handleClick(e) {
  if (_clickCallback) {
    _clickCallback(e);
  }
}

// ── Public API ──────────────────────

/**
 * Initialise the bust-up renderer on a canvas element.
 * Sets up the rendering context, resize observer, and starts the animation loop.
 * @param {HTMLCanvasElement} canvas - The canvas element to draw on
 */
export function initBustup(canvas) {
  if (!canvas || !(canvas instanceof HTMLCanvasElement)) {
    throw new Error("initBustup requires a valid HTMLCanvasElement");
  }

  // Clean up any previous session
  disposeBustup();

  _canvas = canvas;
  _ctx = canvas.getContext("2d");

  // Initial sizing
  syncCanvasSize();

  // Observe container resize
  const parent = canvas.parentElement;
  if (parent && typeof ResizeObserver !== "undefined") {
    _resizeObserver = new ResizeObserver(() => {
      syncCanvasSize();
    });
    _resizeObserver.observe(parent);
  }

  // Click handler
  _canvas.addEventListener("click", handleClick);
  _canvas.style.cursor = "pointer";

  // Initialise blink timer
  scheduleNextBlink(performance.now());

  // Start animation loop
  _lastFrameTime = 0;
  _animFrameId = requestAnimationFrame(animationLoop);
}

/**
 * Stop the animation loop and clean up all resources.
 * Safe to call multiple times.
 */
export function disposeBustup() {
  if (_animFrameId) {
    cancelAnimationFrame(_animFrameId);
    _animFrameId = 0;
  }

  if (_resizeObserver) {
    _resizeObserver.disconnect();
    _resizeObserver = null;
  }

  if (_canvas) {
    _canvas.removeEventListener("click", handleClick);
    _canvas.style.cursor = "";
    _canvas = null;
  }

  _ctx = null;
  _characterName = null;
  _profile = null;
  _expression = "normal";
  _prevExpression = "normal";
  _isTalking = false;
  _clickCallback = null;
}

/**
 * Switch the displayed character by name.
 * Known names use predefined colour profiles; unknown names generate a
 * deterministic profile from a hash of the name string.
 * @param {string} name - Character name (e.g. "sakura", "kotoha")
 */
export function setCharacter(name) {
  if (!name || typeof name !== "string") {
    _characterName = null;
    _profile = null;
    return;
  }

  const key = name.toLowerCase();
  _characterName = key;
  _profile = PROFILES[key] || generateProfile(key);

  // Reset expression
  _expression = "normal";
  _prevExpression = "normal";
}

/**
 * Change the character's facial expression with a brief cross-fade transition.
 * @param {string} expression - One of: 'normal', 'happy', 'troubled', 'angry', 'surprised', 'thinking'
 */
export function setExpression(expression) {
  const expr = (expression || "normal").toLowerCase();
  if (!EXPRESSIONS.includes(expr)) {
    console.warn(`Unknown expression "${expression}", falling back to "normal"`);
    return setExpression("normal");
  }

  if (expr === _expression) return;

  _prevExpression = _expression;
  _expression = expr;
  _expressionTransitionStart = performance.now();
}

/**
 * Enable or disable lip-sync animation.
 * While talking, the mouth alternates between open and closed states.
 * @param {boolean} isTalking
 */
export function setTalking(isTalking) {
  _isTalking = Boolean(isTalking);
  if (_isTalking) {
    _lipSync.lastChange = performance.now();
    _lipSync.isOpen = false;
    _lipSync.patternIndex = 0;
  } else {
    _lipSync.openness = 0;
  }
}

/**
 * Register a click handler for character interaction.
 * Only one handler is active at a time; calling again replaces the previous.
 * @param {function} callback - Receives the native MouseEvent
 */
export function onClick(callback) {
  _clickCallback = typeof callback === "function" ? callback : null;
}

/**
 * Return the canvas element being used for rendering.
 * @returns {HTMLCanvasElement|null}
 */
export function getCanvas() {
  return _canvas;
}
