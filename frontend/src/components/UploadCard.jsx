import { useState } from "react";

import { failureText, startBatch, UNREACHABLE, validateCsv } from "../api";
import { plural } from "../format";

const SAMPLE_CSV = [
  "name,address,phone",
  "General Hospital,123 Main St,555-1234",
  "City Medical Center,45 Oak Avenue,555-2345",
  '"St. Mary\'s, North Campus","9 High Street, Suite 2",',
  "Riverside Clinic,78 River Road,555-4567",
  "",
].join("\n");
const SAMPLE_HREF = `data:text/csv;charset=utf-8,${encodeURIComponent(SAMPLE_CSV)}`;

const NO_MESSAGE = { text: "", kind: "" };

function describe(error) {
  const where = error.row ? `Row ${error.row}` : "File";
  const field = error.field ? ` (${error.field})` : "";
  return `${where}${field}: ${error.message}`;
}

export default function UploadCard({ busy, onStarted }) {
  const [file, setFile] = useState(null);
  const [message, setMessage] = useState(NO_MESSAGE);
  const [errors, setErrors] = useState([]);
  const [pending, setPending] = useState(false);

  const blocked = !file || pending || busy;

  function chooseFile(event) {
    setFile(event.target.files[0] || null);
    setMessage(NO_MESSAGE);
    setErrors([]);
  }

  async function run(progressText, action) {
    setPending(true);
    setMessage({ text: progressText, kind: "" });
    setErrors([]);
    try {
      await action();
    } catch {
      setMessage({ text: UNREACHABLE, kind: "error" });
    } finally {
      setPending(false);
    }
  }

  function reject(response, data) {
    setMessage({ text: failureText(response, data), kind: "error" });
    setErrors((data && data.errors) || []);
  }

  const validate = () =>
    run("Validating...", async () => {
      const { response, data } = await validateCsv(file);
      if (!response.ok || !data) {
        reject(response, data);
      } else if (data.valid) {
        const ready = plural(data.total_rows, "hospital");
        setMessage({ text: `Valid: ${ready} ready to upload.`, kind: "ok" });
      } else {
        const found = plural(data.errors.length, "problem");
        setMessage({ text: `Found ${found}. Nothing was uploaded.`, kind: "error" });
        setErrors(data.errors);
      }
    });

  const process = () =>
    run("Uploading...", async () => {
      const { response, data } = await startBatch(file);
      if (response.status !== 202 || !data) {
        reject(response, data);
        return;
      }
      setMessage(NO_MESSAGE);
      onStarted(data);
    });

  return (
    <section className="card" aria-labelledby="upload-heading">
      <h2 id="upload-heading">1. Choose a CSV</h2>
      <p className="hint">
        Columns: <code>name,address,phone</code>. Phone is optional.{" "}
        <a href={SAMPLE_HREF} download="hospitals-sample.csv">
          Download a sample
        </a>
      </p>
      <label className="file">
        <span className="visually-hidden">CSV file</span>
        <input type="file" accept=".csv,text/csv" onChange={chooseFile} />
      </label>
      <div className="actions">
        <button type="button" className="secondary" onClick={validate} disabled={blocked}>
          Validate
        </button>
        <button type="button" onClick={process} disabled={blocked}>
          Upload and process
        </button>
      </div>
      <p className={`message ${message.kind}`} role="status">
        {message.text}
      </p>
      {errors.length > 0 && (
        <ul className="errors">
          {errors.map((error, index) => (
            <li key={index}>{describe(error)}</li>
          ))}
        </ul>
      )}
    </section>
  );
}
