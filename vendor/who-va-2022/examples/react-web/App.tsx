import { createInsecureWhoVaBrowserDefaults, WhoVaForm } from "@drguptavivek/who-2022-va/web";

const insecurePrototypeDefaults = createInsecureWhoVaBrowserDefaults();

export default function App() {
  return <WhoVaForm {...insecurePrototypeDefaults} onComplete={(result) => console.log(result)} />;
}
