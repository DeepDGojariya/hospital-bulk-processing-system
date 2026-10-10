import { render, screen, within } from "@testing-library/react";

import ResultsTable from "./ResultsTable";

const hospitals = [
  { row: 1, hospital_id: 101, name: "General Hospital", status: "created", error: null },
  { row: 2, hospital_id: null, name: "<b>Bold & Sons</b>", status: "pending", error: null },
  { row: 3, hospital_id: null, name: "Riverside Clinic", status: "failed", error: "returned 500" },
];

const rowFor = (name) => screen.getByText(name).closest("tr");

test("values from the CSV are shown as text, never as markup", () => {
  const { container } = render(<ResultsTable hospitals={hospitals} processing={false} />);

  expect(screen.getByText("<b>Bold & Sons</b>")).toBeInTheDocument();
  expect(container.querySelector("b")).toBeNull();
});

test("a row without a result is labelled as being created while the batch runs", () => {
  render(<ResultsTable hospitals={hospitals} processing />);

  expect(within(rowFor("<b>Bold & Sons</b>")).getByText("Creating...")).toBeInTheDocument();
  expect(within(rowFor("General Hospital")).getByText("Created")).toBeInTheDocument();
});

test("a pending row in a finished batch is labelled pending", () => {
  render(<ResultsTable hospitals={hospitals} processing={false} />);

  expect(within(rowFor("<b>Bold & Sons</b>")).getByText("Pending")).toBeInTheDocument();
});

test("failed rows show their error and a dash for the missing ID", () => {
  render(<ResultsTable hospitals={hospitals} processing={false} />);

  const row = within(rowFor("Riverside Clinic"));
  expect(row.getByText("Failed")).toBeInTheDocument();
  expect(row.getByText("returned 500")).toBeInTheDocument();
  expect(row.getByText("-")).toBeInTheDocument();
});
