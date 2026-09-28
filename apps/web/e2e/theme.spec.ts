import { expect, test, type Page } from "@playwright/test";
import { csrfCookie, mockSockets, REP_CSRF, RUN } from "./liveMock";

// The Light / Dark / System toggle (S1-SYS-76) on the replay library, served by the real API.
const PAGE_BG = { light: "rgb(244, 242, 239)", dark: "rgb(38, 36, 34)" };

const toggle = (page: Page) => page.getByRole("radiogroup", { name: "Theme" });
const html = (page: Page) => page.locator("html");
const bodyBg = (page: Page) => page.locator("body").evaluate((el) => getComputedStyle(el).backgroundColor);

test.use({ colorScheme: "light" });

test("the toggle switches the theme, and the choice survives a reload", async ({ page }) => {
  await page.goto("/");
  await expect(toggle(page).getByRole("radio", { name: "System" })).toHaveAttribute("aria-checked", "true");
  await expect(html(page)).toHaveAttribute("data-theme", "light");
  expect(await bodyBg(page)).toBe(PAGE_BG.light);

  await toggle(page).getByRole("radio", { name: "Dark" }).click();
  await expect(html(page)).toHaveAttribute("data-theme", "dark");
  await expect(toggle(page).getByRole("radio", { name: "Dark" })).toHaveAttribute("aria-checked", "true");
  expect(await bodyBg(page)).toBe(PAGE_BG.dark);
  expect(await page.evaluate(() => localStorage.getItem("proxyloop.theme"))).toBe("dark");

  await page.reload();
  await expect(html(page)).toHaveAttribute("data-theme", "dark");
  await expect(toggle(page).getByRole("radio", { name: "Dark" })).toHaveAttribute("aria-checked", "true");
  expect(await bodyBg(page)).toBe(PAGE_BG.dark);
});

test("the stored theme is on <html> before the app's script runs", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("proxyloop.theme", "dark"));
  await page.route("**/src/main.tsx", (r) => r.abort());
  await page.route("**/assets/*.js", (r) => r.abort()); // no app: only index.html's inline script
  await page.goto("/");
  await expect(html(page)).toHaveAttribute("data-theme", "dark");
});

test("System follows the OS scheme; Light and Dark ignore it", async ({ page }) => {
  await page.goto("/");
  await expect(html(page)).toHaveAttribute("data-theme", "light");
  await page.emulateMedia({ colorScheme: "dark" });
  await expect(html(page)).toHaveAttribute("data-theme", "dark");

  await toggle(page).getByRole("radio", { name: "Light" }).click();
  await expect(html(page)).toHaveAttribute("data-theme", "light");
  await page.emulateMedia({ colorScheme: "light" });
  await page.emulateMedia({ colorScheme: "dark" });
  await expect(html(page)).toHaveAttribute("data-theme", "light");

  await toggle(page).getByRole("radio", { name: "System" }).click();
  await expect(html(page)).toHaveAttribute("data-theme", "dark");
  await page.emulateMedia({ colorScheme: "light" });
  await expect(html(page)).toHaveAttribute("data-theme", "light");
});

test("arrow keys move the choice; one tab stop", async ({ page }) => {
  await page.goto("/");
  const system = toggle(page).getByRole("radio", { name: "System" });
  await system.focus();
  await page.keyboard.press("ArrowLeft");
  await expect(toggle(page).getByRole("radio", { name: "Dark" })).toBeFocused();
  await expect(html(page)).toHaveAttribute("data-theme", "dark");
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("ArrowRight");
  await expect(toggle(page).getByRole("radio", { name: "Light" })).toBeFocused();
  await expect(html(page)).toHaveAttribute("data-theme", "light");
  await expect(toggle(page).locator('[tabindex="0"]')).toHaveCount(1);
});

test("with storage that throws, the page renders on the OS scheme and the toggle still works", async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(window, "localStorage", {
      get() {
        throw new DOMException("The operation is insecure.", "SecurityError");
      },
    });
  });
  await page.emulateMedia({ colorScheme: "dark" });
  await page.goto("/");
  await expect(page.getByRole("list", { name: "Recorded runs" })).toBeVisible();
  await expect(html(page)).toHaveAttribute("data-theme", "dark");
  await toggle(page).getByRole("radio", { name: "Light" }).click();
  await expect(html(page)).toHaveAttribute("data-theme", "light");
  expect(await bodyBg(page)).toBe(PAGE_BG.light);
});

test("the Rep page, which has no toggle, follows the OS while on system and keeps a stored choice", async ({ page, baseURL }) => {
  await csrfCookie(page, baseURL, "pl_rep_csrf", REP_CSRF);
  await mockSockets(page);
  await page.goto(`/?rep=${RUN}`);
  await expect(page.getByRole("textbox", { name: "Say to the agent" })).toBeVisible();
  await expect(toggle(page)).toHaveCount(0);
  await expect(html(page)).toHaveAttribute("data-theme", "light");
  await page.emulateMedia({ colorScheme: "dark" });
  await expect(html(page)).toHaveAttribute("data-theme", "dark");
  expect(await bodyBg(page)).toBe(PAGE_BG.dark);
  await page.emulateMedia({ colorScheme: "light" });
  await expect(html(page)).toHaveAttribute("data-theme", "light");

  await page.evaluate(() => localStorage.setItem("proxyloop.theme", "dark"));
  await page.reload();
  await expect(page.getByRole("textbox", { name: "Say to the agent" })).toBeVisible();
  await expect(html(page)).toHaveAttribute("data-theme", "dark");
  await page.emulateMedia({ colorScheme: "light" });
  await expect(html(page)).toHaveAttribute("data-theme", "dark");
});
