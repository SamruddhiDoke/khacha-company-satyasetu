import { test } from "@playwright/test";
// Diagnostic only (not part of the suite): records API traffic for one Verify click.
test.skip(!process.env.DIAG, "diagnostic");
test("diag: network trace of one verification", async ({ page }, info) => {
  test.skip(info.project.name !== "desktop");
  test.setTimeout(150_000);
  const t0 = Date.now();
  const log = (s: string) => console.log(`${((Date.now() - t0) / 1000).toFixed(1)}s ${s}`);
  page.on("request", (r) => r.url().includes("/api/") && log(`REQ ${r.method()} ${new URL(r.url()).pathname}`));
  page.on("response", (r) => r.url().includes("/api/") && log(`RES ${r.status()} ${new URL(r.url()).pathname} ${r.headers()["content-type"] ?? ""}`));
  page.on("requestfailed", (r) => log(`FAILED ${new URL(r.url()).pathname} ${r.failure()?.errorText}`));
  page.on("console", (m) => (m.type() === "error" || m.type() === "warning") && log(`CONSOLE ${m.type()} ${m.text().slice(0, 200)}`));
  await page.goto("/");
  await page.getByLabel("Message").fill("The Howrah Bridge in Kolkata was opened to traffic in 1943.");
  await page.keyboard.press("Enter");
  await page.getByTestId("verify-button").last().click();
  for (let i = 0; i < 12; i++) {
    await page.waitForTimeout(10_000);
    const state = await page.getByTestId("message").last().locator("[data-testid^=verify-]").first().getAttribute("data-testid").catch(() => "none");
    log(`UI state: ${state}`);
    if (state === "verify-result" || state === "verify-failed") break;
  }
});
