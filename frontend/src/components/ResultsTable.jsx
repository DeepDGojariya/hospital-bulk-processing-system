import { ROW_LABELS } from "../format";
import StatusBadge from "./StatusBadge";

// Names and errors come from the uploaded CSV and the upstream API. React
// renders them as text, so markup in a value is shown, not interpreted.
export default function ResultsTable({ hospitals, processing }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th scope="col">Row</th>
            <th scope="col">Name</th>
            <th scope="col">Status</th>
            <th scope="col">Hospital ID</th>
            <th scope="col">Error</th>
          </tr>
        </thead>
        <tbody>
          {hospitals.map((hospital) => {
            // While the batch runs, a row without a result yet is in flight.
            const inFlight = processing && hospital.status === "pending";
            return (
              <tr key={hospital.row}>
                <td>{hospital.row}</td>
                <td className="name">{hospital.name}</td>
                <td>
                  <StatusBadge kind={inFlight ? "working" : hospital.status}>
                    {inFlight ? "Creating..." : ROW_LABELS[hospital.status] || hospital.status}
                  </StatusBadge>
                </td>
                <td>{hospital.hospital_id === null ? "-" : hospital.hospital_id}</td>
                <td className="error-text">{hospital.error || ""}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
