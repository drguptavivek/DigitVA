import { useRouter } from "expo-router";
import { useState } from "react";
import { Alert, Text, TextInput, View } from "react-native";

import { ActionButton, DemoChrome, ScreenScroll, styles } from "../components/DemoLayout";
import { useDemoState } from "../components/DemoState";

export default function HomeRoute() {
  const router = useRouter();
  const {
    cases,
    completed,
    currentUser,
    defaultApiBaseUrl,
    drafts,
    isDatabaseReady,
    lastUpdate,
    latestDraft,
    login,
    logout,
    switchUser
  } = useDemoState();
  const [apiBaseUrl, setApiBaseUrl] = useState("");
  const [email, setEmail] = useState("");
  const [isLoggingIn, setIsLoggingIn] = useState(false);
  const [password, setPassword] = useState("");
  const [loginMessage, setLoginMessage] = useState("");

  if (!currentUser) {
    return (
      <DemoChrome>
        <ScreenScroll>
          <Text style={styles.screenTitle}>Login</Text>
          <Text style={styles.screenCopy}>
            First login needs the server. After the auth key is cached, the same login and password can open
            the app offline.
          </Text>
          <View style={styles.formPanel}>
            <Text style={styles.fieldLabel}>Server URL</Text>
            <TextInput
              autoCapitalize="none"
              keyboardType="url"
              onChangeText={setApiBaseUrl}
              placeholder={defaultApiBaseUrl}
              style={styles.textInput}
              value={apiBaseUrl}
            />
            <Text style={styles.fieldLabel}>Email or user ID</Text>
            <TextInput
              autoCapitalize="none"
              keyboardType="default"
              onChangeText={setEmail}
              style={styles.textInput}
              value={email}
            />
            <Text style={styles.fieldLabel}>Password</Text>
            <TextInput onChangeText={setPassword} secureTextEntry style={styles.textInput} value={password} />
            <View style={styles.progressTrack}>
              <View
                style={[
                  styles.progressFill,
                  { width: isLoggingIn ? "75%" : isDatabaseReady ? "100%" : "35%" }
                ]}
              />
            </View>
            {!isDatabaseReady ? <Text style={styles.invalidText}>{lastUpdate}</Text> : null}
            {loginMessage ? <Text style={styles.invalidText}>{loginMessage}</Text> : null}
            <View style={styles.actionStack}>
              <ActionButton
                disabled={isLoggingIn}
                label={isLoggingIn ? "Logging in..." : "Login"}
                onPress={() => {
                  setLoginMessage("");
                  if (!isDatabaseReady) {
                    setLoginMessage(lastUpdate || "Local database is still opening. Try again shortly.");
                    return;
                  }
                  setIsLoggingIn(true);
                  void login({ email, password }, apiBaseUrl)
                    .then(() => {
                      setEmail("");
                      setPassword("");
                    })
                    .catch((error: unknown) => {
                      setLoginMessage((error as Error).message);
                    })
                    .finally(() => {
                      setIsLoggingIn(false);
                    });
                }}
              />
            </View>
          </View>
        </ScreenScroll>
      </DemoChrome>
    );
  }

  return (
    <DemoChrome>
      <ScreenScroll>
        <Text style={styles.screenTitle}>Home</Text>
        <Text style={styles.screenCopy}>
          Signed in as {currentUser.name}. Local key: {currentUser.authKey}
        </Text>
        <Text style={styles.screenCopy}>
          Case entries, drafts, and completed submissions are stored in SQLite.
        </Text>
        <View style={styles.actionStack}>
          <ActionButton
            disabled={!isDatabaseReady}
            label="Dashboard"
            onPress={() => router.push("/dashboard")}
          />
          <ActionButton
            disabled={!isDatabaseReady}
            label="Case Data Entry"
            onPress={() => router.push("/case-entry")}
          />
          <ActionButton
            disabled={!isDatabaseReady || !latestDraft}
            label="Continue Last"
            onPress={() => router.push("/continue")}
          />
          <ActionButton
            disabled={!isDatabaseReady}
            label={`Cases (${cases.length}) / Drafts (${drafts.length})`}
            onPress={() => router.push("/drafts")}
            variant="secondary"
          />
          <ActionButton
            disabled={!isDatabaseReady}
            label={`Completed (${completed.length})`}
            onPress={() => router.push("/completed")}
            variant="secondary"
          />
          <ActionButton
            disabled={!isDatabaseReady}
            label="Logout"
            onPress={() => void logout()}
            variant="secondary"
          />
          <ActionButton
            disabled={!isDatabaseReady}
            label="Switch User"
            onPress={() => {
              Alert.alert(
                "Switch accounts",
                "Another user is currently signed in. Continuing will sign out the current user and switch accounts.",
                [
                  { text: "Cancel", style: "cancel" },
                  {
                    text: "Continue",
                    style: "destructive",
                    onPress: () => {
                      void switchUser(apiBaseUrl).then(() => {
                        setEmail("");
                        setPassword("");
                        router.replace("/");
                      });
                    }
                  }
                ]
              );
            }}
            variant="secondary"
          />
        </View>
      </ScreenScroll>
    </DemoChrome>
  );
}
