import { test, expect } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { randomUUID } from "node:crypto";

const directory = path.dirname(fileURLToPath(import.meta.url));
const data = JSON.parse(fs.readFileSync(path.join(directory, "../../tests/fixtures/acceptance.json"), "utf8"));
const backend = "http://127.0.0.1:8001";

function account() {
  const identifier = randomUUID().replaceAll("-", "");
  return { ...data.account, email: `${identifier}@example.com`, employee_id: `ACC-${identifier.slice(0, 12)}` };
}

async function createAccount(page, user) {
  const response = await page.request.post(`${backend}/api/auth/signup`, { data: user });
  expect(response.ok(), await response.text()).toBeTruthy();
}

async function login(page, user) {
  await page.goto("/login");
  await page.getByLabel("EMAIL", { exact: true }).fill(user.email);
  await page.getByLabel("PASSWORD", { exact: true }).fill(user.password);
  await page.getByRole("button", { name: "Sign In", exact: true }).click();
  await expect(page.getByRole("heading", { name: "How can I help you?", exact: true })).toBeVisible();
}

async function ask(page, question) {
  await page.getByRole("textbox", { name: "Ask the ACC assistant" }).fill(question);
  await page.getByRole("button", { name: "Send message" }).click();
}

async function capture(page, testInfo, name) {
  const filename = testInfo.outputPath(`${name}.png`);
  await page.screenshot({ path: filename, fullPage: true });
  await testInfo.attach(name, { path: filename, contentType: "image/png" });
}

test("UAT-01 registration, login, and logout through the browser", async ({ page }, testInfo) => {
  const user = account();
  await page.goto("/signup");
  for (const [label, value] of [["NAME", user.name], ["EMPLOYEE ID", user.employee_id], ["EMAIL", user.email], ["DEPARTMENT", user.department], ["PASSWORD", user.password]]) {
    await page.getByLabel(label, { exact: true }).fill(value);
  }
  await page.getByLabel("ROLE", { exact: true }).selectOption(user.role);
  await page.getByRole("button", { name: "Sign Up", exact: true }).click();
  await expect(page).toHaveURL(/\/login$/);
  await login(page, user);
  await capture(page, testInfo, "uat-01-dashboard");
  await page.getByRole("button", { name: "Log out", exact: true }).click();
  await page.getByRole("button", { name: "Log Out", exact: true }).click();
  await expect(page).toHaveURL(/\/login$/);
  expect((await page.request.get(`${backend}/api/auth/me`)).status()).toBe(401);
  await page.goto("/Dashboard");
  await expect(page).toHaveURL(/\/login$/);
});

test("UAT-02 supported answer, automatic title, and original cited document", async ({ page }, testInfo) => {
  const user = account();
  await createAccount(page, user);
  await login(page, user);
  await ask(page, data.questions.supported);
  await expect(page.locator(".chat-message.assistant")).toContainText(data.document.text);
  await expect(page.getByRole("heading", { name: data.title, exact: true })).toBeVisible();
  await page.getByRole("button", { name: "View 1 sources" }).click();
  await page.getByRole("button", { name: new RegExp(data.document.filename) }).click();
  await expect(page.locator(".source-document pre")).toHaveText(data.document.text);
  await expect(page.locator(".source-document mark")).toHaveText(data.document.text);
  await capture(page, testInfo, "uat-02-original-source");
});

test("UAT-03 missing information is stated explicitly", async ({ page }, testInfo) => {
  const user = account();
  await createAccount(page, user);
  await login(page, user);
  await ask(page, data.questions.missing);
  await expect(page.locator(".chat-message.assistant")).toContainText("I don't have information about that in the available documents.");
  await expect(page.getByRole("button", { name: /View .* sources/ })).toHaveCount(0);
  await capture(page, testInfo, "uat-03-missing-information");
});

test("UAT-04 failed query recovers without duplicate messages", async ({ page }, testInfo) => {
  const user = account();
  await createAccount(page, user);
  await login(page, user);
  await ask(page, data.questions.retry);
  await expect(page.getByRole("alert")).toContainText(/timed out/i);
  await expect(page.locator(".chat-message.user")).toHaveCount(0);
  await expect(page.getByRole("textbox", { name: "Ask the ACC assistant" })).toHaveValue(data.questions.retry);
  await page.getByRole("button", { name: "Retry", exact: true }).click();
  await expect(page.locator(".chat-message.assistant")).toContainText(data.document.text);
  await expect(page.locator(".chat-message.user")).toHaveCount(1);
  await expect(page.getByRole("alert")).toHaveCount(0);
  await page.reload();
  await expect(page.locator(".chat-message.user")).toHaveCount(1);
  await expect(page.locator(".chat-message.assistant")).toHaveCount(1);
  await capture(page, testInfo, "uat-04-retry");
});

test("UAT-05 folder conversations persist and input aligns with chat cards", async ({ page }, testInfo) => {
  const user = account();
  await createAccount(page, user);
  await login(page, user);
  await page.getByRole("button", { name: "New Folder", exact: true }).click();
  await page.getByLabel("Folder name", { exact: true }).fill("Acceptance folder");
  await page.getByRole("button", { name: "Create Folder", exact: true }).click();
  await page.getByText("Acceptance folder", { exact: true }).click();
  await expect(page.getByRole("heading", { name: "Acceptance folder", exact: true })).toBeVisible();
  await ask(page, data.questions.supported);
  await expect(page.locator(".chat-message.assistant")).toContainText(data.document.text);
  await page.locator(".sidebar-quick-folder").filter({ hasText: "Acceptance folder" }).click();
  const card = page.locator(".folder-chat-list .conversation-history-item").first();
  await expect(card).toBeVisible();
  const inputBounds = await page.locator(".folder-chat-prompt-area .prompt-box").boundingBox();
  const cardBounds = await card.boundingBox();
  expect(Math.abs(inputBounds.width - cardBounds.width)).toBeLessThanOrEqual(2);
  expect(Math.abs(inputBounds.x - cardBounds.x)).toBeLessThanOrEqual(2);
  await page.reload();
  await expect(page.locator(".folder-chat-list .conversation-history-item")).toHaveCount(1);
  await capture(page, testInfo, "uat-05-folder");
});

test("UAT-06 another account cannot view a private conversation", async ({ page, browser }, testInfo) => {
  const first = account();
  await createAccount(page, first);
  await login(page, first);
  await ask(page, data.questions.supported);
  await expect(page.locator(".chat-message.assistant")).toBeVisible();
  await expect(page).toHaveURL(/\/chat\/[a-f0-9]{24}$/);
  const privateUrl = page.url();
  const secondContext = await browser.newContext({ baseURL: "http://127.0.0.1:5181" });
  try {
    const secondPage = await secondContext.newPage();
    const second = account();
    await createAccount(secondPage, second);
    await login(secondPage, second);
    await secondPage.goto(privateUrl);
    await expect(secondPage.getByRole("alert")).toContainText("Conversation not found");
    await expect(secondPage.locator(".chat-message.assistant")).toHaveCount(0);
    await capture(secondPage, testInfo, "uat-06-account-isolation");
  } finally {
    await secondContext.close();
  }
});
