// ── Shared Chat Stream ──────────────────────────────────
// Common SSE chat streaming logic used across all chat modules.
// Extracts the duplicated fetch + ReadableStream + SSE parse loop
// into a single reusable function with callback-based UI injection.

import { parseConvSSE, getErrorMessage } from "./sse-parser.js";
import { createLogger } from "./logger.js";

const logger = createLogger("chat-stream");

/**
 * Fetch the active stream for an anima.
 * @param {string} animaName
 * @returns {Promise<object|null>} Active stream info or null
 */
export async function fetchActiveStream(animaName) {
  try {
    const res = await fetch(`/api/animas/${encodeURIComponent(animaName)}/stream/active`);
    if (!res.ok) return null;
    const data = await res.json();
    return data.active ? data : null;
  } catch {
    return null;
  }
}

/**
 * Fetch progress of a specific stream.
 * @param {string} animaName
 * @param {string} responseId
 * @returns {Promise<object|null>}
 */
export async function fetchStreamProgress(animaName, responseId) {
  try {
    const res = await fetch(
      `/api/animas/${encodeURIComponent(animaName)}/stream/${encodeURIComponent(responseId)}/progress`
    );
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

/**
 * SSE chat stream processor.
 *
 * Handles the full lifecycle: fetch -> ReadableStream -> SSE parse -> callbacks.
 * UI-specific logic (bubble updates, Live2D expressions, state management)
 * is injected via the callbacks parameter.
 *
 * @param {string} animaName - Target Anima name
 * @param {string|FormData} body - Request body (JSON string or FormData)
 * @param {AbortSignal|null} signal - Optional AbortSignal for cancellation
 * @param {object} callbacks - Event callbacks
 * @param {function(string): void} [callbacks.onTextDelta] - Text delta received
 * @param {function(string): void} [callbacks.onToolStart] - Tool execution started (tool name)
 * @param {function(): void} [callbacks.onToolEnd] - Tool execution ended
 * @param {function({summary: string, emotion: string}): void} [callbacks.onDone] - Stream completed
 * @param {function({message: string}): void} [callbacks.onError] - SSE error event received
 * @param {function(object): void} [callbacks.onBootstrap] - Bootstrap event (data object)
 * @param {function(): void} [callbacks.onChainStart] - Chain continuation event
 * @param {function({message: string}): void} [callbacks.onHeartbeatRelayStart] - Heartbeat relay started
 * @param {function({text: string}): void} [callbacks.onHeartbeatRelay] - Heartbeat relay text chunk
 * @param {function(): void} [callbacks.onHeartbeatRelayDone] - Heartbeat relay completed
 * @param {function(): void} [callbacks.onReconnecting] - Reconnection attempt starting
 * @param {function(): void} [callbacks.onReconnected] - Reconnection successful
 * @returns {Promise<void>}
 * @throws {Error} On HTTP error (non-ok response) or network failure
 */
export async function streamChat(animaName, body, signal, callbacks) {
  const url = `/api/animas/${encodeURIComponent(animaName)}/chat/stream`;
  const start = performance.now();
  logger.info(`Stream start: ${animaName}`);

  // Track response ID and last event ID for reconnection
  let responseId = null;
  let lastEventId = null;

  const headers = body instanceof FormData ? {} : { "Content-Type": "application/json" };

  const res = await fetch(url, {
    method: "POST",
    headers,
    body,
    ...(signal ? { signal } : {}),
  });

  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    logger.error(`Stream failed: ${res.status} ${text}`);
    throw new Error(`API ${res.status}: ${text}`);
  }

  try {
    await _processStream(res, callbacks, (id) => { responseId = id; }, (id) => { lastEventId = id; }, signal);
  } catch (err) {
    if (err.name === "AbortError") throw err;

    // Attempt reconnection with exponential backoff
    if (responseId) {
      logger.info(`Stream interrupted, attempting reconnect for ${responseId}`);
      const reconnected = await _reconnectWithBackoff(
        animaName, responseId, lastEventId, body, signal, callbacks,
      );
      if (reconnected) return;
    }

    throw err;
  }

  const elapsed = ((performance.now() - start) / 1000).toFixed(1);
  logger.info(`Stream complete: ${animaName} (${elapsed}s)`);
}

/**
 * Process a ReadableStream response, parsing SSE events.
 */
async function _processStream(res, callbacks, setResponseId, setLastEventId, signal) {
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      if (signal?.aborted) throw new DOMException("Aborted", "AbortError");

      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const { parsed, remaining } = parseConvSSE(buffer);
      buffer = remaining;

      for (const { id, event, data } of parsed) {
        // Track event IDs for reconnection
        if (id) setLastEventId(id);

        switch (event) {
          case "stream_start":
            if (data.response_id) setResponseId(data.response_id);
            break;

          case "text_delta":
            callbacks.onTextDelta?.(data.text || "");
            break;

          case "tool_start":
            callbacks.onToolStart?.(data.tool_name);
            break;

          case "tool_end":
            callbacks.onToolEnd?.();
            break;

          case "done":
            callbacks.onDone?.({
              summary: data.summary || null,
              emotion: data.emotion || "neutral",
            });
            break;

          case "error":
            callbacks.onError?.({ message: getErrorMessage(data) });
            break;

          case "bootstrap":
            callbacks.onBootstrap?.(data);
            break;

          case "chain_start":
            callbacks.onChainStart?.();
            break;

          case "heartbeat_relay_start":
            callbacks.onHeartbeatRelayStart?.({ message: data.message || "" });
            break;

          case "heartbeat_relay":
            callbacks.onHeartbeatRelay?.({ text: data.text || "" });
            break;

          case "heartbeat_relay_done":
            callbacks.onHeartbeatRelayDone?.();
            break;
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}

/**
 * Reconnect with exponential backoff (1s -> 2s -> 4s -> ... max 30s, 5 attempts).
 */
async function _reconnectWithBackoff(animaName, responseId, lastEventId, originalBody, signal, callbacks) {
  const MAX_RETRIES = 5;
  const MAX_DELAY = 30000;
  let delay = 1000;

  for (let attempt = 1; attempt <= MAX_RETRIES; attempt++) {
    if (signal?.aborted) return false;

    logger.info(`Reconnect attempt ${attempt}/${MAX_RETRIES} (delay: ${delay}ms)`);
    callbacks.onReconnecting?.();

    await new Promise((r) => setTimeout(r, delay));

    try {
      // Parse from_person from original body
      let fromPerson = "human";
      if (typeof originalBody === "string") {
        try { fromPerson = JSON.parse(originalBody).from_person || "human"; } catch { /* ignore */ }
      }

      const resumeBody = JSON.stringify({
        message: "",
        from_person: fromPerson,
        resume: responseId,
        last_event_id: lastEventId || "",
      });

      const url = `/api/animas/${encodeURIComponent(animaName)}/chat/stream`;
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: resumeBody,
        ...(signal ? { signal } : {}),
      });

      if (!res.ok) {
        logger.warn(`Reconnect failed: ${res.status}`);
        delay = Math.min(delay * 2, MAX_DELAY);
        continue;
      }

      callbacks.onReconnected?.();
      await _processStream(res, callbacks, () => {}, (id) => { lastEventId = id; }, signal);
      return true;
    } catch (err) {
      if (err.name === "AbortError") return false;
      logger.warn(`Reconnect attempt ${attempt} error: ${err.message}`);
      delay = Math.min(delay * 2, MAX_DELAY);
    }
  }

  logger.error("All reconnect attempts failed");
  return false;
}
