import { formatStarted, shortId } from "../format";
import StatusBadge from "./StatusBadge";

export default function BatchList({ batches, selectedId, onSelect, onRefresh, error }) {
  return (
    <section className="card" aria-labelledby="list-heading">
      <div className="card-head">
        <h2 id="list-heading">Recent batches</h2>
        <button type="button" className="secondary small" onClick={onRefresh}>
          Refresh
        </button>
      </div>
      {error && <p className="message error">{error}</p>}
      {batches.length === 0 ? (
        <p className="hint">
          No batches yet. Batches processed since the service last started appear here.
        </p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th scope="col">Started</th>
                <th scope="col">Batch</th>
                <th scope="col">Status</th>
                <th scope="col">Created</th>
                <th scope="col">Failed</th>
                <th scope="col">Time</th>
              </tr>
            </thead>
            <tbody>
              {batches.map((batch) => {
                const selected = batch.batch_id === selectedId;
                return (
                  <tr
                    key={batch.batch_id}
                    className={selected ? "selected" : undefined}
                    aria-current={selected ? "true" : undefined}
                  >
                    <td>{formatStarted(batch.created_at)}</td>
                    <td>
                      <button
                        type="button"
                        className="link"
                        title={`View batch ${batch.batch_id}`}
                        onClick={() => onSelect(batch.batch_id)}
                      >
                        <code>{shortId(batch.batch_id)}</code>
                      </button>
                    </td>
                    <td>
                      <StatusBadge kind={batch.status}>{batch.status}</StatusBadge>
                    </td>
                    <td>
                      {batch.processed_hospitals} / {batch.total_hospitals}
                    </td>
                    <td>{batch.failed_hospitals}</td>
                    <td>{batch.processing_time_seconds.toFixed(1)} s</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
