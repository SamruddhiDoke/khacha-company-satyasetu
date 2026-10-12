import { test } from "@playwright/test";
// Diagnostic only (not part of the suite): records API traffic for one Verify click.
test.skip(!process.env.DIAG, "diagnostic");
test("diag: network trace of one verification", async ({ page }, info) => {
  test.skip(info.project.name !== "desktop");
  test.setTimeout(400_000);
  const t0 = Date.now();
  const log = (s: string) => console.log(`${((Date.now() - t0) / 1000).toFixed(1)}s ${s}`);
  page.on("request", (r) => r.url().includes("/api/") && log(`REQ ${r.method()} ${new URL(r.url()).pathname}`));
  page.on("response", (r) => r.url().includes("/api/") && log(`RES ${r.status()} ${new URL(r.url()).pathname} ${r.headers()["content-type"] ?? ""}`));
  page.on("requestfailed", (r) => log(`FAILED ${new URL(r.url()).pathname} ${r.failure()?.errorText}`));
  page.on("console", (m) => (m.type() === "error" || m.type() === "warning") && log(`CONSOLE ${m.type()} ${m.text().slice(0, 200)}`));
  await page.goto("/");
  await page.getByLabel("Message").fill("The Howrah Bridge in Kolkata was opened to traffic in 1943.");
  await page.keyboard.press("Enter");
  const vreq = page.waitForResponse((r) => r.url().includes("/verifications") && r.request().method() === "POST");
  await page.getByTestId("verify-button").last().click();
  const job = await (await vreq).json();
  log(`JOB ${job.id}`);
  for (let i = 0; i < 34; i++) {
    await page.waitForTimeout(10_000);
    const state = await page.getByTestId("message").last().locator("[data-testid^=verify-]").first().getAttribute("data-testid").catch(() => "none");
    const d = await page.request.get(`/api/verifications/${job.id}`).then((r) => r.json());
    const last = d.events?.[d.events.length - 1];
    log(`UI state: ${state} | server: ${d.status} ${d.overall_verdict ?? ""} ${d.error_code ?? ""} | last event ${last?.stage}/${last?.status} ${last?.detail ?? ""}`);
    if (state === "verify-result" || state === "verify-failed") break;
  }
});
