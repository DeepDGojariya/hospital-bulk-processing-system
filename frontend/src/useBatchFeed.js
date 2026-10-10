import { useEffect, useRef } from "react";

import { getBatch, progressSocketUrl } from "./api";

const POLL_INTERVAL_MS = 1000;

/**
 * Keeps a processing batch up to date: over the WebSocket when possible,
 * by polling when the socket cannot connect or drops before the batch ends.
 */
export function useBatchFeed(batch, onSnapshot, onLost) {
  const batchId = batch ? batch.batch_id : null;
  const processing = batch !== null && batch.status === "processing";
  const handlers = useRef({ onSnapshot, onLost });
  useEffect(() => {
    handlers.current = { onSnapshot, onLost };
  });

  useEffect(() => {
    if (!processing) {
      return undefined;
    }
    let stopped = false;
    let finished = false;
    let pollTimer = null;

    const receive = (snapshot) => {
      if (stopped) {
        return;
      }
      finished = snapshot.status !== "processing";
      handlers.current.onSnapshot(snapshot);
    };

    const poll = async () => {
      try {
        const { response, data } = await getBatch(batchId);
        if (response.status === 404) {
          clearInterval(pollTimer);
          if (!stopped) {
            handlers.current.onLost();
          }
        } else if (response.ok && data) {
          receive(data);
        }
      } catch {
        // Temporary network failure: try again on the next tick.
      }
    };

    const socket = new WebSocket(progressSocketUrl(batchId));
    socket.onmessage = (event) => receive(JSON.parse(event.data));
    socket.onclose = () => {
      // The server closes the socket once the batch finishes. Any earlier
      // close means we lost the live feed, so fall back to polling.
      if (!stopped && !finished && pollTimer === null) {
        pollTimer = setInterval(poll, POLL_INTERVAL_MS);
      }
    };

    return () => {
      stopped = true;
      socket.close();
      if (pollTimer !== null) {
        clearInterval(pollTimer);
      }
    };
  }, [batchId, processing]);
}
