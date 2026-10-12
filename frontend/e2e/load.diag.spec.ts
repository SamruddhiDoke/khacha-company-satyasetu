import { test } from "@playwright/test";
// Diagnostic only (DIAG=1): loads the app and records API traffic and visible errors. No fact-check is started.
test.skip(!process.env.DIAG, "diagnostic");
test("diag: page load traffic", async ({ page }, info) => {
  test.skip(info.project.name !== "desktop");
  test.setTimeout(200_000);
  const t0 = Date.now();
  const log = (s: string) => console.log(`${((Date.now() - t0) / 1000).toFixed(1)}s ${s}`);
  page.on("response", (r) => r.url().includes("/api/") && log(`RES ${r.status()} ${new URL(r.url()).pathname} ${r.headers()["content-type"] ?? ""}`));
  page.on("requestfailed", (r) => log(`FAILED ${new URL(r.url()).pathname} ${r.failure()?.errorText}`));
  page.on("console", (m) => m.type() === "error" && log(`CONSOLE ${m.text().slice(0, 160)}`));
  await page.goto("/");
  await page.waitForTimeout(8000);
  const toasts = await page.locator("[role=alert],[role=status]").allInnerTexts();
  log(`VISIBLE NOTICES ${JSON.stringify(toasts)}`);
});
