export default function ProgressBar({ done, total, busy }) {
  return (
    <div
      className={busy ? "bar busy" : "bar"}
      role="progressbar"
      aria-label="Rows processed"
      aria-valuemin={0}
      aria-valuemax={total}
      aria-valuenow={done}
    >
      <div className="bar-fill" style={{ width: `${(100 * done) / total}%` }} />
    </div>
  );
}
