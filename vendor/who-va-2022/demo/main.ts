import {
  createInsecureWhoVaBrowserDefaults,
  defineWhoVaElement,
  loadWhoVaWebAttachmentBlob,
  type WhoVaFormElement
} from "../src/web-component.js";
import { WHO_VA_2022_LANGUAGES } from "../src/instrument-loader.js";
import { createWhoVaInitialDataFromPrefill } from "../src/prefill.js";
import type { WhoVaDraft, WhoVaDraftStore } from "../src/types.js";

type DeathPlace = "hospital-death" | "home-death" | "on-the-way-to-hospital" | "other";

interface CaseEntryData {
  district: string;
  block: string;
  villages: string;
  phc: string;
  subcentre: string;
  uid: string;
  date: string;
  deceasedFullName: string;
  deceasedSex: "female" | "male" | "undetermined";
  deceasedHouseAddress: string;
  pinCode: string;
  deathDate: string;
  deathPlace: DeathPlace;
  ageAtDeath: number;
}

type UserRole = "admin" | "data-entry";

interface RegisteredUser {
  userId: string;
  name: string;
  email: string;
  role: UserRole;
  partnerSite: string;
  siteAssigned: string;
  authKey: string;
  createdAt: string;
}

interface RegisterUserPayload {
  name: string;
  email: string;
  role: UserRole | "";
  partnerSite: string;
  siteAssigned: string;
  password: string;
}

interface AdminUserUpdatePayload {
  name: string;
  email: string;
  role: UserRole | "";
  partnerSite: string;
  siteAssigned: string;
  password?: string;
}

interface LoginPayload {
  email: string;
  password: string;
}

interface ChangePasswordPayload {
  currentPassword: string;
  newPassword: string;
}

interface LoginResult {
  user: RegisteredUser;
  entries: SavedCaseEntry[];
}

interface SavedFormEntry {
  id: number;
  uid: string;
  userId?: string | null;
  status: string;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
}

interface SavedCaseEntry extends SavedFormEntry {
  caseEntry?: CaseEntryData;
  case_entry?: CaseEntryData;
  whoVaData?: Record<string, unknown>;
  who_va_prefill?: Record<string, unknown>;
  updatedAt?: string;
}

interface SaveFormEntryPayload {
  uid: string;
  userId?: string;
  authKey?: string;
  caseEntry: CaseEntryData;
  whoVaData: Record<string, unknown>;
  status: "case-entry" | "completed";
  submission?: Record<string, unknown>;
  validationIssues?: unknown[];
}

interface StoredAttachmentResponse {
  id: string;
  uri: string;
  originalName?: string | null;
  storedName: string;
  mimeType: string;
  size: number;
  createdAt: string;
  updatedAt: string;
}

interface StoredCaseEntry {
  uid: string;
  userId?: string | null;
  caseEntry: CaseEntryData;
  whoVaData: Record<string, unknown>;
  updatedAt: string;
}

type DashboardFormStatus = "pending" | "drafted" | "final";
type DashboardFormType = "Adult" | "Child" | "Neonatal" | "Not set";

interface DashboardFormEntry {
  id: number;
  uid: string;
  status: DashboardFormStatus;
  formType?: DashboardFormType;
  sourceStatus: string;
  createdAt: string;
  updatedAt: string;
  completedAt: string | null;
  draftId?: string | null;
  draftSection?: string | null;
  draftUpdatedAt?: string | null;
  caseEntry?: CaseEntryData;
  whoVaData?: Record<string, unknown>;
}

interface DashboardUserGroup {
  userId: string;
  name: string;
  email: string;
  role: string;
  partnerSite: string;
  siteAssigned: string;
  counts: Record<DashboardFormStatus, number>;
  forms: DashboardFormEntry[];
}

defineWhoVaElement();

const LOCAL_CASE_ENTRIES_KEY = "who-va-demo-case-entries";
const API_BASE_STORAGE_KEY = "who-va-demo-api-base";
const editablePrefillQuestionNames = new Set(["Id10051"]);

const configuredApiBase = (() => {
  const fromQuery = new URLSearchParams(window.location.search).get("apiBase");
  const fromStorage = localStorage.getItem(API_BASE_STORAGE_KEY);
  const base = (fromQuery ?? fromStorage ?? "").trim().replace(/\/+$/u, "");
  if (fromQuery) localStorage.setItem(API_BASE_STORAGE_KEY, base);
  return base;
})();

const apiUrl = (path: string) => `${configuredApiBase}${path.startsWith("/") ? path : `/${path}`}`;

const fetchApi = async (path: string, init?: RequestInit) => {
  const url = path.startsWith("http://") || path.startsWith("https://") ? path : apiUrl(path);
  try {
    return await fetch(url, init);
  } catch (error) {
    if (error instanceof TypeError) {
      throw new Error(
        `Could not reach the WHO VA server at ${url}. Start the DB-backed demo server with pnpm dev, or open this page with ?apiBase=http://SERVER_IP:5173 when syncing from another device.`
      );
    }
    throw error;
  }
};

const form = document.querySelector<WhoVaFormElement>("#who-va-form");
const language = document.querySelector<HTMLSelectElement>("#language");

if (form) {
  const insecureDemoDefaults = createInsecureWhoVaBrowserDefaults();
  form.platform = insecureDemoDefaults.platform;
}

for (const availableLanguage of WHO_VA_2022_LANGUAGES) {
  const option = document.createElement("option");
  option.value = availableLanguage.locale;
  option.textContent = availableLanguage.label;
  option.selected = availableLanguage.locale === (form?.getAttribute("locale") ?? "en");
  language?.append(option);
}

language?.addEventListener("change", () => {
  form?.setAttribute("locale", language.value);
  document.documentElement.lang = language.value;
});

const loginShell = document.querySelector<HTMLElement>("#login-shell");
const loginForm = document.querySelector<HTMLFormElement>("#login-form");
const loginOutput = document.querySelector<HTMLOutputElement>("#login-output");
const adminShell = document.querySelector<HTMLElement>("#admin-shell");
const adminSummary = document.querySelector<HTMLElement>("#admin-summary");
const adminRegisterUser = document.querySelector<HTMLButtonElement>("#admin-register-user");
const adminManageUsers = document.querySelector<HTMLButtonElement>("#admin-manage-users");
const adminOpenDataEntry = document.querySelector<HTMLButtonElement>("#admin-open-data-entry");
const adminOpenDashboard = document.querySelector<HTMLButtonElement>("#admin-open-dashboard");
const showDashboard = document.querySelector<HTMLButtonElement>("#show-dashboard");
const showProfile = document.querySelector<HTMLButtonElement>("#show-profile");
const logoutUser = document.querySelector<HTMLButtonElement>("#logout-user");
const menuButtons = Array.from(document.querySelectorAll<HTMLButtonElement>("[data-menu-step]"));
const userManagementShell = document.querySelector<HTMLElement>("#user-management-shell");
const userManagementForm = document.querySelector<HTMLFormElement>("#user-management-form");
const managedUserSelect = document.querySelector<HTMLSelectElement>("#managed-user-select");
const refreshManagedUsers = document.querySelector<HTMLButtonElement>("#refresh-managed-users");
const userManagementOutput = document.querySelector<HTMLOutputElement>("#user-management-output");
const profileShell = document.querySelector<HTMLElement>("#profile-shell");
const profileDetails = document.querySelector<HTMLElement>("#profile-details");
const passwordChangeForm = document.querySelector<HTMLFormElement>("#password-change-form");
const profileOutput = document.querySelector<HTMLOutputElement>("#profile-output");
const dashboardShell = document.querySelector<HTMLElement>("#dashboard-shell");
const dashboardSummary = document.querySelector<HTMLElement>("#dashboard-summary");
const dashboardTotals = document.querySelector<HTMLElement>("#dashboard-totals");
const dashboardUsers = document.querySelector<HTMLElement>("#dashboard-users");
const dashboardOutput = document.querySelector<HTMLOutputElement>("#dashboard-output");
const refreshDashboard = document.querySelector<HTMLButtonElement>("#refresh-dashboard");
const registrationShell = document.querySelector<HTMLElement>("#registration-shell");
const registrationForm = document.querySelector<HTMLFormElement>("#registration-form");
const registrationOutput = document.querySelector<HTMLOutputElement>("#registration-output");
const generatedUserIdInput = document.querySelector<HTMLInputElement>("#generated-user-id");
const showLogin = document.querySelector<HTMLButtonElement>("#show-login");
const showRegistration = document.querySelector<HTMLButtonElement>("#show-registration");
const clearRegistration = document.querySelector<HTMLButtonElement>("#clear-registration");
const casePickerShell = document.querySelector<HTMLElement>("#case-picker-shell");
const deceasedEntrySelect = document.querySelector<HTMLSelectElement>("#deceased-entry-select");
const selectedEntryOutput = document.querySelector<HTMLOutputElement>("#selected-entry-output");
const newCaseEntry = document.querySelector<HTMLButtonElement>("#new-case-entry");
const startSelectedEntries = Array.from(
  document.querySelectorAll<HTMLButtonElement>(".start-selected-entry")
);
const entryShell = document.querySelector<HTMLElement>("#case-entry-shell");
const whoVaShell = document.querySelector<HTMLElement>("#who-va-shell");
const chooseCaseEntry = document.querySelector<HTMLButtonElement>("#choose-case-entry");
const editCaseEntry = document.querySelector<HTMLButtonElement>("#edit-case-entry");
const entryForm = document.querySelector<HTMLFormElement>("#case-entry-form");
const clearCaseEntry = document.querySelector<HTMLButtonElement>("#clear-case-entry");
const uidInput = document.querySelector<HTMLInputElement>("#uid");
const entryOutput = document.querySelector<HTMLOutputElement>("#case-entry-output");
const whoVaOutput = document.querySelector<HTMLOutputElement>("#who-va-output");
let currentCaseEntry: CaseEntryData | undefined;
let currentWhoVaData: Record<string, unknown> | undefined;
let currentUser: RegisteredUser | undefined;
let managedUsers: RegisteredUser[] = [];

