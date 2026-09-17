import {
  createInsecureWhoVaBrowserDefaults,
  defineWhoVaElement,
  type WhoVaFormElement
} from "@drguptavivek/who-2022-va/web-component";

defineWhoVaElement();

const form = document.querySelector<WhoVaFormElement>("who-va-2022-form");
if (form) {
  const insecurePrototypeDefaults = createInsecureWhoVaBrowserDefaults();
  form.draftStore = insecurePrototypeDefaults.draftStore;
  form.platform = insecurePrototypeDefaults.platform;
}
form?.addEventListener("who-va-complete", (event) => {
  console.log((event as CustomEvent).detail);
});
