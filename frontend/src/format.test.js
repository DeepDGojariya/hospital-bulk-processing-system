import { plural, shortId, summaryFor } from "./format";

const batch = (overrides) => ({
  status: "completed",
  total_hospitals: 5,
  processed_hospitals: 5,
  failed_hospitals: 0,
  processing_time_seconds: 7.123,
  activation_error: null,
  ...overrides,
});

test("plural adds an s except for one", () => {
  expect(plural(1, "row")).toBe("1 row");
  expect(plural(2, "row")).toBe("2 rows");
  expect(plural(0, "row")).toBe("0 rows");
});

test("shortId keeps the first block of the UUID", () => {
  expect(shortId("730996b5-b586-4102-a1cd-a77f902c4e37")).toBe("730996b5");
});

test("a completed batch reports the count and time", () => {
  expect(summaryFor(batch())).toEqual({
    text: "5 hospitals created and activated in 7.1 s.",
    kind: "ok",
  });
});

test("a batch with failed rows says it was not activated", () => {
  const summary = summaryFor(batch({ status: "failed", processed_hospitals: 4, failed_hospitals: 1 }));

  expect(summary.kind).toBe("error");
  expect(summary.text).toMatch(/^1 row failed, so the batch was not activated/);
});

test("an activation failure is reported as such", () => {
  const summary = summaryFor(batch({ status: "failed", activation_error: "returned 500" }));

  expect(summary.text).toBe("All hospitals were created, but activation failed: returned 500");
});

test("a processing batch explains why nothing has arrived yet", () => {
  const summary = summaryFor(batch({ status: "processing", processed_hospitals: 0 }));

  expect(summary.kind).toBe("");
  expect(summary.text).toMatch(/results usually arrive together/);
});