const deathPlaceLabels: Record<DeathPlace, string> = {
  "hospital-death": "Hospital death",
  "home-death": "Home death",
  "on-the-way-to-hospital": "On the way to hospital",
  other: "Other place"
};

const deathPlaceAliases = new Map<string, DeathPlace>([
  ["hospital-death", "hospital-death"],
  ["hospital death", "hospital-death"],
  ["hospital", "hospital-death"],
  ["health facility", "hospital-death"],
  ["facility", "hospital-death"],
  ["home-death", "home-death"],
  ["home death", "home-death"],
  ["home", "home-death"],
  ["on-the-way-to-hospital", "on-the-way-to-hospital"],
  ["on the way to hospital", "on-the-way-to-hospital"],
  ["on way to hospital", "on-the-way-to-hospital"],
  ["transit", "on-the-way-to-hospital"],
  ["other", "other"],
  ["other place", "other"],
  ["others", "other"]
]);

const normalizeDeathPlace = (value: unknown): DeathPlace | "" => {
  if (typeof value !== "string") return "";
  const trimmed = value.trim();
  const normalized = trimmed.toLowerCase().replace(/[_-]+/gu, " ").replace(/\s+/gu, " ");
  return deathPlaceAliases.get(trimmed) ?? deathPlaceAliases.get(normalized) ?? "";
};

const normalizeCaseEntry = (entry: CaseEntryData): CaseEntryData => ({
  ...entry,
  deathPlace: normalizeDeathPlace(entry.deathPlace) as CaseEntryData["deathPlace"]
});

const createEntryUid = () => {
  const randomPart = crypto.getRandomValues(new Uint32Array(1))[0].toString(36).padStart(7, "0");
  return `VA-${Date.now().toString(36).toUpperCase()}-${randomPart.toUpperCase()}`;
};

const setVisibleStep = (
  step:
    | "login"
    | "registration"
    | "admin"
    | "user-management"
    | "profile"
    | "dashboard"
    | "picker"
    | "entry"
    | "instrument"
) => {
  if (loginShell) loginShell.hidden = step !== "login";
  if (registrationShell) registrationShell.hidden = step !== "registration";
  if (adminShell) adminShell.hidden = step !== "admin";
  if (userManagementShell) userManagementShell.hidden = step !== "user-management";
  if (profileShell) profileShell.hidden = step !== "profile";
  if (dashboardShell) dashboardShell.hidden = step !== "dashboard";
  if (casePickerShell) casePickerShell.hidden = step !== "picker";
  if (entryShell) entryShell.hidden = step !== "entry";
  if (whoVaShell) whoVaShell.hidden = step !== "instrument";
  for (const button of menuButtons) {
    const isActive = button.dataset.menuStep === step;
    button.classList.toggle("menu-button--active", isActive);
    if (isActive) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  }
};

const hasDataEntryAccess = () => currentUser?.role === "admin" || currentUser?.role === "data-entry";
const hasAdminAccess = () => currentUser?.role === "admin";

const updateAccessControls = () => {
  if (showLogin) showLogin.hidden = currentUser != null;
  if (showRegistration) showRegistration.hidden = currentUser != null && !hasAdminAccess();
  if (showDashboard) showDashboard.hidden = currentUser == null;
  if (showProfile) showProfile.hidden = currentUser == null;
  if (logoutUser) logoutUser.hidden = currentUser == null;
  if (newCaseEntry) newCaseEntry.hidden = !hasDataEntryAccess();
  for (const button of startSelectedEntries) {
    button.hidden = !hasDataEntryAccess();
  }
  renderSelectedEntrySummary();
};

const requireDataEntryAccess = () => {
  if (hasDataEntryAccess()) return true;
  showLoginOutput("Login with an admin or data entry account first.");
  setVisibleStep("login");
  return false;
};

const requireAdminAccess = () => {
  if (hasAdminAccess() || currentUser == null) return true;
  showLoginOutput("Only admin users can register new users.");
  setVisibleStep("login");
  return false;
};

