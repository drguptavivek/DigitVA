import Constants from "expo-constants";

import appConfig from "../app.json";

/** The installed client release, independent of any downloaded form version. */
export const APP_VERSION =
  Constants.expoConfig?.version ?? appConfig.expo.version;
