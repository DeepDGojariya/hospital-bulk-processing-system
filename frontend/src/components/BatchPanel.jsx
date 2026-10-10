import { useEffect, useState } from "react";

import { failureText, resumeBatch, UNREACHABLE } from "../api";
import { summaryFor } from "../format";
import ProgressBar from "./ProgressBar";
import ResultsTable from "./ResultsTable";
import StatusBadge from "./StatusBadge";

// The upstream answers every create after about the same delay, so results
// tend to arrive together. A running clock shows the page is still working.
function Elapsed() {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    const started = Date.now();
    const timer = setInterval(() => setSeconds(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => clearInterval(timer);
  }, []);
  return <span>{` · ${seconds} s elapsed`}</span>;
}

export default function BatchPanel({ batch, lost, onResumed }) {
  const [resuming, setResuming] = useState(false);
  const [resumeError, setResumeError] = useState("");

  const processing = batch.status === "processing";
  const done = batch.processed_hospitals + batch.failed_hospitals;
  const summary = summaryFor(batch);
  const failed = batch.failed_hospitals ? `, ${batch.failed_hospitals} failed` : "";

  async function resume() {
    setResuming(true);
    setResumeError("");
    try {
      const { response, data } = await resumeBatch(batch.batch_id);
      if (response.status === 202 && data) {
        onResumed(data);
      } else {
        setResumeError(failureText(response, data));
      }
    } catch {
      setResumeError(UNREACHABLE);
    } finally {
      setResuming(false);
    }
  }

  return (
    <section className="card" aria-labelledby="batch-heading">
      <h2 id="batch-heading">2. Progress</h2>
      <p className="batch-line">
        <span>
          Batch <code>{batch.batch_id}</code>
        </span>
        <StatusBadge kind={batch.status}>{batch.status}</StatusBadge>
      </p>
      <ProgressBar done={done} total={batch.total_hospitals} busy={processing} />
      <p className="counts">
        <span aria-live="polite">
          {batch.processed_hospitals} of {batch.total_hospitals} created{failed}
        </span>
        {processing && <Elapsed key={batch.batch_id} />}
      </p>
      <p className={`message ${summary.kind}`} role="status">
        {summary.text}
      </p>
      {lost && <p className="message error">This batch is no longer available on the server.</p>}
      {resumeError && <p className="message error">{resumeError}</p>}
      {batch.status === "failed" && (
        <button type="button" className="resume" onClick={resume} disabled={resuming}>
          Resume failed batch
        </button>
      )}
      <ResultsTable hospitals={batch.hospitals} processing={processing} />
    </section>
  );
}
