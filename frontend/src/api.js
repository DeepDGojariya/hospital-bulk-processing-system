// The only module that knows the API's URLs.

async function request(path, options) {
  const response = await fetch(path, options);
  let data = null;
  try {
    data = await response.json();
  } catch {
    // Not JSON (for example a proxy error page); the status code is enough.
  }
  return { response, data };
}

function fileForm(file) {
  const form = new FormData();
  form.append("file", file);
  return form;
}

export const validateCsv = (file) =>
  request("/hospitals/bulk/validate", { method: "POST", body: fileForm(file) });

export const startBatch = (file) =>
  request("/hospitals/bulk?mode=async", { method: "POST", body: fileForm(file) });

export const resumeBatch = (batchId) =>
  request(`/hospitals/bulk/${batchId}/resume?mode=async`, { method: "POST" });

export const getBatch = (batchId) => request(`/hospitals/bulk/${batchId}`);

export const listBatches = () => request("/hospitals/bulk");

export function progressSocketUrl(batchId) {
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  return `${scheme}://${window.location.host}/hospitals/bulk/${batchId}/ws`;
}

export function failureText(response, data) {
  if (data && typeof data.detail === "string") {
    return data.detail;
  }
  return `Request failed with status ${response.status}.`;
}

export const UNREACHABLE = "Could not reach the server. Check your connection and try again.";