const readStoredCaseEntries = (): StoredCaseEntry[] => {
  try {
    const raw = localStorage.getItem(LOCAL_CASE_ENTRIES_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter((entry): entry is StoredCaseEntry => {
        if (!entry || typeof entry !== "object") return false;
        const candidate = entry as Partial<StoredCaseEntry>;
        return Boolean(candidate.uid && candidate.caseEntry && candidate.whoVaData);
      })
      .map((entry) => ({ ...entry, caseEntry: normalizeCaseEntry(entry.caseEntry) }));
  } catch {
    return [];
  }
};

const writeStoredCaseEntries = (entries: StoredCaseEntry[]) => {
  localStorage.setItem(LOCAL_CASE_ENTRIES_KEY, JSON.stringify(entries));
};

const userCanSeeStoredEntry = (entry: StoredCaseEntry) =>
  currentUser?.role === "admin" || !currentUser || entry.userId === currentUser.userId;

const visibleStoredCaseEntries = () => readStoredCaseEntries().filter(userCanSeeStoredEntry);

const rememberCaseEntry = (caseEntry: CaseEntryData, whoVaData: Record<string, unknown>) => {
  const normalizedCaseEntry = normalizeCaseEntry(caseEntry);
  const entries = readStoredCaseEntries().filter((entry) => entry.uid !== normalizedCaseEntry.uid);
  entries.unshift({
    uid: normalizedCaseEntry.uid,
    userId: currentUser?.userId,
    caseEntry: normalizedCaseEntry,
    whoVaData,
    updatedAt: new Date().toISOString()
  });
  writeStoredCaseEntries(entries.slice(0, 100));
};

const mergeStoredCaseEntries = (primary: StoredCaseEntry[], secondary: StoredCaseEntry[]) => {
  const byUid = new Map<string, StoredCaseEntry>();
  for (const entry of [...secondary, ...primary]) byUid.set(entry.uid, entry);
  return [...byUid.values()].sort((left, right) => right.updatedAt.localeCompare(left.updatedAt));
};

const normalizeSavedCaseEntries = (entries: SavedCaseEntry[]): StoredCaseEntry[] =>
  entries.flatMap((entry) => {
    const caseEntry = entry.caseEntry ?? entry.case_entry;
    const updatedAt = entry.updatedAt ?? entry.updated_at;
    if (!entry.uid || !caseEntry?.deceasedFullName || !updatedAt) return [];
    return [
      {
        uid: entry.uid,
        userId: entry.userId,
        caseEntry: normalizeCaseEntry(caseEntry),
        whoVaData: entry.whoVaData ?? entry.who_va_prefill ?? {},
        updatedAt
      }
    ];
  });

const cacheSyncedCaseEntries = (entries: SavedCaseEntry[]) => {
  const syncedEntries = normalizeSavedCaseEntries(entries);
  if (syncedEntries.length === 0) return 0;
  writeStoredCaseEntries(mergeStoredCaseEntries(syncedEntries, readStoredCaseEntries()).slice(0, 100));
  return syncedEntries.length;
};

const loadSavedCaseEntries = async (): Promise<StoredCaseEntry[]> => {
  const response = await fetchApi(currentUser ? "/api/mobile-sync" : formEntriesApiUrl(), {
    headers: authHeaders()
  });
  const body = await readJsonResponse<{ ok: boolean; entries?: SavedCaseEntry[]; error?: string }>(response);
  if (!response.ok || !body.ok) {
    throw new Error(body.error ?? `Saved entries could not be loaded. Status: ${response.status}.`);
  }
  return normalizeSavedCaseEntries(body.entries ?? []);
};

const refreshDeceasedDropdown = async () => {
  pickerStatusMessage = "Loading saved deceased entries...";
  renderDeceasedDropdown();
  try {
    const remoteEntries = await loadSavedCaseEntries();
    writeStoredCaseEntries(mergeStoredCaseEntries(remoteEntries, visibleStoredCaseEntries()).slice(0, 100));
    pickerStatusMessage =
      remoteEntries.length > 0 ? undefined : "No deceased entries were returned from the database.";
  } catch (error) {
    console.warn("Could not load saved case entries", error);
    pickerStatusMessage = error instanceof Error ? error.message : String(error);
  } finally {
    renderDeceasedDropdown();
  }
};

const selectedStoredCaseEntry = () => {
  const uid = deceasedEntrySelect?.value;
  if (!uid) return undefined;
  return visibleStoredCaseEntries().find((entry) => entry.uid === uid);
};

const formatDeathPlace = (deathPlace?: CaseEntryData["deathPlace"]) => {
  const normalized = normalizeDeathPlace(deathPlace);
  if (normalized) return deathPlaceLabels[normalized];
  return "Not recorded";
};

let pickerStatusMessage: string | undefined;

const renderSelectedEntrySummary = () => {
  const selected = selectedStoredCaseEntry();
  for (const button of startSelectedEntries) button.disabled = !selected || !hasDataEntryAccess();
  if (!selectedEntryOutput) return;

  if (!selected) {
    selectedEntryOutput.hidden = !pickerStatusMessage;
    selectedEntryOutput.textContent = pickerStatusMessage ?? "";
    return;
  }

  const entry = selected.caseEntry;
  selectedEntryOutput.hidden = false;
  selectedEntryOutput.textContent = [
    ...(pickerStatusMessage ? [pickerStatusMessage, ""] : []),
    `UID: ${entry.uid}`,
    `Address: ${entry.deceasedHouseAddress}`,
    `Village: ${entry.villages}`,
    `District: ${entry.district}`,
    `Sex: ${entry.deceasedSex ?? "Not recorded"}`,
    `Death date: ${entry.deathDate}`,
    `Death place: ${formatDeathPlace(entry.deathPlace)}`,
    `Age at death: ${entry.ageAtDeath}`
  ].join("\n");
};

const renderDeceasedDropdown = () => {
  if (!deceasedEntrySelect) return;
  const currentValue = deceasedEntrySelect.value;
  const entries = visibleStoredCaseEntries();
  deceasedEntrySelect.replaceChildren();

  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = entries.length ? "Select deceased name" : "No saved deceased entries";
  deceasedEntrySelect.append(placeholder);

  for (const stored of entries) {
    const option = document.createElement("option");
    option.value = stored.uid;
    option.textContent = `${stored.caseEntry.deceasedFullName} (${stored.uid})`;
    option.selected = stored.uid === currentValue;
    deceasedEntrySelect.append(option);
  }

  renderSelectedEntrySummary();
};

const setDefaultEntryValues = () => {
  if (!entryForm || !uidInput) return;

  const today = new Date().toISOString().slice(0, 10);
  uidInput.value = createEntryUid();
  const deathDateInput = entryForm.elements.namedItem("deathDate") as HTMLInputElement | null;
  if (deathDateInput) deathDateInput.max = today;
  const dateInput = entryForm.elements.namedItem("date") as HTMLInputElement | null;
  if (dateInput && !dateInput.value) {
    dateInput.value = today;
  }
};

const clearEntryFormValues = () => {
  entryForm?.reset();
  window.setTimeout(() => {
    setDefaultEntryValues();
    if (entryOutput) {
      entryOutput.hidden = true;
      entryOutput.textContent = "";
    }
    currentCaseEntry = undefined;
    currentWhoVaData = undefined;
  });
};

const fillCaseEntryForm = (entry: CaseEntryData) => {
  if (!entryForm) return;
  for (const [name, value] of Object.entries(normalizeCaseEntry(entry))) {
    const control = entryForm.elements.namedItem(name) as HTMLInputElement | HTMLTextAreaElement | null;
    if (control) control.value = String(value);
  }
};

const readCaseEntryData = (sourceForm: HTMLFormElement): CaseEntryData => {
  const formData = new FormData(sourceForm);
  const entryDate = String(formData.get("date") ?? "") || new Date().toISOString().slice(0, 10);
  return {
    district: String(formData.get("district") ?? ""),
    block: String(formData.get("block") ?? ""),
    villages: String(formData.get("villages") ?? ""),
    phc: String(formData.get("phc") ?? ""),
    subcentre: String(formData.get("subcentre") ?? ""),
    uid: String(formData.get("uid") ?? ""),
    date: entryDate,
    deceasedFullName: String(formData.get("deceasedFullName") ?? ""),
    deceasedSex: String(formData.get("deceasedSex") ?? "") as CaseEntryData["deceasedSex"],
    deceasedHouseAddress: String(formData.get("deceasedHouseAddress") ?? ""),
    pinCode: String(formData.get("pinCode") ?? ""),
    deathDate: String(formData.get("deathDate") ?? ""),
    deathPlace: normalizeDeathPlace(formData.get("deathPlace")) as CaseEntryData["deathPlace"],
    ageAtDeath: Number(formData.get("ageAtDeath") ?? 0)
  };
};

const isFutureDate = (value: string) => {
  const date = new Date(`${value}T00:00:00`);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return !Number.isNaN(date.getTime()) && date.getTime() > today.getTime();
};

const validateCaseEntryData = (data: CaseEntryData): string | undefined => {
  if (!data.deathDate) return "Death date is required.";
  if (isFutureDate(data.deathDate)) return "Death date cannot be in the future.";
  if (!data.deathPlace) {
    return "Select a valid death place: Hospital death, Home death, On the way to hospital, or Other place.";
  }
  return undefined;
};

const focusDeathPlaceControl = () => {
  const control = entryForm?.elements.namedItem("deathPlace") as HTMLSelectElement | null;
  control?.focus();
  control?.scrollIntoView({ block: "center" });
};

const createWhoVaDataFromCaseEntry = (entry: CaseEntryData) => {
  const whoVaData = createWhoVaInitialDataFromPrefill({
    deceased: {
      givenNames: entry.deceasedFullName,
      sex: entry.deceasedSex,
      ...(entry.ageAtDeath >= 12 ? { ageInYears: entry.ageAtDeath } : {}),
      dateOfDeath: entry.deathDate
    },
    location: {
      district: entry.district,
      village: entry.villages
    }
  });

  if (entry.ageAtDeath > 0 && entry.ageAtDeath < 12) {
    whoVaData.Id10020 = "no";
    whoVaData.age_group = "child";
    whoVaData.age_child_unit = "years";
    whoVaData.age_child_years = entry.ageAtDeath;
  }

  return whoVaData as Record<string, unknown>;
};

const showEntryOutput = (value: unknown) => {
  const output = whoVaShell?.hidden ? entryOutput : whoVaOutput;
  if (!output) return;
  output.hidden = false;
  output.textContent = typeof value === "string" ? value : JSON.stringify(value, null, 2);
};
const showRegistrationOutput = (value: unknown) => {
  if (!registrationOutput) return;
  registrationOutput.hidden = false;
  registrationOutput.textContent = typeof value === "string" ? value : JSON.stringify(value, null, 2);
};

const usersApiUrl = () => apiUrl("/api/users");
const profileApiUrl = () => apiUrl("/api/profile");
const passwordApiUrl = () => apiUrl("/api/profile/password");

const roleLabel = (role: string) => {
  if (role === "admin") return "Admin";
  if (role === "data-entry") return "Data entry";
  return role || "Not recorded";
};

const renderProfileDetails = () => {
  if (!profileDetails) return;
  profileDetails.replaceChildren();
  if (!currentUser) return;

  const details = [
    ["Name", currentUser.name],
    ["Email", currentUser.email],
    ["User ID", currentUser.userId],
    ["Role", roleLabel(currentUser.role)],
    ["Partner site", currentUser.partnerSite],
    ["Site assigned", currentUser.siteAssigned],
    ["Created", formatDateTime(currentUser.createdAt)]
  ];

  for (const [label, value] of details) {
    const term = document.createElement("dt");
    term.textContent = label;
    const description = document.createElement("dd");
    description.textContent = value || "Not recorded";
    profileDetails.append(term, description);
  }
};

const showProfileOutput = (value: unknown) => {
  if (!profileOutput) return;
  profileOutput.hidden = false;
  profileOutput.textContent = typeof value === "string" ? value : JSON.stringify(value, null, 2);
};

const loadCurrentUserProfile = async (): Promise<RegisteredUser> => {
  const response = await fetchApi(profileApiUrl(), { headers: authHeaders() });
  const body = await readJsonResponse<{ ok: boolean; user?: RegisteredUser; error?: string }>(response);
  if (!response.ok || !body.ok || !body.user) {
    throw new Error(body.error ?? `Profile could not be loaded. Status: ${response.status}.`);
  }
  return body.user;
};

const openProfile = async () => {
  if (!currentUser) {
    showLoginOutput("Login before opening your profile.");
    setVisibleStep("login");
    loginShell?.scrollIntoView({ block: "start" });
    return;
  }
  renderProfileDetails();
  if (profileOutput) {
    profileOutput.hidden = true;
    profileOutput.textContent = "";
  }
  try {
    currentUser = await loadCurrentUserProfile();
    renderProfileDetails();
  } catch (error) {
    showProfileOutput(error instanceof Error ? error.message : String(error));
  }
  setVisibleStep("profile");
  profileShell?.scrollIntoView({ block: "start" });
};

const readRegistrationData = (sourceForm: HTMLFormElement): RegisterUserPayload => {
  const formData = new FormData(sourceForm);
  return {
    name: String(formData.get("name") ?? "").trim(),
    email: String(formData.get("email") ?? "")
      .trim()
      .toLowerCase(),
    role: String(formData.get("role") ?? "").trim() as UserRole | "",
    partnerSite: String(formData.get("partnerSite") ?? "").trim(),
    siteAssigned: String(formData.get("siteAssigned") ?? "").trim(),
    password: String(formData.get("password") ?? "")
  };
};

const validateRegistrationData = (data: RegisterUserPayload): string | undefined => {
  if (!/^[A-Za-z]+(?: [A-Za-z]+)*$/u.test(data.name)) {
    return "Name accepts letters only. Spaces are allowed between words.";
  }
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/u.test(data.email)) return "Enter a valid email address.";
  if (data.role !== "admin" && data.role !== "data-entry") return "Select a valid role.";
  if (!data.partnerSite) return "Select a partner site.";
  if (!data.siteAssigned) return "Select an assigned site.";
  if (data.password.length < 8) return "Password must be at least 8 characters.";
  return undefined;
};

