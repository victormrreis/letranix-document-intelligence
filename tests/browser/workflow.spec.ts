import { test, expect, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import path from "node:path";

const shots = process.env.LETRANIX_SCREENSHOTS === "1";
const fixture = (name: string) => path.resolve("demo/synthetic", name);

async function shot(page: Page, name: string) {
  if (shots) await page.screenshot({ path: `docs/assets/${name}.png` });
}

async function open(page: Page, name: string) {
  await page.goto("/#/documents");
  await page.getByRole("link", { name: new RegExp(name) }).click();
  await expect(page.getByRole("heading", { name })).toBeVisible();
}

test.describe.configure({ mode: "serial" });

test("import, OCR, correct, approve, history, export and deliver over HTTP", async ({
  page,
}) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();

  // Route deliveries to the fictitious records API started with the service.
  await page.goto("/#/settings");
  await page.locator("#integration\\.adapter").selectOption("http-demo");
  await page
    .locator("#integration\\.endpoint")
    .fill("http://127.0.0.1:8807/records");
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByText("setting(s) saved")).toBeVisible();

  // Import documents that were never processed in this workspace.
  await page.goto("/#/documents");
  await page
    .locator("input[type=file]")
    .setInputFiles([
      fixture("inspection-report.png"),
      fixture("service-order.txt"),
      fixture("invoice.pdf"),
      fixture("scanned-request.pdf"),
    ]);
  await expect(page.getByText("4 document(s) imported")).toBeVisible();
  await shot(page, "02-import");

  // Real OCR runs in the background; the row updates when extraction finishes.
  const row = page.getByRole("row", { name: /inspection-report\.png/ });
  await expect(row.getByText("Needs review")).toBeVisible({ timeout: 120000 });
  await expect(
    page
      .getByRole("row", { name: /scanned-request\.pdf/ })
      .getByText("Needs review"),
  ).toBeVisible({
    timeout: 120000,
  });
  await shot(page, "03-documents");

  await open(page, "inspection-report.png");
  await expect(page.locator("#field-report_id")).toHaveValue("IR-3310");
  await expect(page.locator("#field-result")).toHaveValue("pass");
  await expect(page.getByText(/deskew/)).toBeVisible();
  await page.locator("#field-site").focus();
  await shot(page, "04-ocr-review");

  // Correct one field: the draft survives a reload before the decision.
  await page
    .locator("#field-notes")
    .fill("Gauge within range; verified on the synthetic image");
  await page.reload();
  await expect(page.getByText("Restored unsaved edits")).toBeVisible();
  await expect(page.locator("#field-notes")).toHaveValue(
    "Gauge within range; verified on the synthetic image",
  );
  await page
    .getByLabel("Decision note")
    .fill("Compared each field with the page image");
  await page.getByRole("button", { name: "Approve", exact: true }).click();
  await expect(page.getByText(/Review approved/)).toBeVisible();
  await expect(page.getByText(/Approved by/)).toBeVisible();

  // History shows the decision with per-field provenance.
  await page.getByRole("tab", { name: /History/ }).click();
  await expect(page.getByText("notes corrected")).toBeVisible();
  await expect(page.getByText("review.approved")).toBeVisible();
  await shot(page, "06-history");

  // Explicit authorisation, then delivery through the outbox to the HTTP destination.
  await page.getByRole("tab", { name: "Review" }).click();
  await page.getByRole("button", { name: /Send to destination/ }).click();
  await expect(page.getByRole("dialog")).toContainText(
    "http://127.0.0.1:8807/records",
  );
  await page.getByRole("button", { name: "Authorise and send" }).click();
  await expect(
    page.getByRole("button", { name: "Destination: delivered" }),
  ).toBeVisible({
    timeout: 20000,
  });

  // Verify at the destination itself, through the UI and directly.
  await page.goto("/#/integrations");
  await expect(page.getByRole("cell", { name: "delivered" })).toBeVisible();
  await expect(page.getByText(/notes: Gauge within range/)).toBeVisible();
  await shot(page, "07-integrations");
  const direct = await page.request.get("http://127.0.0.1:8807/records");
  const records = await direct.json();
  expect(records).toHaveLength(1);
  expect(records[0].fields.report_id).toBe("IR-3310");

  // Export approved records.
  await page.goto("/#/documents");
  const [csv] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("button", { name: "Approved CSV" }).click(),
  ]);
  const body = readFileSync(await csv.path(), "utf-8");
  expect(body).toContain("IR-3310");
  expect(body).toContain("Gauge within range");

  // Persistence across a full page reload (server restart is covered by pytest).
  await page.reload();
  await open(page, "inspection-report.png");
  await expect(page.locator("#field-notes")).toHaveValue(
    "Gauge within range; verified on the synthetic image",
  );
});

