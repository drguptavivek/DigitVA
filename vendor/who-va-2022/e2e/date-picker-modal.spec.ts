import { readFile } from "node:fs/promises";

import { expect, test } from "@playwright/test";

test("date picker is roomy and dismisses from Escape and outside clicks", async ({ page }) => {
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  const bundle = await readFile(
    new URL("../../../app/static/vendor/who-va-2022/who-va-2022.web-component.js", import.meta.url)
  );
  await page.route("http://who-va-calendar.test/**", async (route) => {
    if (new URL(route.request().url()).pathname === "/bundle.js") {
      await route.fulfill({ body: bundle, contentType: "text/javascript" });
      return;
    }
    await route.fulfill({
      contentType: "text/html",
      body: `<!doctype html><html><body style="font-family: Arial, sans-serif"><script type="module">
        import "/bundle.js";
        await customElements.whenDefined("who-va-2022-form");
        const form = document.createElement("who-va-2022-form");
        form.instrument = {
          id: "calendar-test", title: "Calendar test", version: "1", defaultLanguage: "English (en)", sourceFile: "test.json",
          sections: [{ name: "dates", sourceRow: 1, order: 1, label: { en: "Dates" } }],
          questions: [{
            name: "birth_date", order: 1, sourceRow: 2, sourceType: "date", dataType: "date", control: "date",
            label: { en: "Birth date" }, hint: {}, guidance: {}, required: false, readOnly: false,
            constraintMessage: {}, sectionPath: ["dates"],
            constraint: { source: ". >= date('2020-05-01') and . <= date('2020-05-31')" }
          }]
        };
        form.style.setProperty("--who-2022-web-color-brand", "#1b4f9c");
        form.style.setProperty("--who-2022-web-color-surface", "#ffffff");
        document.body.append(form);
        await new Promise((resolve) => setTimeout(resolve, 0));
        form.setData({ birth_date: "2020-05-15" });
      </script></body></html>`
    });
  });
  await page.goto("http://who-va-calendar.test/");
  const dateInput = page.getByTestId("question-birth_date");
  await expect(dateInput).toHaveValue("2020-05-15");
  await expect(dateInput).toHaveAttribute("min", "2020-05-01");
  await expect(dateInput).toHaveAttribute("max", "2020-05-31");
  const calendar = page.getByTestId("question-birth_date-calendar");
  const close = page.getByTestId("react-native-paper-dates-close");

  await calendar.click();
  await expect(close).toBeVisible();
  const calendarWidth = await close.evaluate((button) => {
    let element: HTMLElement | null = button as HTMLElement;
    while (element && getComputedStyle(element).maxWidth !== "400px") element = element.parentElement;
    return element?.getBoundingClientRect().width ?? 0;
  });
  expect(calendarWidth).toBeGreaterThanOrEqual(350);
  await expect(
    page.getByTestId("react-native-paper-dates-prev-month").first().locator("svg path")
  ).toHaveAttribute("stroke", "#667085");
  await expect(
    page.getByTestId("react-native-paper-dates-save").getByText("Save", { exact: true })
  ).toHaveCSS("color", "rgb(27, 79, 156)");
  const surfaceColor = await close.evaluate((button) => {
    let element: HTMLElement | null = button as HTMLElement;
    while (element && getComputedStyle(element).maxWidth !== "400px") element = element.parentElement;
    return element ? getComputedStyle(element).backgroundColor : null;
  });
  expect(surfaceColor).toBe("rgb(255, 255, 255)");
  await expect(page.getByTestId("react-native-paper-dates-day-2020-4-1")).toBeEnabled();
  await expect(page.getByTestId("react-native-paper-dates-day-2020-4-31")).toBeEnabled();
  await page.screenshot({ path: "/tmp/digitva-calendar-theme.png" });

  await page.getByTestId("react-native-paper-dates-prev-month").click();
  await expect(close).toBeVisible();
  await expect(page.getByTestId("react-native-paper-dates-day-2020-3-30")).toBeDisabled();

  await page.keyboard.press("Escape");
  await expect(close).toHaveCount(0);
  await expect(dateInput).toHaveValue("2020-05-15");

  await calendar.click();
  await expect(close).toBeVisible();
  await page.mouse.click(2, 2);
  await expect(close).toHaveCount(0);
  await expect(dateInput).toHaveValue("2020-05-15");

  await page.setViewportSize({ width: 390, height: 844 });
  await calendar.click();
  await expect(close).toBeVisible();
  const modalBounds = await close.evaluate((button) => {
    let element: HTMLElement | null = button as HTMLElement;
    while (element && element.getBoundingClientRect().height < 400) element = element.parentElement;
    const bounds = element?.getBoundingClientRect();
    return bounds ? { bottom: bounds.bottom, left: bounds.left, right: bounds.right, top: bounds.top } : null;
  });
  expect(modalBounds).not.toBeNull();
  expect(modalBounds!.left).toBeGreaterThanOrEqual(0);
  expect(modalBounds!.top).toBeGreaterThanOrEqual(0);
  expect(modalBounds!.right).toBeLessThanOrEqual(390);
  expect(modalBounds!.bottom).toBeLessThanOrEqual(844);
  await close.click();
  await expect(close).toHaveCount(0);
  await expect(dateInput).toHaveValue("2020-05-15");

  await calendar.click();
  await page.getByTestId("react-native-paper-dates-day-2020-4-20").click();
  await expect(close).toBeVisible();
  await page.getByTestId("react-native-paper-dates-save").click();
  await expect(dateInput).toHaveValue("2020-05-20");
  expect(pageErrors).toEqual([]);
});