const validateManagedUserData = (data: AdminUserUpdatePayload): string | undefined => {
  if (!/^[A-Za-z]+(?: [A-Za-z]+)*$/u.test(data.name)) {
    return "Name accepts letters only. Spaces are allowed between words.";
  }
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/u.test(data.email)) return "Enter a valid email address.";
  if (data.role !== "admin" && data.role !== "data-entry") return "Select a valid role.";
  if (!data.partnerSite) return "Select a partner site.";
  if (!data.siteAssigned) return "Select an assigned site.";
  if (data.password && data.password.length < 8) return "Password must be at least 8 characters.";
  return undefined;
};

const registerUser = async (payload: RegisterUserPayload): Promise<RegisteredUser> => {
  const response = await fetchApi(usersApiUrl(), {
    method: "POST",
    headers: { "content-type": "application/json", ...authHeaders() },
    body: JSON.stringify(payload)
  });
  const body = await readJsonResponse<{ ok: boolean; user?: RegisteredUser; error?: string }>(response);
  if (!response.ok || !body.ok || !body.user) {
    throw new Error(body.error ?? `User could not be registered. Status: ${response.status}.`);
  }
  return body.user;
};

const userApiUrl = (userId: string) => `${usersApiUrl()}/${encodeURIComponent(userId)}`;

const showUserManagementOutput = (value: unknown) => {
  if (!userManagementOutput) return;
  userManagementOutput.hidden = false;
  userManagementOutput.textContent = typeof value === "string" ? value : JSON.stringify(value, null, 2);
};

const readManagedUserData = (sourceForm: HTMLFormElement): AdminUserUpdatePayload => {
  const formData = new FormData(sourceForm);
  const password = String(formData.get("password") ?? "");
  return {
    name: String(formData.get("name") ?? "").trim(),
    email: String(formData.get("email") ?? "")
      .trim()
      .toLowerCase(),
    role: String(formData.get("role") ?? "").trim() as UserRole | "",
    partnerSite: String(formData.get("partnerSite") ?? "").trim(),
    siteAssigned: String(formData.get("siteAssigned") ?? "").trim(),
    ...(password ? { password } : {})
  };
};

const loadManagedUsers = async (): Promise<RegisteredUser[]> => {
  const response = await fetchApi(usersApiUrl(), { headers: authHeaders() });
  const body = await readJsonResponse<{ ok: boolean; users?: RegisteredUser[]; error?: string }>(response);
  if (!response.ok || !body.ok) {
    throw new Error(body.error ?? `Users could not be loaded. Status: ${response.status}.`);
  }
  return body.users ?? [];
};

const updateManagedUser = async (
  userId: string,
  payload: AdminUserUpdatePayload
): Promise<RegisteredUser> => {
  const response = await fetchApi(userApiUrl(userId), {
    method: "PATCH",
    headers: { "content-type": "application/json", ...authHeaders() },
    body: JSON.stringify(payload)
  });
  const body = await readJsonResponse<{ ok: boolean; user?: RegisteredUser; error?: string }>(response);
  if (!response.ok || !body.ok || !body.user) {
    throw new Error(body.error ?? `User could not be updated. Status: ${response.status}.`);
  }
  return body.user;
};

const populateManagedUserForm = (userId: string) => {
  const user = managedUsers.find((candidate) => candidate.userId === userId);
  if (!userManagementForm || !user) return;
  const setValue = (name: string, value: string) => {
    const control = userManagementForm.elements.namedItem(name) as
      HTMLInputElement | HTMLSelectElement | null;
    if (control) control.value = value;
  };
  setValue("name", user.name);
  setValue("email", user.email);
  setValue("role", user.role);
  setValue("partnerSite", user.partnerSite);
  setValue("siteAssigned", user.siteAssigned);
  setValue("password", "");
};

