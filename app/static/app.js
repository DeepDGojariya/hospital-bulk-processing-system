"use strict";

// Everything shown on the page comes from the API or the uploaded CSV, so it is
// always written with textContent, never as HTML.

const SAMPLE_CSV = [
  "name,address,phone",
  "General Hospital,123 Main St,555-1234",
  "City Medical Center,45 Oak Avenue,555-2345",
  '"St. Mary\'s, North Campus","9 High Street, Suite 2",',
  "Riverside Clinic,78 River Road,555-4567",
  "",
].join("\n");

const ROW_LABELS = {
  pending: "Pending",
  created: "Created",
  created_and_activated: "Activated",
  failed: "Failed",
};

const POLL_INTERVAL_MS = 1000;

const el = (id) => document.getElementById(id);
const fileInput = el("file");
const validateButton = el("validate");
const processButton = el("process");
const resumeButton = el("resume");
const message = el("message");
const errorList = el("errors");
const summary = el("summary");

let current = null; // latest batch snapshot from the server
let socket = null;
let pollTimer = null;
let clockTimer = null;
let startedAt = 0;
let requestInFlight = false;

el("sample-link").href = URL.createObjectURL(new Blob([SAMPLE_CSV], { type: "text/csv" }));

function setMessage(target, text, kind) {
  target.textContent = text;
  target.className = kind ? `message ${kind}` : "message";
}

function showErrors(errors) {
  errorList.replaceChildren(
    ...errors.map((error) => {
      const item = document.createElement("li");
      const where = error.row ? `Row ${error.row}` : "File";
      const field = error.field ? ` (${error.field})` : "";
      item.textContent = `${where}${field}: ${error.message}`;
      return item;
    }),
  );
  errorList.hidden = errors.length === 0;
}

function updateButtons() {
  const processing = current !== null && current.status === "processing";
  const blocked = requestInFlight || processing || fileInput.files.length === 0;
  validateButton.disabled = blocked;
  processButton.disabled = blocked;
  resumeButton.disabled = requestInFlight;
}

async function send(path, body) {
  const response = await fetch(path, { method: "POST", body });
  let data = null;
  try {
    data = await response.json();
  } catch {
    // Not JSON (for example a proxy error page); the status code is enough.
  }
  return { response, data };
}

function failureText(response, data) {
  if (data && typeof data.detail === "string") {
    return data.detail;
  }
  return `Request failed with status ${response.status}.`;
}

async function withRequest(target, action) {
  requestInFlight = true;
  updateButtons();
  try {
    await action();
  } catch {
    setMessage(target, "Could not reach the server. Check your connection and try again.", "error");
  } finally {
    requestInFlight = false;
    updateButtons();
  }
}

function fileForm() {
  const form = new FormData();
  form.append("file", fileInput.files[0]);
  return form;
}

function plural(count, word) {
  return `${count} ${word}${count === 1 ? "" : "s"}`;
}

async function validate() {
  await withRequest(message, async () => {
    setMessage(message, "Validating...");
    showErrors([]);
    const { response, data } = await send("/hospitals/bulk/validate", fileForm());
    if (!response.ok || !data) {
      setMessage(message, failureText(response, data), "error");
      showErrors((data && data.errors) || []);
    } else if (data.valid) {
      setMessage(message, `Valid: ${plural(data.total_rows, "hospital")} ready to upload.`, "ok");
    } else {
      setMessage(message, `Found ${plural(data.errors.length, "problem")}. Nothing was uploaded.`, "error");
      showErrors(data.errors);
    }
  });
}

async function process() {
  await withRequest(message, async () => {
    setMessage(message, "Uploading...");
    showErrors([]);
    const { response, data } = await send("/hospitals/bulk?mode=async", fileForm());
    if (response.status !== 202 || !data) {
      setMessage(message, failureText(response, data), "error");
      showErrors((data && data.errors) || []);
      return;
    }
    setMessage(message, "");
    follow(data);
  });
}

async function resume() {
  await withRequest(summary, async () => {
    const { response, data } = await send(`/hospitals/bulk/${current.batch_id}/resume?mode=async`);
    if (response.status !== 202 || !data) {
      setMessage(summary, failureText(response, data), "error");
      return;
    }
    follow(data);
  });
}

