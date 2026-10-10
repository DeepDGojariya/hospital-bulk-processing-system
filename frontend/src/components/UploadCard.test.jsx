import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import UploadCard from "./UploadCard";

const csv = () => new File(["name,address\n,1 Main St\n"], "hospitals.csv", { type: "text/csv" });

function respondWith(status, body) {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => vi.unstubAllGlobals());

test("buttons stay disabled until a file is chosen", async () => {
  render(<UploadCard busy={false} onStarted={() => {}} />);

  expect(screen.getByRole("button", { name: "Validate" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Upload and process" })).toBeDisabled();

  await userEvent.upload(screen.getByLabelText("CSV file"), csv());

  expect(screen.getByRole("button", { name: "Validate" })).toBeEnabled();
});

test("validation errors are listed by row and field", async () => {
  const fetchMock = respondWith(200, {
    valid: false,
    total_rows: 1,
    errors: [{ row: 1, field: "name", message: "name is required" }],
  });
  render(<UploadCard busy={false} onStarted={() => {}} />);
  await userEvent.upload(screen.getByLabelText("CSV file"), csv());

  await userEvent.click(screen.getByRole("button", { name: "Validate" }));

  expect(await screen.findByText("Found 1 problem. Nothing was uploaded.")).toBeInTheDocument();
  expect(screen.getByText("Row 1 (name): name is required")).toBeInTheDocument();
  expect(fetchMock.mock.calls[0][0]).toBe("/hospitals/bulk/validate");
});

test("a valid file is reported as ready", async () => {
  respondWith(200, { valid: true, total_rows: 3, errors: [] });
  render(<UploadCard busy={false} onStarted={() => {}} />);
  await userEvent.upload(screen.getByLabelText("CSV file"), csv());

  await userEvent.click(screen.getByRole("button", { name: "Validate" }));

  expect(await screen.findByText("Valid: 3 hospitals ready to upload.")).toBeInTheDocument();
});

test("an accepted upload hands the new batch to the page", async () => {
  const accepted = { batch_id: "abc", status: "processing", hospitals: [] };
  const fetchMock = respondWith(202, accepted);
  const onStarted = vi.fn();
  render(<UploadCard busy={false} onStarted={onStarted} />);
  await userEvent.upload(screen.getByLabelText("CSV file"), csv());

  await userEvent.click(screen.getByRole("button", { name: "Upload and process" }));

  await vi.waitFor(() => expect(onStarted).toHaveBeenCalledWith(accepted));
  expect(fetchMock.mock.calls[0][0]).toBe("/hospitals/bulk?mode=async");
});

test("a rejected upload shows the server's errors and starts nothing", async () => {
  respondWith(422, {
    detail: "CSV validation failed",
    errors: [{ row: null, field: null, message: "CSV has 21 rows; the maximum is 20" }],
  });
  const onStarted = vi.fn();
  render(<UploadCard busy={false} onStarted={onStarted} />);
  await userEvent.upload(screen.getByLabelText("CSV file"), csv());

  await userEvent.click(screen.getByRole("button", { name: "Upload and process" }));

  expect(await screen.findByText("CSV validation failed")).toBeInTheDocument();
  expect(screen.getByText("File: CSV has 21 rows; the maximum is 20")).toBeInTheDocument();
  expect(onStarted).not.toHaveBeenCalled();
});

test("uploads are blocked while a batch is processing", async () => {
  render(<UploadCard busy onStarted={() => {}} />);
  await userEvent.upload(screen.getByLabelText("CSV file"), csv());

  expect(screen.getByRole("button", { name: "Upload and process" })).toBeDisabled();
});

test("a network failure is explained", async () => {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
  render(<UploadCard busy={false} onStarted={() => {}} />);
  await userEvent.upload(screen.getByLabelText("CSV file"), csv());

  await userEvent.click(screen.getByRole("button", { name: "Validate" }));

  expect(await screen.findByText(/Could not reach the server/)).toBeInTheDocument();
});