const renderManagedUserSelect = (selectedUserId = managedUserSelect?.value ?? "") => {
  if (!managedUserSelect) return;
  managedUserSelect.replaceChildren();
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = managedUsers.length ? "Select user" : "No users found";
  managedUserSelect.append(placeholder);

  for (const user of managedUsers) {
    const option = document.createElement("option");
    option.value = user.userId;
    option.textContent = `${user.name} (${user.email}) - ${roleLabel(user.role)}`;
    option.selected = user.userId === selectedUserId;
    managedUserSelect.append(option);
  }

  const nextUserId = managedUsers.some((user) => user.userId === selectedUserId)
    ? selectedUserId
    : (managedUsers[0]?.userId ?? "");
  managedUserSelect.value = nextUserId;
  populateManagedUserForm(nextUserId);
};

const refreshManagedUserList = async (selectedUserId = managedUserSelect?.value ?? "") => {
  if (!hasAdminAccess()) {
    showLoginOutput("Only admin users can manage user accounts.");
    setVisibleStep("login");
    return;
  }
  showUserManagementOutput("Loading users...");
  managedUsers = await loadManagedUsers();
  renderManagedUserSelect(selectedUserId);
  if (userManagementOutput) {
    userManagementOutput.hidden = true;
    userManagementOutput.textContent = "";
  }
};

const openUserManagement = async () => {
  if (!hasAdminAccess()) {
    showLoginOutput("Only admin users can manage user accounts.");
    setVisibleStep("login");
    loginShell?.scrollIntoView({ block: "start" });
    return;
  }
  setVisibleStep("user-management");
  userManagementShell?.scrollIntoView({ block: "start" });
  try {
    await refreshManagedUserList();
  } catch (error) {
    showUserManagementOutput(error instanceof Error ? error.message : String(error));
  }
};

const readPasswordChangeData = (
  sourceForm: HTMLFormElement
): ChangePasswordPayload & {
  confirmPassword: string;
} => {
  const formData = new FormData(sourceForm);
  return {
    currentPassword: String(formData.get("currentPassword") ?? ""),
    newPassword: String(formData.get("newPassword") ?? ""),
    confirmPassword: String(formData.get("confirmPassword") ?? "")
  };
};

const validatePasswordChangeData = (
  data: ChangePasswordPayload & { confirmPassword: string }
): string | undefined => {
  if (!data.currentPassword) return "Enter your current password.";
  if (data.newPassword.length < 8 || data.newPassword.length > 128) {
    return "New password must be between 8 and 128 characters.";
  }
  if (data.newPassword !== data.confirmPassword) return "New password and confirmation do not match.";
  return undefined;
};

const changeCurrentUserPassword = async (payload: ChangePasswordPayload): Promise<RegisteredUser> => {
  const response = await fetchApi(passwordApiUrl(), {
    method: "POST",
    headers: { "content-type": "application/json", ...authHeaders() },
    body: JSON.stringify(payload)
  });
  const body = await readJsonResponse<{ ok: boolean; user?: RegisteredUser; error?: string }>(response);
  if (!response.ok || !body.ok || !body.user) {
    throw new Error(body.error ?? `Password could not be changed. Status: ${response.status}.`);
  }
  return body.user;
};
const readLoginData = (sourceForm: HTMLFormElement): LoginPayload => {
  const formData = new FormData(sourceForm);
  return {
    email: String(formData.get("email") ?? "").trim(),
    password: String(formData.get("password") ?? "")
  };
};

const loginUser = async (payload: LoginPayload): Promise<LoginResult> => {
  const response = await fetchApi("/api/login", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload)
  });
  const body = await readJsonResponse<{
    ok: boolean;
    user?: RegisteredUser;
    entries?: SavedCaseEntry[];
    error?: string;
  }>(response);
  if (!response.ok || !body.ok || !body.user) {
    throw new Error(body.error ?? `Login failed. Status: ${response.status}.`);
  }
  return { user: body.user, entries: body.entries ?? [] };
};

const showLoginOutput = (value: unknown) => {
  if (!loginOutput) return;
  loginOutput.hidden = false;
  loginOutput.textContent = typeof value === "string" ? value : JSON.stringify(value, null, 2);
};

const logoutCurrentUser = () => {
  const previousUser = currentUser;
  currentUser = undefined;
  currentCaseEntry = undefined;
  currentWhoVaData = undefined;
  pickerStatusMessage = undefined;
  if (previousUser?.role !== "admin") {
    writeStoredCaseEntries(
      readStoredCaseEntries().filter((entry) => entry.userId && entry.userId !== previousUser?.userId)
    );
  }
  loginForm?.reset();
  if (loginOutput) {
    loginOutput.hidden = true;
    loginOutput.textContent = "";
  }
  if (dashboardUsers) dashboardUsers.replaceChildren();
  if (dashboardTotals) dashboardTotals.replaceChildren();
  if (dashboardOutput) {
    dashboardOutput.hidden = true;
    dashboardOutput.textContent = "";
  }
  passwordChangeForm?.reset();
  if (profileDetails) profileDetails.replaceChildren();
  if (profileOutput) {
    profileOutput.hidden = true;
    profileOutput.textContent = "";
  }
  managedUsers = [];
  userManagementForm?.reset();
  managedUserSelect?.replaceChildren();
  if (userManagementOutput) {
    userManagementOutput.hidden = true;
    userManagementOutput.textContent = "";
  }
  form?.setLockedQuestionNames([]);
  form?.setData({});
  updateAccessControls();
  setVisibleStep("login");
  loginShell?.scrollIntoView({ block: "start" });
};

const showRolePage = (user: RegisteredUser) => {
  currentUser = user;
  updateAccessControls();
  if (user.role === "admin") {
    if (adminSummary) {
      adminSummary.textContent = `Signed in as ${user.name} (${user.email}). Role: Admin.`;
    }
    setVisibleStep("admin");
    adminShell?.scrollIntoView({ block: "start" });
    return;
  }
  void refreshDeceasedDropdown();
  setVisibleStep("picker");
  casePickerShell?.scrollIntoView({ block: "start" });
};

const applyCaseEntryToInstrument = async (caseEntry: CaseEntryData, whoVaData: Record<string, unknown>) => {
  const normalizedCaseEntry = normalizeCaseEntry(caseEntry);
  currentCaseEntry = normalizedCaseEntry;
  currentWhoVaData = whoVaData;
  form?.setAttribute("draft-id", normalizedCaseEntry.uid);
  form?.setLockedQuestionNames(
    Object.keys(whoVaData).filter((name) => !editablePrefillQuestionNames.has(name))
  );
  form?.setData(whoVaData);
  setVisibleStep("instrument");
  whoVaShell?.scrollIntoView({ block: "start" });

  try {
    const savedDraft = await dbDraftStore.load(normalizedCaseEntry.uid);
    if (savedDraft) form?.setData(savedDraft.data);
  } catch (error) {
    console.warn("Could not load saved WHO VA draft", error);
  }
};

const formEntriesApiUrl = () => apiUrl("/api/form-entries");

const authHeaders = (): Record<string, string> =>
  currentUser?.userId && currentUser.authKey
    ? { "x-user-id": currentUser.userId, "x-auth-key": currentUser.authKey }
    : {};

const dashboardApiUrl = () => {
  return apiUrl("/api/dashboard");
};

const draftsApiUrl = (id?: string) => {
  const base = formEntriesApiUrl().replace(/\/form-entries$/u, "/drafts");
  return id ? `${base}/${encodeURIComponent(id)}` : base;
};

const readJsonResponse = async <T extends { error?: string }>(response: Response): Promise<T> => {
  const responseText = await response.text();
  try {
    const body = responseText ? (JSON.parse(responseText) as T) : ({} as T);
    if (!response.ok && body.error) {
      throw new Error(`${body.error} (HTTP ${response.status})`);
    }
    return body;
  } catch (error) {
    if (error instanceof Error && responseText && responseText.trim().startsWith("{")) throw error;
    throw new Error(
      `The API returned a web page instead of JSON. Open the DB-backed demo server, not the plain Vite server. Status: ${response.status}.`
    );
  }
};

