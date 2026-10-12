import { expect, test } from "@playwright/test";
// Diagnostic (WAKE=1, local stack): backend is stopped when the page loads and started ~20 s later by the caller.
test.skip(!process.env.WAKE, "diagnostic");
test("app shows waking banner and recovers when the backend comes back", async ({ page }, info) => {
  test.skip(info.project.name !== "desktop");
  test.setTimeout(180_000);
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.goto("/");
  await expect(page.getByTestId("waking-banner")).toBeVisible({ timeout: 15_000 });
  console.log("BANNER visible while backend down");
  await expect(page.getByTestId("waking-banner")).toBeHidden({ timeout: 150_000 });
  console.log("BANNER hidden after backend returned");
  await expect(page.getByText("Live verification isn't configured")).toHaveCount(0); // capabilities loaded (keys present locally)
  const text = `Recovery test message ${Date.now()}`;
  await page.getByLabel("Message").fill(text);
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("message").filter({ hasText: text })).toBeVisible();
  console.log("MESSAGE sent after recovery; page errors:", JSON.stringify(errors));
});
