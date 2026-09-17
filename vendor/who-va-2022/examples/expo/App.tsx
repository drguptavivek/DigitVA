import { SafeAreaView } from "react-native";

import { WhoVaForm } from "@drguptavivek/who-2022-va/native";

export default function App() {
  return (
    <SafeAreaView style={{ flex: 1 }}>
      <WhoVaForm
        onChange={(data) => {
          // Persist to the host application's offline store.
          console.log("draft", data);
        }}
        onComplete={(result) => {
          console.log("validated submission", result);
        }}
      />
    </SafeAreaView>
  );
}