function stopFollowing() {
  if (socket) {
    const closing = socket;
    socket = null;
    closing.close();
  }
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

// The upstream answers every create after about the same delay, so results
// tend to arrive together. A running clock shows the page is still working.
function startClock() {
  stopClock();
  startedAt = Date.now();
  showElapsed();
  clockTimer = setInterval(showElapsed, 1000);
}

function stopClock() {
  if (clockTimer) {
    clearInterval(clockTimer);
    clockTimer = null;
  }
  el("elapsed").textContent = "";
}

function showElapsed() {
  const seconds = Math.floor((Date.now() - startedAt) / 1000);
  el("elapsed").textContent = ` \u00b7 ${seconds} s elapsed`;
}

function follow(snapshot) {
  stopFollowing();
  if (snapshot.status === "processing") {
    startClock();
  }
  render(snapshot);
  if (snapshot.status === "processing") {
    connect(snapshot.batch_id);
  }
}

function connect(batchId) {
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${scheme}://${location.host}/hospitals/bulk/${batchId}/ws`);
  socket = ws;
  ws.onmessage = (event) => {
    if (socket === ws) {
      render(JSON.parse(event.data));
    }
  };
  ws.onclose = () => {
    if (socket !== ws) {
      return;
    }
    socket = null;
    // The server closes the socket when the batch finishes. If it closed
    // earlier (or never connected), keep the page up to date by polling.
    if (current && current.status === "processing") {
      startPolling(batchId);
    }
  };
}

function startPolling(batchId) {
  pollTimer = setInterval(async () => {
    try {
      const response = await fetch(`/hospitals/bulk/${batchId}`);
      if (response.status === 404) {
        stopFollowing();
        setMessage(summary, "This batch is no longer available on the server.", "error");
        return;
      }
      if (response.ok && pollTimer) {
        render(await response.json());
      }
    } catch {
      // Temporary network failure: try again on the next tick.
    }
  }, POLL_INTERVAL_MS);
}

function summaryFor(batch) {
  if (batch.status === "processing") {
    const waiting =
      "All rows are sent to the Hospital Directory at once. It takes a few seconds " +
      "to answer, so results usually arrive together.";
    return [waiting, ""];
  }
  const seconds = `${batch.processing_time_seconds.toFixed(1)} s`;
  if (batch.status === "completed") {
    const all = plural(batch.total_hospitals, "hospital");
    return [`${all} created and activated in ${seconds}.`, "ok"];
  }
  if (batch.activation_error) {
    return [`All hospitals were created, but activation failed: ${batch.activation_error}`, "error"];
  }
  const failed = plural(batch.failed_hospitals, "row");
  return [`${failed} failed, so the batch was not activated. Resume to retry only the failed rows.`, "error"];
}

function cell(text, className) {
  const td = document.createElement("td");
  td.textContent = text;
  if (className) {
    td.className = className;
  }
  return td;
}

function render(batch) {
  current = batch;
  el("batch").hidden = false;
  el("batch-id").textContent = batch.batch_id;

  const status = el("status");
  status.textContent = batch.status;
  status.className = `badge ${batch.status}`;

  const processing = batch.status === "processing";
  const done = batch.processed_hospitals + batch.failed_hospitals;
  const bar = el("bar");
  bar.setAttribute("aria-valuemax", String(batch.total_hospitals));
  bar.setAttribute("aria-valuenow", String(done));
  bar.classList.toggle("busy", processing);
  el("bar-fill").style.width = `${(100 * done) / batch.total_hospitals}%`;

  const failed = batch.failed_hospitals ? `, ${batch.failed_hospitals} failed` : "";
  el("counts").textContent = `${batch.processed_hospitals} of ${batch.total_hospitals} created${failed}`;

  const [text, kind] = summaryFor(batch);
  setMessage(summary, text, kind);
  resumeButton.hidden = batch.status !== "failed";

  el("rows").replaceChildren(
    ...batch.hospitals.map((hospital) => {
      const row = document.createElement("tr");
      const badge = document.createElement("span");
      // While the batch runs, a row without a result yet is in flight.
      const inFlight = processing && hospital.status === "pending";
      badge.className = inFlight ? "badge working" : `badge ${hospital.status}`;
      badge.textContent = inFlight ? "Creating..." : ROW_LABELS[hospital.status] || hospital.status;
      const statusCell = document.createElement("td");
      statusCell.append(badge);
      row.append(
        cell(String(hospital.row)),
        cell(hospital.name),
        statusCell,
        cell(hospital.hospital_id === null ? "-" : String(hospital.hospital_id)),
        cell(hospital.error || "", "error-text"),
      );
      return row;
    }),
  );

  if (!processing) {
    stopFollowing();
    stopClock();
  }
  updateButtons();
}

fileInput.addEventListener("change", () => {
  setMessage(message, "");
  showErrors([]);
  updateButtons();
});
validateButton.addEventListener("click", validate);
processButton.addEventListener("click", process);
resumeButton.addEventListener("click", resume);
