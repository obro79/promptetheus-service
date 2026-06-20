import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const VIEWPORTS = [
  { name: "desktop-wide", width: 1920, height: 1080 },
  { name: "desktop", width: 1440, height: 900 },
  { name: "laptop", width: 1280, height: 800 },
  { name: "tablet", width: 1024, height: 768 },
  { name: "mobile", width: 390, height: 844 },
] as const;

test("global observability styles are loaded", async ({ page }) => {
  await page.goto("/incidents");
  const styles = await page.evaluate(() => ({
    background: getComputedStyle(document.body).backgroundColor,
    color: getComputedStyle(document.body).color,
    fontFamily: getComputedStyle(document.body).fontFamily,
    styleSheets: document.styleSheets.length,
  }));

  expect(styles.background).toBe("rgb(12, 13, 18)");
  expect(styles.color).toBe("rgb(242, 240, 245)");
  expect(styles.fontFamily).toContain("GeistSans");
  expect(styles.styleSheets).toBeGreaterThan(0);
});

test("light mode can be enabled and persists across reloads", async ({ page }) => {
  await page.goto("/incidents");

  await page.getByRole("button", { name: "Switch to light mode" }).click();
  await expect(page.locator("html")).toHaveClass(/light/);
  await expect(page.getByRole("button", { name: "Switch to dark mode" })).toBeVisible();
  await expect
    .poll(() => page.evaluate(() => getComputedStyle(document.documentElement).colorScheme))
    .toBe("light");
  await expect
    .poll(() =>
      page.evaluate(() =>
        getComputedStyle(document.querySelector('aside a[href="/sessions"]')!).color,
      ),
    )
    .toBe("rgb(94, 97, 110)");
  const accessibility = await new AxeBuilder({ page }).analyze();
  expect(
    accessibility.violations.filter((violation) =>
      ["serious", "critical"].includes(violation.impact ?? ""),
    ),
  ).toEqual([]);
  await page.screenshot({ path: "test-results/light-mode.png", fullPage: true });

  await page.reload();

  await expect(page.locator("html")).toHaveClass(/light/);
  await expect(page.getByRole("button", { name: "Switch to dark mode" })).toBeVisible();

  await page.getByRole("button", { name: "Switch to dark mode" }).click();
  await expect(page.locator("html")).toHaveClass(/dark/);
  await expect(page.locator("html")).not.toHaveClass(/light/);
  await expect(page.getByRole("button", { name: "Switch to light mode" })).toBeVisible();
  const darkAccessibility = await new AxeBuilder({ page }).analyze();
  expect(
    darkAccessibility.violations.filter((violation) =>
      ["serious", "critical"].includes(violation.impact ?? ""),
    ),
  ).toEqual([]);
});

for (const viewport of VIEWPORTS) {
  test(`voice replay remains operable at ${viewport.name}`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await page.goto("/demo");

    await expect(page.getByRole("heading", { name: /refund voice agent ignores correction/i })).toBeVisible();
    await expect(page.getByRole("region", { name: "Synchronized forensic timeline" })).toBeVisible();
    await expect(page.getByRole("region", { name: "Incident case summary" })).toBeVisible();

    const dimensions = await page.evaluate(() => ({ scrollWidth: document.body.scrollWidth, innerWidth: window.innerWidth }));
    expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.innerWidth);
    await page.screenshot({ path: `test-results/${viewport.name}.png`, fullPage: true });
  });
}

test("voice replay has no serious automated accessibility violations", async ({ page }) => {
  await page.goto("/demo");
  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations.filter((violation) => ["serious", "critical"].includes(violation.impact ?? ""))).toEqual([]);
});

for (const viewport of [
  { name: "desktop", width: 1440, height: 900 },
  { name: "mobile", width: 390, height: 844 },
]) {
  test(`failure inbox stays dense and operable at ${viewport.name}`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await page.goto("/incidents");

    await expect(page.getByRole("heading", { name: "Incidents requiring judgment" })).toBeVisible();
    await expect(page.getByRole("list", { name: "Failure inbox" })).toBeVisible();
    await expect(page.getByRole("combobox", { name: "Filter by status" })).toBeVisible();

    const dimensions = await page.evaluate(() => ({ scrollWidth: document.body.scrollWidth, innerWidth: window.innerWidth }));
    expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.innerWidth);
  });
}

for (const surface of [
  { name: "sessions", path: "/sessions", heading: "Sessions" },
  { name: "agents", path: "/agents", heading: "Agents" },
  { name: "docs", path: "/docs", heading: "Promptetheus API" },
  { name: "settings", path: "/settings/projects", heading: "Project settings" },
]) {
  test(`${surface.name} uses the shared product surface`, async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(surface.path);
    await expect(page.getByRole("heading", { name: surface.heading, exact: true })).toBeVisible();
    const dimensions = await page.evaluate(() => ({
      scrollWidth: document.body.scrollWidth,
      innerWidth: window.innerWidth,
    }));
    expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.innerWidth);
    await page.screenshot({ path: `test-results/surface-${surface.name}.png`, fullPage: true });
  });
}