const isLocalAttachmentReference = (
  value: unknown
): value is Record<string, unknown> & {
  id: string;
  uri: string;
} => {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const candidate = value as Record<string, unknown>;
  return (
    typeof candidate.id === "string" &&
    typeof candidate.uri === "string" &&
    candidate.uri.startsWith("who-va-attachment:")
  );
};

const uploadAttachmentReference = async (
  reference: Record<string, unknown> & { id: string; uri: string }
): Promise<Record<string, unknown>> => {
  const blob = await loadWhoVaWebAttachmentBlob({ id: reference.id });
  if (!blob) throw new Error(`Attachment ${reference.id} is missing from browser storage.`);
  const name =
    typeof reference.name === "string"
      ? reference.name
      : typeof reference.originalName === "string"
        ? reference.originalName
        : reference.id;
  const mimeType =
    typeof reference.mimeType === "string" && reference.mimeType ? reference.mimeType : blob.type;
  const response = await fetchApi(`/api/attachments/${encodeURIComponent(reference.id)}`, {
    method: "PUT",
    headers: {
      "content-type": mimeType || "application/octet-stream",
      "x-attachment-name": encodeURIComponent(name),
      "x-attachment-size": String(blob.size),
      ...authHeaders()
    },
    body: blob
  });
  const body = await readJsonResponse<{
    ok: boolean;
    attachment?: StoredAttachmentResponse;
    error?: string;
  }>(response);
  if (!response.ok || !body.ok || !body.attachment) {
    throw new Error(
      body.error ?? `Attachment ${reference.id} could not be saved. Status: ${response.status}.`
    );
  }
  return {
    ...reference,
    uri: body.attachment.uri,
    serverAttachmentId: body.attachment.id,
    storage: "filesystem",
    storedName: body.attachment.storedName,
    serverStored: true
  };
};

const uploadAttachmentsInValue = async (
  value: unknown,
  uploaded = new Map<string, Promise<Record<string, unknown>>>()
): Promise<unknown> => {
  if (isLocalAttachmentReference(value)) {
    let upload = uploaded.get(value.id);
    if (!upload) {
      upload = uploadAttachmentReference(value);
      uploaded.set(value.id, upload);
    }
    return upload;
  }
  if (Array.isArray(value)) return Promise.all(value.map((item) => uploadAttachmentsInValue(item, uploaded)));
  if (!value || typeof value !== "object") return value;
  const entries = await Promise.all(
    Object.entries(value as Record<string, unknown>).map(async ([key, nested]) => [
      key,
      await uploadAttachmentsInValue(nested, uploaded)
    ])
  );
  return Object.fromEntries(entries);
};

const uploadAttachmentsInRecord = async (data: Record<string, unknown>): Promise<Record<string, unknown>> =>
  (await uploadAttachmentsInValue(data)) as Record<string, unknown>;
const dbDraftStore: WhoVaDraftStore = {
  async save(draft) {
    const uploadedDraft: WhoVaDraft = {
      ...draft,
      data: (await uploadAttachmentsInRecord(draft.data as Record<string, unknown>)) as WhoVaDraft["data"]
    };
    const response = await fetchApi(draftsApiUrl(), {
      method: "POST",
      headers: { "content-type": "application/json", ...authHeaders() },
      body: JSON.stringify({ draft: uploadedDraft })
    });
    const body = await readJsonResponse<{ ok: boolean; error?: string }>(response);
    if (!response.ok || !body.ok) {
      throw new Error(body.error ?? `Draft could not be saved. Status: ${response.status}.`);
    }
  },
  async load(id) {
    const response = await fetchApi(draftsApiUrl(id), { headers: authHeaders() });
    if (response.status === 404) return undefined;
    const body = await readJsonResponse<{ ok: boolean; draft?: WhoVaDraft; error?: string }>(response);
    if (!response.ok || !body.ok) {
      throw new Error(body.error ?? `Draft could not be loaded. Status: ${response.status}.`);
    }
    return body.draft;
  },
  async remove(id) {
    const response = await fetchApi(draftsApiUrl(id), { method: "DELETE", headers: authHeaders() });
    const body = await readJsonResponse<{ ok: boolean; error?: string }>(response);
    if (!response.ok || !body.ok) {
      throw new Error(body.error ?? `Draft could not be removed. Status: ${response.status}.`);
    }
  }
};
if (form) form.draftStore = dbDraftStore;

form?.addEventListener("who-va-draft-saved", (event) => {
  const draft = (event as CustomEvent<WhoVaDraft>).detail;
  showEntryOutput(`Draft saved to PostgreSQL: ${draft.id}`);
});

form?.addEventListener("who-va-draft-error", (event) => {
  const error = (event as CustomEvent<Error>).detail;
  showEntryOutput(error instanceof Error ? error.message : String(error));
});

const saveFormEntry = async (payload: SaveFormEntryPayload): Promise<SavedFormEntry> => {
  const uploadedPayload: SaveFormEntryPayload = {
    ...payload,
    whoVaData: await uploadAttachmentsInRecord(payload.whoVaData),
    ...(payload.submission ? { submission: await uploadAttachmentsInRecord(payload.submission) } : {})
  };
  const response = await fetchApi(formEntriesApiUrl(), {
    method: "POST",
    headers: { "content-type": "application/json", ...authHeaders() },
    body: JSON.stringify(uploadedPayload)
  });
  const responseText = await response.text();
  let body: { ok: boolean; saved?: SavedFormEntry; error?: string } | undefined;
  try {
    body = responseText
      ? (JSON.parse(responseText) as { ok: boolean; saved?: SavedFormEntry; error?: string })
      : undefined;
  } catch {
    throw new Error(
      `The save API returned a non-JSON response. Open the DB-backed demo server, not the plain Vite server. Status: ${response.status}.`
    );
  }
  if (!response.ok || !body?.ok || !body.saved) {
    throw new Error(
      body?.error ??
        `The entry could not be saved. Status: ${response.status}. Response: ${responseText || "empty"}`
    );
  }
  return body.saved;
};

const showDashboardOutput = (value: unknown) => {
  if (!dashboardOutput) return;
  dashboardOutput.hidden = false;
  dashboardOutput.textContent = typeof value === "string" ? value : JSON.stringify(value, null, 2);
};

const formatDateTime = (value?: string | null) => {
  if (!value) return "Not yet";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
};

const dashboardStatusLabel = (status: DashboardFormStatus) => {
  if (status === "final") return "Final";
  if (status === "drafted") return "Drafted";
  return "Pending";
};

const dashboardActionLabel = (status: DashboardFormStatus) => {
  if (status === "final") return "Update form";
  if (status === "drafted") return "Complete task";
  return "Start form";
};

const selectedFlag = (value: unknown) => value === "1" || value === 1 || value === true;

const dashboardFormTypeLabel = (whoVaData?: Record<string, unknown>): DashboardFormType => {
  if (!whoVaData) return "Not set";
  if (selectedFlag(whoVaData.isAdult) || whoVaData.age_group === "adult") return "Adult";
  if (selectedFlag(whoVaData.isChild) || whoVaData.age_group === "child") return "Child";
  if (selectedFlag(whoVaData.isNeonatal) || whoVaData.age_group === "neonate") return "Neonatal";
  return "Not set";
};

const createStatusTotal = (label: string, value: number) => {
  const item = document.createElement("div");
  item.className = "dashboard-total";
  const number = document.createElement("strong");
  number.textContent = String(value);
  const text = document.createElement("span");
  text.textContent = label;
  item.append(number, text);
  return item;
};

const createStatusPill = (label: string, value: number) => {
  const item = document.createElement("span");
  item.className = "dashboard-pill";
  item.textContent = `${label}: ${value}`;
  return item;
};

