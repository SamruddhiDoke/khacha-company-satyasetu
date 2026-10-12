import { expect, test } from "@playwright/test";
import { writeFileSync } from "node:fs";

// LIVE: real Gemini + Tavily through the real UI. Run only with LIVE=1 (consumes free quota).
test.skip(!process.env.LIVE, "set LIVE=1 to run against real providers");

test("live: one unseen claim through the real UI", async ({ page }, info) => {
  test.skip(info.project.name !== "desktop", "run once");
  test.setTimeout(240_000);
  const consoleErrors: string[] = [];
  page.on("console", (m) => m.type() === "error" && consoleErrors.push(m.text()));
  page.on("pageerror", (e) => consoleErrors.push(String(e)));
  const claim = process.env.CLAIM ?? "The Statue of Unity in Gujarat, which depicts Sardar Vallabhbhai Patel, is 182 metres tall.";
  await page.goto("/");
  await page.getByLabel("Message").fill(claim);
  await page.keyboard.press("Enter");
  const bubble = page.getByTestId("message").filter({ hasText: claim });
  await expect(bubble).toBeVisible();
  const req = page.waitForRequest((r) => r.url().includes("/verifications") && r.method() === "POST");
  await bubble.getByTestId("verify-button").click();
  const resp = (await (await req).response())!;
  const job = await resp.json();
  console.log("VERIFY POST", resp.status(), job.id ?? JSON.stringify(job));
  try {
    await expect(bubble.getByTestId("verify-result").or(bubble.getByTestId("verify-failed"))).toBeVisible({ timeout: 200_000 });
  } catch (e) {
    const d = job.id ? await page.request.get(`/api/verifications/${job.id}`).then((r) => r.json()) : null;
    const last = d?.events?.[d.events.length - 1];
    console.log("TIMEOUT DIAG server:", d?.status, d?.error_code, "last:", last?.stage, last?.status,
                "| toasts:", JSON.stringify(await page.locator("[role=alert],[role=status]").allInnerTexts()));
    throw e;
  }
  const detail = await page.request.get(`/api/verifications/${job.id}`).then((r) => r.json());
  writeFileSync("test-results/live-job.json", JSON.stringify(detail, null, 1));
  if (detail.status === "completed") {
    await bubble.getByTestId("verify-result").click();
    await expect(page.getByRole("complementary", { name: "Verification report" })).toBeVisible();
    await page.waitForTimeout(500);
  }
  await page.screenshot({ path: "test-results/screens/live-report.png", fullPage: false });
  console.log("JOB", job.id, detail.status, detail.overall_verdict, detail.error_code);
  console.log("CONSOLE_ERRORS", JSON.stringify(consoleErrors));
});
