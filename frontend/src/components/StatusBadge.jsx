export default function StatusBadge({ kind, children }) {
  return <span className={`badge ${kind}`}>{children}</span>;
}
