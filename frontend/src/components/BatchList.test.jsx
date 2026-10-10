import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import BatchList from "./BatchList";

const batches = [
  {
    batch_id: "22222222-0000-0000-0000-000000000000",
    status: "failed",
    created_at: "2026-10-10T12:05:00Z",
    total_hospitals: 5,
    processed_hospitals: 4,
    failed_hospitals: 1,
    processing_time_seconds: 6.2,
    batch_activated: false,
  },
  {
    batch_id: "11111111-0000-0000-0000-000000000000",
    status: "completed",
    created_at: "2026-10-10T12:00:00Z",
    total_hospitals: 20,
    processed_hospitals: 20,
    failed_hospitals: 0,
    processing_time_seconds: 7.0,
    batch_activated: true,
  },
];

const noop = () => {};

test("lists batches in the order given, with their totals", () => {
  render(<BatchList batches={batches} selectedId={null} onSelect={noop} onRefresh={noop} error="" />);

  const rows = screen.getAllByRole("row").slice(1);
  expect(rows).toHaveLength(2);
  expect(rows[0]).toHaveTextContent("22222222");
  expect(rows[0]).toHaveTextContent("failed");
  expect(rows[0]).toHaveTextContent("4 / 5");
  expect(rows[1]).toHaveTextContent("11111111");
  expect(rows[1]).toHaveTextContent("20 / 20");
});

test("choosing a batch reports its full ID", async () => {
  const onSelect = vi.fn();
  render(<BatchList batches={batches} selectedId={null} onSelect={onSelect} onRefresh={noop} error="" />);

  await userEvent.click(screen.getByRole("button", { name: /11111111/ }));

  expect(onSelect).toHaveBeenCalledWith("11111111-0000-0000-0000-000000000000");
});

test("the batch being viewed is marked", () => {
  render(
    <BatchList batches={batches} selectedId={batches[1].batch_id} onSelect={noop} onRefresh={noop} error="" />,
  );

  expect(screen.getByRole("button", { name: /11111111/ }).closest("tr")).toHaveAttribute(
    "aria-current",
    "true",
  );
});

test("an empty list explains where batches come from", () => {
  render(<BatchList batches={[]} selectedId={null} onSelect={noop} onRefresh={noop} error="" />);

  expect(screen.getByText(/No batches yet/)).toBeInTheDocument();
  expect(screen.queryByRole("table")).toBeNull();
});

test("refresh asks for the list again", async () => {
  const onRefresh = vi.fn();
  render(<BatchList batches={batches} selectedId={null} onSelect={noop} onRefresh={onRefresh} error="" />);

  await userEvent.click(screen.getByRole("button", { name: "Refresh" }));

  expect(onRefresh).toHaveBeenCalledTimes(1);
});
