import { test, expect } from "@playwright/test";
import path from "node:path";

test("real synthetic workflow, review, explicit integration, persistence and responsive layout", async ({
  page,
}) => {
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Document intelligence." }),
  ).toBeVisible();
  await page
    .locator("input[type=file]")
    .setInputFiles(path.resolve("demo/synthetic/service-order.txt"));
  await page.getByRole("button", { name: /service-order.txt/ }).click();
  const process = page.getByRole("button", {
    name: "Process document",
    exact: true,
  });
  if (await process.isVisible()) await process.click();
  await expect(page.getByLabel("reference", { exact: true })).toHaveValue(
    "DEMO-001",
  );
  await page
    .getByLabel("description", { exact: true })
    .fill("Verified synthetic scanner inspection");
  await page
    .getByLabel("Decision reason")
    .fill("Compared every field with the synthetic source");
  await page
    .getByRole("button", { name: "Approve review", exact: true })
    .click();
  await expect(
    page.getByText("Review saved. No integration was executed."),
  ).toBeVisible();
  await page.getByRole("button", { name: "Preview local integration" }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await expect(
    page.getByRole("dialog").getByText("Verified synthetic scanner inspection"),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Authorize local integration" })
    .click();
  await expect(
    page.getByRole("button", { name: "Integrated locally" }),
  ).toBeDisabled();
  await page.reload();
  await page.getByRole("button", { name: /service-order.txt/ }).click();
  await expect(page.getByLabel("description", { exact: true })).toHaveValue(
    "Verified synthetic scanner inspection",
  );
  for (const [width, height, name] of [
    [1920, 1080, "desktop"],
    [1366, 768, "laptop"],
    [911, 512, "scaled-150"],
    [390, 844, "mobile"],
  ] as const) {
    await page.setViewportSize({ width, height });
    await expect(
      page.getByRole("button", { name: "Integrated locally" }),
    ).toBeAttached();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth + 1,
      ),
    ).toBeTruthy();
    await page.screenshot({
      path: `docs/screenshots/${name}.png`,
      fullPage: true,
    });
  }
  await page.getByRole("button", { name: /Audit trail/ }).click();
  await expect(
    page.getByText("integration.local-demo", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Source & review" }).click();
  await page
    .getByRole("button", { name: "Reprocess · requires a new review" })
    .click();
  await expect(page.getByLabel("description", { exact: true })).toBeEnabled();
  await page
    .getByLabel("Decision reason")
    .fill("Rechecked the second extraction version against source");
  await page
    .getByRole("button", { name: "Approve review", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Preview local integration" }),
  ).toBeEnabled();
  await page.getByRole("button", { name: "Preview local integration" }).click();
  await page
    .getByRole("button", { name: "Authorize local integration" })
    .click();
  await expect(
    page.getByRole("button", { name: "Integrated locally" }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "Close document" }).click();
  await page.getByLabel("Search documents").fill("service-order");
  await expect(
    page.getByRole("button", { name: /service-order.txt/ }),
  ).toBeVisible();
  await page.getByLabel("Search documents").fill("absent-synthetic-result");
  await expect(page.getByText("No documents in this view")).toBeVisible();
});

test("real image OCR with human confirmation and local integration", async ({
  page,
}) => {
  await page.goto("/");
  await page
    .locator("input[type=file]")
    .setInputFiles(path.resolve("demo/synthetic/operational-report.png"));
  await page.getByRole("button", { name: /operational-report.png/ }).click();
  await page
    .getByRole("button", { name: "Process document", exact: true })
    .click();
  await expect(page.getByLabel("reference", { exact: true })).toHaveValue(
    "DEMO-002",
    { timeout: 60000 },
  );
  await expect(page.getByAltText("Uploaded document source")).toBeVisible();
  await page.getByLabel("reference", { exact: true }).fill("DEMO-002");
  await page
    .getByLabel("organization", { exact: true })
    .fill("Example Works Lab");
  await page
    .getByLabel("category", { exact: true })
    .selectOption("operational-report");
  await page.getByLabel("date", { exact: true }).fill("2026-01-15");
  await page
    .getByLabel("description", { exact: true })
    .fill("Synthetic equipment inspection completed.");
  await page
    .getByLabel("Decision reason")
    .fill("Verified OCR fields against the generated image");
  await page
    .getByRole("button", { name: "Approve review", exact: true })
    .click();
  await page.getByRole("button", { name: "Preview local integration" }).click();
  await page
    .getByRole("button", { name: "Authorize local integration" })
    .click();
  await expect(
    page.getByRole("button", { name: "Integrated locally" }),
  ).toBeDisabled();
  await page.setViewportSize({ width: 1600, height: 1000 });
  await page.screenshot({
    path: "docs/screenshots/ocr-review.png",
    fullPage: true,
  });
});
