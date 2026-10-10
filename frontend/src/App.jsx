import { useCallback, useEffect, useState } from "react";

import { getBatch, listBatches, UNREACHABLE } from "./api";
import BatchList from "./components/BatchList";
import BatchPanel from "./components/BatchPanel";
import UploadCard from "./components/UploadCard";
import { useBatchFeed } from "./useBatchFeed";

export default function App() {
  const [batch, setBatch] = useState(null); // the batch shown in the progress panel
  const [lost, setLost] = useState(false);
  const [batches, setBatches] = useState([]);
  const [listError, setListError] = useState("");

  const refreshBatches = useCallback(async () => {
    try {
      const { response, data } = await listBatches();
      if (response.ok && Array.isArray(data)) {
        setBatches(data);
        setListError("");
      } else {
        setListError("Could not load the batch list.");
      }
    } catch {
      setListError(UNREACHABLE);
    }
  }, []);

  const show = useCallback((snapshot) => {
    setLost(false);
    setBatch(snapshot);
  }, []);

  const openBatch = useCallback(
    async (batchId) => {
      try {
        const { response, data } = await getBatch(batchId);
        if (response.ok && data) {
          show(data);
          // The panel sits above the list, so bring it into view.
          document.getElementById("batch-heading")?.scrollIntoView?.({ behavior: "smooth" });
        } else {
          setListError("That batch is no longer available on the server.");
          refreshBatches();
        }
      } catch {
        setListError(UNREACHABLE);
      }
    },
    [show, refreshBatches],
  );

  useBatchFeed(batch, setBatch, () => setLost(true));

  // Reload the list on first render and whenever the shown batch starts,
  // finishes, or is resumed.
  const batchId = batch ? batch.batch_id : null;
  const status = batch ? batch.status : null;
  useEffect(() => {
    refreshBatches();
  }, [batchId, status, refreshBatches]);

  return (
    <main>
      <header>
        <h1>Hospital Bulk Upload</h1>
        <p className="lede">
          Upload a CSV of up to 20 hospitals. They are created in the Hospital Directory as one
          batch and activated together once every row succeeds.
        </p>
      </header>

      <UploadCard busy={status === "processing"} onStarted={show} />
      {batch && <BatchPanel batch={batch} lost={lost} onResumed={show} />}
      <BatchList
        batches={batches}
        selectedId={batchId}
        onSelect={openBatch}
        onRefresh={refreshBatches}
        error={listError}
      />

      <footer>
        <a href="/docs">API documentation</a>
      </footer>
    </main>
  );
}