test("multi-page scan, table review, search, audit and responsive layout", async ({
  page,
}) => {
  await open(page, "scanned-request.pdf");
  await expect(page.getByText("Page 1 / 2")).toBeVisible();
  await expect(page.locator("#field-protocol")).toHaveValue("AR-5521");
  await page.getByRole("tab", { name: "Recognised text" }).click();
  await expect(page.getByRole("heading", { name: /Page 2 ocr/ })).toBeVisible();

  await open(page, "invoice.pdf");
  await expect(page.locator("#field-total")).toHaveValue("254.00");
  await expect(page.getByLabel("Description row 3")).toHaveValue(
    "Document boxes",
  );
  await expect(page.getByAltText(/Page 1 of invoice/)).toBeVisible();
  await page
    .getByRole("heading", { name: /Line items/ })
    .scrollIntoViewIfNeeded();
  await shot(page, "05-fields-table");

  // Flagging a field blocks approval until it is cleared.
  await page
    .getByRole("button", { name: "Flag inconsistency" })
    .first()
    .click();
  await page
    .getByLabel(/Inconsistency note/)
    .fill("Number differs from the stamp");
  await page.getByLabel("Decision note").fill("Checking the flagged number");
  await page.getByRole("button", { name: "Approve", exact: true }).click();
  await expect(
    page.getByText("Resolve or clear flagged inconsistencies"),
  ).toBeVisible();

  await page.goto("/#/documents");
  await page.getByLabel("Search documents").fill("Records Office");
  await expect(
    page.getByRole("row", { name: /scanned-request\.pdf/ }),
  ).toBeVisible();
  await expect(page.getByText("1 document")).toBeVisible();
  await page.getByLabel("Search documents").fill("no-such-synthetic-term");
  await expect(page.getByText("No documents in this view")).toBeVisible();

  await page.goto("/#/audit");
  await expect(
    page.getByRole("cell", { name: "integration.delivered" }),
  ).toBeVisible();
  await shot(page, "08-audit");

  await page.goto("/#/overview");
  await expect(page.getByText("Active documents")).toBeVisible();
  await shot(page, "01-overview");
  for (const page_ of ["templates", "learning", "settings"]) {
    await page.goto("/#/" + page_);
    await expect(page.locator("h1")).toBeVisible();
    if (page_ === "learning") {
      // Runs the real train/validation/test evaluation in a temporary workspace.
      await page.getByRole("button", { name: "Run evaluation" }).click();
      await expect(page.getByText("Field accuracy")).toBeVisible({
        timeout: 120000,
      });
    }
    await shot(
      page,
      {
        templates: "10-types",
        learning: "09-learning",
        settings: "11-settings",
      }[page_]!,
    );
  }

  for (const [width, height] of [
    [1920, 1080],
    [1366, 768],
    [390, 844],
  ] as const) {
    await page.setViewportSize({ width, height });
    for (const route of ["documents", "settings"]) {
      await page.goto("/#/" + route);
      await expect(page.locator("h1")).toBeVisible();
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= window.innerWidth + 1,
        ),
      ).toBeTruthy();
    }
  }
  await shot(page, "12-mobile");
});

test("invalid upload is rejected with a clear message", async ({ page }) => {
  await page.goto("/#/documents");
  await page.locator("input[type=file]").setInputFiles({
    name: "broken.pdf",
    mimeType: "application/pdf",
    buffer: Buffer.from("%PDF-1.4 truncated"),
  });
  await expect(page.getByText(/broken\.pdf: The PDF is damaged/)).toBeVisible();
});