const openDashboardForm = async (entry: DashboardFormEntry) => {
  if (!requireDataEntryAccess()) return;
  if (!entry.caseEntry) {
    showDashboardOutput(`Case entry data is missing for ${entry.uid}.`);
    return;
  }
  const whoVaData = entry.whoVaData ?? createWhoVaDataFromCaseEntry(entry.caseEntry);
  fillCaseEntryForm(entry.caseEntry);
  await applyCaseEntryToInstrument(entry.caseEntry, whoVaData);
};

const renderDashboard = (users: DashboardUserGroup[]) => {
  if (!dashboardTotals || !dashboardUsers) return;
  const totals = users.reduce(
    (accumulator, user) => {
      accumulator.pending += user.counts.pending;
      accumulator.drafted += user.counts.drafted;
      accumulator.final += user.counts.final;
      return accumulator;
    },
    { pending: 0, drafted: 0, final: 0 }
  );
  const totalForms = totals.pending + totals.drafted + totals.final;
  if (dashboardSummary) {
    dashboardSummary.textContent =
      currentUser?.role === "admin"
        ? `${totalForms} forms across ${users.length} users.`
        : `${totalForms} forms assigned to ${currentUser?.name ?? "this user"}.`;
  }

  dashboardTotals.replaceChildren(
    createStatusTotal("Pending", totals.pending),
    createStatusTotal("Drafted", totals.drafted),
    createStatusTotal("Final", totals.final)
  );
  dashboardUsers.replaceChildren();

  if (users.length === 0) {
    const empty = document.createElement("p");
    empty.className = "dashboard-empty";
    empty.textContent = "No WHO VA forms found for this user.";
    dashboardUsers.append(empty);
    return;
  }

  for (const user of users) {
    const section = document.createElement("section");
    section.className = "dashboard-user";

    const header = document.createElement("div");
    header.className = "dashboard-user__header";
    const title = document.createElement("h3");
    title.textContent = user.email ? `${user.name} (${user.email})` : user.name;
    const meta = document.createElement("p");
    meta.textContent = [user.role, user.partnerSite, user.siteAssigned].filter(Boolean).join(" | ");
    header.append(title, meta);

    const counts = document.createElement("div");
    counts.className = "dashboard-user__counts";
    counts.append(
      createStatusPill("Pending", user.counts.pending),
      createStatusPill("Drafted", user.counts.drafted),
      createStatusPill("Final", user.counts.final)
    );

    const table = document.createElement("table");
    table.className = "dashboard-table";
    table.innerHTML = `
      <thead>
        <tr>
          <th>UID</th>
          <th>Deceased</th>
          <th>Form type</th>
          <th>Status</th>
          <th>Last update</th>
          <th>Action</th>
        </tr>
      </thead>
    `;
    const body = document.createElement("tbody");
    for (const formEntry of user.forms) {
      const row = document.createElement("tr");
      const uid = document.createElement("td");
      uid.textContent = formEntry.uid;
      const deceased = document.createElement("td");
      deceased.textContent = formEntry.caseEntry?.deceasedFullName ?? "Not recorded";
      const formType = document.createElement("td");
      formType.textContent = formEntry.formType ?? dashboardFormTypeLabel(formEntry.whoVaData);
      const status = document.createElement("td");
      const statusBadge = document.createElement("span");
      statusBadge.className = `dashboard-status dashboard-status--${formEntry.status}`;
      statusBadge.textContent = dashboardStatusLabel(formEntry.status);
      status.append(statusBadge);
      const updated = document.createElement("td");
      updated.textContent = formatDateTime(
        formEntry.status === "final"
          ? formEntry.completedAt
          : (formEntry.draftUpdatedAt ?? formEntry.updatedAt)
      );
      const action = document.createElement("td");
      const actionButton = document.createElement("button");
      actionButton.type = "button";
      actionButton.textContent = dashboardActionLabel(formEntry.status);
      actionButton.addEventListener("click", () => {
        void openDashboardForm(formEntry).catch((error: unknown) => {
          showDashboardOutput(error instanceof Error ? error.message : String(error));
        });
      });
      action.append(actionButton);
      row.append(uid, deceased, formType, status, updated, action);
      body.append(row);
    }
    table.append(body);
    section.append(header, counts, table);
    dashboardUsers.append(section);
  }
};

const refreshUserDashboard = async () => {
  if (!currentUser) {
    showLoginOutput("Login before opening the dashboard.");
    setVisibleStep("login");
    return;
  }
  if (dashboardOutput) dashboardOutput.hidden = true;
  if (dashboardUsers) {
    dashboardUsers.replaceChildren();
    const loading = document.createElement("p");
    loading.className = "dashboard-empty";
    loading.textContent = "Loading dashboard...";
    dashboardUsers.append(loading);
  }
  try {
    const response = await fetchApi(dashboardApiUrl(), { headers: authHeaders() });
    const body = await readJsonResponse<{ ok: boolean; users?: DashboardUserGroup[]; error?: string }>(
      response
    );
    if (!response.ok || !body.ok) {
      throw new Error(body.error ?? `Dashboard could not be loaded. Status: ${response.status}.`);
    }
    renderDashboard(body.users ?? []);
  } catch (error) {
    showDashboardOutput(error instanceof Error ? error.message : String(error));
  }
};

showLogin?.addEventListener("click", () => {
  setVisibleStep("login");
  loginShell?.scrollIntoView({ block: "start" });
});

showProfile?.addEventListener("click", () => {
  void openProfile();
});

logoutUser?.addEventListener("click", () => {
  logoutCurrentUser();
});

adminRegisterUser?.addEventListener("click", () => {
  if (!requireAdminAccess()) return;
  setVisibleStep("registration");
  registrationShell?.scrollIntoView({ block: "start" });
});

adminManageUsers?.addEventListener("click", () => {
  void openUserManagement();
});

adminOpenDataEntry?.addEventListener("click", () => {
  if (!requireDataEntryAccess()) return;
  void refreshDeceasedDropdown();
  setVisibleStep("picker");
  casePickerShell?.scrollIntoView({ block: "start" });
});

adminOpenDashboard?.addEventListener("click", () => {
  setVisibleStep("dashboard");
  dashboardShell?.scrollIntoView({ block: "start" });
  void refreshUserDashboard();
});

showDashboard?.addEventListener("click", () => {
  setVisibleStep("dashboard");
  dashboardShell?.scrollIntoView({ block: "start" });
  void refreshUserDashboard();
});

refreshDashboard?.addEventListener("click", () => {
  void refreshUserDashboard();
});

managedUserSelect?.addEventListener("change", () => {
  populateManagedUserForm(managedUserSelect.value);
  if (userManagementOutput) {
    userManagementOutput.hidden = true;
    userManagementOutput.textContent = "";
  }
});

refreshManagedUsers?.addEventListener("click", () => {
  void refreshManagedUserList().catch((error: unknown) => {
    showUserManagementOutput(error instanceof Error ? error.message : String(error));
  });
});

userManagementForm?.addEventListener("submit", (event) => {
  event.preventDefault();
  void (async () => {
    if (!hasAdminAccess()) {
      showUserManagementOutput("Only admin users can manage user accounts.");
      return;
    }
    const userId = managedUserSelect?.value ?? "";
    if (!userId) {
      showUserManagementOutput("Select a user before saving changes.");
      return;
    }
    const submitButton = userManagementForm.querySelector<HTMLButtonElement>('button[type="submit"]');
    submitButton?.setAttribute("disabled", "true");
    showUserManagementOutput("Saving user changes...");
    try {
      const data = readManagedUserData(userManagementForm);
      const validationError = validateManagedUserData(data);
      if (validationError) {
        showUserManagementOutput(validationError);
        return;
      }
      const user = await updateManagedUser(userId, data);
      if (currentUser?.userId === user.userId) {
        currentUser = user;
        updateAccessControls();
      }
      await refreshManagedUserList(user.userId);
      showUserManagementOutput(
        [
          "User updated successfully",
          `User ID: ${user.userId}`,
          `Name: ${user.name}`,
          `Email: ${user.email}`,
          `Role: ${roleLabel(user.role)}`,
          `Partner site: ${user.partnerSite}`,
          `Site assigned: ${user.siteAssigned}`
        ].join("\n")
      );
    } catch (error) {
      showUserManagementOutput(error instanceof Error ? error.message : String(error));
    } finally {
      submitButton?.removeAttribute("disabled");
    }
  })();
});

