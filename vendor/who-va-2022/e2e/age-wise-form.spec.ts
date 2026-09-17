import { expect, test, type Page, type TestInfo } from "@playwright/test";

interface AgeScenario {
  name: string;
  born: string;
  ageInDays: number;
  ageInYears: number;
  classification: "isNeonatal" | "isChild" | "isAdult";
  displayQuestion: "displayAgeNeonate" | "displayAgeChild" | "displayAgeAdult";
  displayText: string;
}

const ageScenarios: AgeScenario[] = [
  {
    name: "27-day neonate",
    born: "2026-06-20",
    ageInDays: 27,
    ageInYears: 0,
    classification: "isNeonatal",
    displayQuestion: "displayAgeNeonate",
    displayText: "NEONATE was 27 days old."
  },
  {
    name: "28-day child",
    born: "2026-06-19",
    ageInDays: 28,
    ageInYears: 0,
    classification: "isChild",
    displayQuestion: "displayAgeChild",
    displayText: "CHILD was 0 years 0 months and 28 days old."
  },
  {
    name: "4-year-old child",
    born: "2022-07-17",
    ageInDays: 1461,
    ageInYears: 4,
    classification: "isChild",
    displayQuestion: "displayAgeChild",
    displayText: "CHILD was 4 years 0 months and 0 days old."
  },
  {
    name: "8-year-old child",
    born: "2018-07-17",
    ageInDays: 2922,
    ageInYears: 8,
    classification: "isChild",
    displayQuestion: "displayAgeChild",
    displayText: "CHILD was 8 years 0 months and 0 days old."
  },
  {
    name: "10-year-old child",
    born: "2016-07-16",
    ageInDays: 3653,
    ageInYears: 10,
    classification: "isChild",
    displayQuestion: "displayAgeChild",
    displayText: "CHILD was 10 years 0 months and 0 days old."
  },
  {
    name: "12-year-old adult",
    born: "2014-07-16",
    ageInDays: 4384,
    ageInYears: 12,
    classification: "isAdult",
    displayQuestion: "displayAgeAdult",
    displayText: "ADULT was 12 years old."
  },
  {
    name: "40-year-old adult",
    born: "1986-07-16",
    ageInDays: 14611,
    ageInYears: 40,
    classification: "isAdult",
    displayQuestion: "displayAgeAdult",
    displayText: "ADULT was 40 years old."
  },
  {
    name: "50-year-old adult",
    born: "1976-07-16",
    ageInDays: 18263,
    ageInYears: 50,
    classification: "isAdult",
    displayQuestion: "displayAgeAdult",
    displayText: "ADULT was 50 years old."
  }
];

async function fill(page: Page, question: string, value: string): Promise<void> {
  await page.getByTestId(`question-${question}`).fill(value);
}

async function choose(page: Page, question: string, value: string): Promise<void> {
  await page.getByTestId(`question-${question}-choice-${value}`).click();
}

async function next(page: Page): Promise<void> {
  await page.getByRole("button", { name: "Next", exact: true }).click();
}

async function openEnglishForm(page: Page): Promise<void> {
  await page.goto("/");
  await page.getByLabel("Instrument language").selectOption("en");
  await expect(page.getByRole("button", { name: "Next", exact: true })).toBeVisible();
}

async function fillInterviewer(page: Page): Promise<void> {
  await fill(page, "Id10010", "Browser Interviewer");
  await fill(page, "Id10010a", "35");
  await choose(page, "Id10010b", "female");
  await fill(page, "Id10010c", "E2E-001");
  await choose(page, "language", "en");
  await next(page);
}

async function fillPresets(page: Page): Promise<void> {
  await choose(page, "Id10002", "low");
  await choose(page, "Id10003", "low");
  await choose(page, "Id10004", "dry");
  await next(page);
}

async function fillRespondent(page: Page): Promise<void> {
  await fill(page, "Id10007", "Respondent One");
  await choose(page, "Id10007a", "female");
  await fill(page, "Id10007b", "45");
  await choose(page, "Id10008", "family_member");
  await choose(page, "Id10009", "yes");
  await choose(page, "Id10013", "yes");
  await next(page);
}

async function reachDeceasedScreen(page: Page): Promise<void> {
  await fillInterviewer(page);
  await fillPresets(page);
  await fillRespondent(page);
  await expect(page.getByText("Information on the Deceased", { exact: true })).toBeVisible();
}

async function fillDeceasedScreen(page: Page, scenario: AgeScenario): Promise<void> {
  await fill(page, "Id10017", "Deceased Person");
  await fill(page, "Id10018", "E2E-DECEASED-001");
  await choose(page, "Id10019", "female");
  await choose(page, "Id10020", "yes");
  await fill(page, "Id10021", scenario.born);
  await choose(page, "Id10022", "yes");
  await fill(page, "Id10023_a", "2026-07-17");
  await choose(page, "Id10058", "home");
  await choose(page, "Id10487", "no");
  await choose(page, "Id10051", "no");
  if (scenario.classification === "isAdult") await choose(page, "Id10059", "single");
}

async function calculatedData(page: Page): Promise<Record<string, unknown>> {
  return page.locator("who-va-2022-form").evaluate((element) => {
    return (element as HTMLElement & { getData(): Record<string, unknown> }).getData();
  });
}

async function attachState(page: Page, testInfo: TestInfo, name: string): Promise<void> {
  await testInfo.attach(name, { body: await page.screenshot({ fullPage: true }), contentType: "image/png" });
}

test("required and constraint errors appear, then clear after correction", async ({ page }, testInfo) => {
  await openEnglishForm(page);
  await next(page);
  await expect(page.getByTestId("question-card-Id10010").getByRole("alert")).toContainText("is required");
  await attachState(page, testInfo, "required-errors");

  await fill(page, "Id10010", "Browser Interviewer");
  await fill(page, "Id10010a", "3");
  await expect(page.getByTestId("question-card-Id10010a").getByRole("alert")).toContainText(
    "Interviewer should be an adult"
  );

  await fill(page, "Id10010a", "35");
  await expect(page.getByTestId("question-card-Id10010a").getByRole("alert")).toHaveCount(0);
  await choose(page, "Id10010b", "female");
  await fill(page, "Id10010c", "E2E-001");
  await choose(page, "language", "en");
  await expect(page.getByRole("alert")).toHaveCount(0);
  await next(page);
  await expect(page.getByText("Preset HIV-Malaria mortality and season.", { exact: true })).toBeVisible();
});

for (const scenario of ageScenarios) {
  test(`${scenario.name}: fills the browser form and shows correct calculations`, async ({
    page
  }, testInfo) => {
    await openEnglishForm(page);
    await reachDeceasedScreen(page);
    await fillDeceasedScreen(page, scenario);

    const summary = page.getByTestId(`question-card-${scenario.displayQuestion}`);
    await expect(summary).toContainText(scenario.displayText);
    await expect(page.getByRole("alert")).toHaveCount(0);

    const data = await calculatedData(page);
    expect(data.Id10021).toBe(scenario.born);
    expect(data.ageInDays).toBe(scenario.ageInDays);
    expect(data.ageInYears).toBe(scenario.ageInYears);
    expect(data[scenario.classification]).toBe("1");
    for (const other of ["isNeonatal", "isChild", "isAdult"].filter(
      (name) => name !== scenario.classification
    )) {
      expect(data[other]).toBe("0");
    }

    await attachState(page, testInfo, scenario.name.replaceAll(" ", "-"));
    await next(page);
    await expect(page.getByText("Open narrative", { exact: true })).toBeVisible();
    await expect(page.getByRole("alert")).toHaveCount(0);
  });
}
