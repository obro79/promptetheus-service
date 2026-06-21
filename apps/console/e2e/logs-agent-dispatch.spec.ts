import { expect, test } from "@playwright/test";

test("logs dispatch opens browser, chat, and voice agent PRs", async ({ page }) => {
  await page.goto("/logs");

  await expect(page.getByRole("heading", { name: "Agent observability" })).toBeVisible();
  await page.getByRole("button", { name: "Create and close test PR" }).click();
  await expect(page.getByRole("link", { name: /Closed PR #94/ })).toHaveAttribute(
    "href",
    "https://github.com/obro79/demo-agents/pull/94",
  );

  await page.getByRole("button", { name: "Dispatch fix for selected run" }).click();

  const proof = page.getByRole("complementary", { name: "Fix DAG proof" });
  await expect(proof.getByText("Agent PRs")).toBeVisible({ timeout: 15_000 });
  await expect(proof.getByText("obro79/demo-agents", { exact: true })).toBeVisible();

  await expect(proof.getByRole("link", { name: /PR #91/ })).toHaveAttribute(
    "href",
    "https://github.com/obro79/demo-agents/pull/91",
  );
  await expect(proof.getByRole("link", { name: /PR #92/ })).toHaveAttribute(
    "href",
    "https://github.com/obro79/demo-agents/pull/92",
  );
  await expect(proof.getByRole("link", { name: /PR #93/ })).toHaveAttribute(
    "href",
    "https://github.com/obro79/demo-agents/pull/93",
  );
  await expect(proof.getByText("Devin requested")).toHaveCount(3);
});
