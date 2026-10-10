import { expect, test, type Page } from "@playwright/test";

// These run against the real stack. Messages are generated per run so they can't match any fixture.
const unique = () => `Claim ${Date.now()}-${Math.floor(Math.random() * 1e6)}: the municipal corporation of a town will give free bicycles to every resident aged over 70 from next Monday.`;

async function openApp(page: Page) {
  await page.goto("/");
  await expect(page.getByLabel("Message")).toBeVisible();
}

async function ensureChatVisible(page: Page) {
  // On mobile the chat is the main view already; the sidebar is a drawer.
  await expect(page.getByRole("region", { name: "Chat" })).toBeVisible();
}

test("AT-01/02: arbitrary text is sent, shown, and Verify sends that exact message to the backend", async ({ page }, info) => {
  await openApp(page);
  await ensureChatVisible(page);
  const text = unique();
  await page.getByLabel("Message").fill(text);
  await page.keyboard.press("Enter");

  const bubble = page.getByTestId("message").filter({ hasText: text });
  await expect(bubble).toBeVisible();
  const messageId = await bubble.getAttribute("data-message-id");
  expect(messageId).toBeTruthy();

  const reqPromise = page.waitForRequest((r) => r.url().includes("/verifications") && r.method() === "POST");
  await bubble.getByTestId("verify-button").click();
  const req = await reqPromise;
  expect(req.url()).toContain(`/api/messages/${messageId}/verifications`);
  expect(JSON.parse(req.postData() ?? "{}")).toMatchObject({ retry: false });
  const res = await req.response();
  const job = await res!.json();
  expect(job.message_id).toBe(messageId);

  // The job's input on the server is exactly the user's text.
  const detail = await page.request.get(`/api/verifications/${job.id}`).then((r) => r.json());
  expect(detail.input_text).toBe(text);

  // Whatever happens next must be a real terminal state: a verdict or an honest failure.
  await expect(bubble.getByTestId("verify-result").or(bubble.getByTestId("verify-failed"))).toBeVisible({ timeout: 45_000 });
  await page.screenshot({ path: `test-results/screens/after-verify-${info.project.name}.png`, fullPage: false });
});

test("Shift+Enter makes a newline; multi-line paste keeps formatting; second message can be sent while the first is checking", async ({ page }) => {
  await openApp(page);
  const box = page.getByLabel("Message");
  await box.click();
  await box.type("Line one");
  await page.keyboard.press("Shift+Enter");
  await box.type("Line two");
  await expect(box).toHaveValue("Line one\nLine two");
  await page.keyboard.press("Enter");
  const first = page.getByTestId("message").filter({ hasText: "Line two" }).last();
  await expect(first).toBeVisible();
  await first.getByTestId("verify-button").click();

  const second = unique();
  await box.fill(second);
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("message").filter({ hasText: second })).toBeVisible();
  // ordering: the second message is below the first
  const ids = await page.getByTestId("message").evaluateAll((els) => els.map((e) => e.textContent ?? ""));
  expect(ids.findIndex((t) => t.includes("Line two"))).toBeLessThan(ids.findIndex((t) => t.includes(second)));
});

test("AT-15: without provider keys the UI says so and never shows a verdict", async ({ page }) => {
  const caps = await page.request.get("/api/capabilities").then((r) => r.json());
  test.skip(caps.live_verification, "Live providers are configured in this environment");
  await openApp(page);
  await expect(page.getByText("Live verification isn't configured")).toBeVisible();
  await page.getByLabel("Message").fill("Share your OTP now or your bank account will be blocked by RBI today.");
  await page.keyboard.press("Enter");
  const bubble = page.getByTestId("message").last();
  await bubble.getByTestId("verify-button").click();
  await expect(bubble.getByTestId("verify-failed")).toContainText("API keys");
  await expect(bubble.getByTestId("verify-result")).toHaveCount(0);
  // The safety warnings still appear in the report.
  await bubble.getByRole("button", { name: "Details" }).click();
  await expect(page.getByText("Asks for an OTP, PIN or password")).toBeVisible();
});

test("AT-13: layout is usable and screenshots are captured", async ({ page }, info) => {
  await openApp(page);
  await page.screenshot({ path: `test-results/screens/home-${info.project.name}.png` });
  const width = page.viewportSize()!.width;
  // no horizontal scroll
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
  if (width < 768) {
    await page.getByLabel("Open conversations").click();
    await expect(page.getByRole("complementary", { name: "Conversations" })).toBeInViewport();
    await page.screenshot({ path: `test-results/screens/drawer-${info.project.name}.png` });
  } else {
    await expect(page.getByRole("complementary", { name: "Conversations" })).toBeVisible();
  }
});
