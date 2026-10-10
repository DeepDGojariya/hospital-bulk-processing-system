export const ROW_LABELS = {
  pending: "Pending",
  created: "Created",
  created_and_activated: "Activated",
  failed: "Failed",
};

export function plural(count, word) {
  return `${count} ${word}${count === 1 ? "" : "s"}`;
}

export function shortId(batchId) {
  return batchId.slice(0, 8);
}

export function formatStarted(isoTimestamp) {
  return new Date(isoTimestamp).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "medium",
  });
}

/** The one-line outcome shown under the progress bar. */
export function summaryFor(batch) {
  if (batch.status === "processing") {
    return {
      text:
        "All rows are sent to the Hospital Directory at once. It takes a few seconds " +
        "to answer, so results usually arrive together.",
      kind: "",
    };
  }
  if (batch.status === "completed") {
    const seconds = batch.processing_time_seconds.toFixed(1);
    return {
      text: `${plural(batch.total_hospitals, "hospital")} created and activated in ${seconds} s.`,
      kind: "ok",
    };
  }
  if (batch.activation_error) {
    return {
      text: `All hospitals were created, but activation failed: ${batch.activation_error}`,
      kind: "error",
    };
  }
  return {
    text:
      `${plural(batch.failed_hospitals, "row")} failed, so the batch was not activated. ` +
      "Resume to retry only the failed rows.",
    kind: "error",
  };
}
