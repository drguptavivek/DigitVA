import { prefillFromRegistration, type RegistrationFields } from "../src/cases";
import { initialDataFromPrefill } from "../src/prefill";

jest.mock(
  "@drguptavivek/who-2022-va",
  () => ({
    createWhoVaInitialDataFromPrefill: (prefill: { interviewer?: { name?: string }; deceased?: { givenNames?: string; surname?: string; sex?: string } }) => ({
      ...(prefill.interviewer?.name ? { Id10010: prefill.interviewer.name } : {}),
      ...(prefill.deceased?.givenNames ? { Id10017: prefill.deceased.givenNames } : {}),
      ...(prefill.deceased?.surname ? { Id10018: prefill.deceased.surname } : {}),
      ...(prefill.deceased?.sex ? { Id10019: prefill.deceased.sex } : {})
    })
  }),
  { virtual: true }
);

describe("browser WHO prefill", () => {
  it("returns an empty answer set when the server has no prefill", () => {
    expect(initialDataFromPrefill({})).toEqual({});
  });

  it("maps a partial interviewer and deceased prefill through the WHO package", () => {
    expect(
      initialDataFromPrefill({
        interviewer: { name: "Anita Rao" },
        deceased: { givenNames: "Ramesh", surname: "Kumar", sex: "male" }
      })
    ).toMatchObject({ Id10010: "Anita Rao", Id10017: "Ramesh", Id10018: "Kumar", Id10019: "male" });
  });

  it("keeps saved answers over newly supplied registration defaults", () => {
    expect(
      initialDataFromPrefill({
        interviewer: { name: "Current interviewer" },
        answers: { Id10010: "Saved interviewer" }
      })
    ).toMatchObject({ Id10010: "Saved interviewer" });
  });
});

describe("offline registration WHO prefill", () => {
  const fields: RegistrationFields = {
    deceased_name: "  Ram Lal Verma ",
    deceased_sex: "male",
    date_of_death: "2026-09-28",
    informant_name: " Sita Verma ",
    address_house_street: " House 12 ",
    address_village_ward: " Ward 4 ",
    address_landmark: " Near the well ",
    address: " Kandaghat "
  };

  it("maps local address parts to residence and death location in server order", () => {
    expect(prefillFromRegistration(fields).answers).toMatchObject({
      Id10051: "yes",
      Id10055: "House 12, Ward 4, Near the well, Kandaghat",
      Id10057: "House 12, Ward 4, Near the well, Kandaghat",
      Id10007: "Sita Verma"
    });
  });

  it("preserves partial birth precision and can apply cached interviewer identity", () => {
    const prefill = prefillFromRegistration(
      { ...fields, date_of_birth_partial: "1987-04" },
      { name: " Anita Rao ", id: " user-123 " }
    );
    expect(prefill).toMatchObject({
      interviewer: { name: "Anita Rao", id: "user-123" },
      answers: { Id10020: "no", dob_precision: "month_year", dob_month_year: "1987-04-01" }
    });
    expect(prefill.lockedQuestionNames).toEqual(["Id10010", "Id10010c"]);
    expect(prefill.interviewer).not.toHaveProperty("age");
    expect(prefill.deceased).not.toHaveProperty("dateOfBirth");
  });

  it("does not invent sex or interviewer identity values", () => {
    const prefill = prefillFromRegistration({ ...fields, deceased_sex: "unknown" });
    expect(prefill.deceased).toMatchObject({ sex: "undetermined" });
    expect(prefill).not.toHaveProperty("interviewer");
  });

  it("keeps registered adult and child age answers editable and preserves identity locks", () => {
    const interviewer = { name: "Anita Rao", id: "user-123" };
    const adult = prefillFromRegistration({ ...fields, age_years: "58" }, interviewer);
    expect(adult.deceased).toMatchObject({ ageInYears: 58 });
    expect(adult.answers).toMatchObject({ age_group: "adult", age_adult: 58 });
    expect(adult.lockedQuestionNames).toEqual(["Id10010", "Id10010c"]);

    const child = prefillFromRegistration({ ...fields, age_years: "5" }, interviewer);
    expect(child.answers).toMatchObject({ Id10020: "no", age_group: "child", age_child_unit: "years", age_child_years: 5 });
    expect(child.lockedQuestionNames).toEqual(["Id10010", "Id10010c"]);

    const exact = prefillFromRegistration({ ...fields, age_years: "58", date_of_birth: "1968-01-01" }, interviewer);
    expect(exact.deceased).toHaveProperty("dateOfBirth", "1968-01-01");
    expect(exact.deceased).not.toHaveProperty("ageInYears");
    expect(exact.answers).not.toHaveProperty("age_group");
    expect(exact.lockedQuestionNames).toEqual(["Id10010", "Id10010c"]);
  });
});