passwordChangeForm?.addEventListener("submit", (event) => {
  event.preventDefault();
  if (!currentUser) {
    showProfileOutput("Login before changing your password.");
    return;
  }
  const data = readPasswordChangeData(passwordChangeForm);
  const validationMessage = validatePasswordChangeData(data);
  if (validationMessage) {
    showProfileOutput(validationMessage);
    return;
  }
  void changeCurrentUserPassword({
    currentPassword: data.currentPassword,
    newPassword: data.newPassword
  })
    .then((user) => {
      currentUser = user;
      renderProfileDetails();
      passwordChangeForm.reset();
      showProfileOutput("Password changed successfully.");
    })
    .catch((error: unknown) => {
      showProfileOutput(error instanceof Error ? error.message : String(error));
    });
});

loginForm?.addEventListener("submit", (event) => {
  event.preventDefault();
  void (async () => {
    const submitButton = loginForm.querySelector<HTMLButtonElement>('button[type="submit"]');
    submitButton?.setAttribute("disabled", "true");
    showLoginOutput("Signing in...");
    try {
      const { user, entries } = await loginUser(readLoginData(loginForm));
      const syncedCount = cacheSyncedCaseEntries(entries);
      showLoginOutput(`Login successful. Role: ${user.role === "admin" ? "Admin" : "Data entry"}`);
      if (syncedCount > 0) pickerStatusMessage = `Synced ${syncedCount} entries from the server.`;
      showRolePage(user);
    } catch (error) {
      showLoginOutput(error instanceof Error ? error.message : String(error));
    } finally {
      submitButton?.removeAttribute("disabled");
    }
  })();
});
showRegistration?.addEventListener("click", () => {
  if (!requireAdminAccess()) return;
  setVisibleStep("registration");
  registrationShell?.scrollIntoView({ block: "start" });
});

clearRegistration?.addEventListener("click", () => {
  registrationForm?.reset();
  if (generatedUserIdInput) generatedUserIdInput.value = "";
  if (registrationOutput) {
    registrationOutput.hidden = true;
    registrationOutput.textContent = "";
  }
});

registrationForm?.addEventListener("submit", (event) => {
  event.preventDefault();
  void (async () => {
    const submitButton = registrationForm.querySelector<HTMLButtonElement>('button[type="submit"]');
    submitButton?.setAttribute("disabled", "true");
    showRegistrationOutput("Registering user...");

    try {
      const registrationData = readRegistrationData(registrationForm);
      const validationError = validateRegistrationData(registrationData);
      if (validationError) {
        showRegistrationOutput(validationError);
        return;
      }
      const user = await registerUser(registrationData);
      if (generatedUserIdInput) generatedUserIdInput.value = user.userId;
      showRegistrationOutput(
        [
          "Registration successful",
          `User ID: ${user.userId}`,
          `Name: ${user.name}`,
          `Email: ${user.email}`,
          `Partner site: ${user.partnerSite}`,
          `Site assigned: ${user.siteAssigned}`
        ].join("\n")
      );
      window.alert(`Registration successful. User ID: ${user.userId}`);
    } catch (error) {
      showRegistrationOutput(error instanceof Error ? error.message : String(error));
    } finally {
      submitButton?.removeAttribute("disabled");
    }
  })();
});
deceasedEntrySelect?.addEventListener("change", () => {
  pickerStatusMessage = undefined;
  renderSelectedEntrySummary();
});

newCaseEntry?.addEventListener("click", () => {
  if (!requireDataEntryAccess()) return;
  pickerStatusMessage = undefined;
  clearEntryFormValues();
  setVisibleStep("entry");
  entryShell?.scrollIntoView({ block: "start" });
});

for (const button of startSelectedEntries) {
  button.addEventListener("click", () => {
    void (async () => {
      if (!requireDataEntryAccess()) return;
      const selected = selectedStoredCaseEntry();
      if (!selected) return;
      fillCaseEntryForm(selected.caseEntry);
      await applyCaseEntryToInstrument(selected.caseEntry, selected.whoVaData);
    })().catch((error: unknown) => {
      showEntryOutput(error instanceof Error ? error.message : String(error));
    });
  });
}

clearCaseEntry?.addEventListener("click", clearEntryFormValues);

entryForm?.addEventListener("submit", (event) => {
  event.preventDefault();
  void (async () => {
    const submitButton = entryForm.querySelector<HTMLButtonElement>('button[type="submit"]');
    submitButton?.setAttribute("disabled", "true");
    showEntryOutput("Saving entry to PostgreSQL...");

    try {
      const entry = readCaseEntryData(entryForm);
      const validationError = validateCaseEntryData(entry);
      if (validationError) {
        showEntryOutput(validationError);
        focusDeathPlaceControl();
        return;
      }
      const whoVaData = createWhoVaDataFromCaseEntry(entry);
      const saved = await saveFormEntry({
        uid: entry.uid,
        userId: currentUser?.userId,
        authKey: currentUser?.authKey,
        caseEntry: entry,
        whoVaData,
        status: "case-entry"
      });

      rememberCaseEntry(entry, whoVaData);
      void refreshUserDashboard();
      window.alert("Case data entry submitted successfully.");
      renderDeceasedDropdown();
      if (deceasedEntrySelect) deceasedEntrySelect.value = entry.uid;
      pickerStatusMessage = `Entry saved successfully for ${entry.deceasedFullName}.`;
      renderSelectedEntrySummary();
      currentCaseEntry = undefined;
      currentWhoVaData = undefined;
      setVisibleStep("picker");
      casePickerShell?.scrollIntoView({ block: "start" });
      showEntryOutput({ saved, caseEntry: entry, whoVaData });
    } catch (error) {
      showEntryOutput(error instanceof Error ? error.message : String(error));
    } finally {
      submitButton?.removeAttribute("disabled");
    }
  })();
});

chooseCaseEntry?.addEventListener("click", () => {
  if (!requireDataEntryAccess()) return;
  void refreshDeceasedDropdown();
  setVisibleStep("picker");
  casePickerShell?.scrollIntoView({ block: "start" });
});

editCaseEntry?.addEventListener("click", () => {
  if (!requireDataEntryAccess()) return;
  if (currentCaseEntry) fillCaseEntryForm(currentCaseEntry);
  setVisibleStep("entry");
  entryShell?.scrollIntoView({ block: "start" });
});

form?.addEventListener("who-va-complete", (event) => {
  void (async () => {
    if (!currentCaseEntry || !currentWhoVaData) return;
    if (!currentUser?.userId) {
      showEntryOutput("Login before submitting WHO VA data.");
      return;
    }
    const validationError = validateCaseEntryData(currentCaseEntry);
    if (validationError) {
      showEntryOutput(validationError);
      setVisibleStep("entry");
      fillCaseEntryForm(currentCaseEntry);
      focusDeathPlaceControl();
      return;
    }
    const result = (event as CustomEvent).detail as {
      data: Record<string, unknown>;
      issues: unknown[];
    };
    showEntryOutput("Saving completed WHO VA form to PostgreSQL...");
    try {
      const saved = await saveFormEntry({
        uid: currentCaseEntry.uid,
        userId: currentUser.userId,
        authKey: currentUser.authKey,
        caseEntry: currentCaseEntry,
        whoVaData: currentWhoVaData,
        status: "completed",
        submission: result.data,
        validationIssues: result.issues
      });
      window.alert("WHO VA form submitted successfully.");
      showEntryOutput({ saved, completed: true });
      void refreshUserDashboard();
    } catch (error) {
      showEntryOutput(error instanceof Error ? error.message : String(error));
    }
  })();
});

setDefaultEntryValues();
setVisibleStep("login");
updateAccessControls();
