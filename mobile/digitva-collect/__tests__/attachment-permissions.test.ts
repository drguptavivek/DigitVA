/** The microphone and camera permission flows: explain first, ask, offer the settings link when refused for good. */
import { Alert, AppState, Linking, Platform } from "react-native";

const mockMic = { get: jest.fn(), request: jest.fn() };
const mockGal = { get: jest.fn(), request: jest.fn() };
const mockCam = { get: jest.fn(), request: jest.fn() };
jest.mock("expo-audio", () => ({
  RecordingPresets: { HIGH_QUALITY: { extension: ".m4a" } },
  getRecordingPermissionsAsync: () => mockMic.get(),
  requestRecordingPermissionsAsync: () => mockMic.request(),
  setAudioModeAsync: jest.fn(),
  useAudioRecorder: jest.fn(() => ({})),
  useAudioPlayer: jest.fn(),
  useAudioPlayerStatus: jest.fn(),
}));
jest.mock("expo-image-picker", () => ({
  getCameraPermissionsAsync: () => mockCam.get(),
  requestCameraPermissionsAsync: () => mockCam.request(),
  getMediaLibraryPermissionsAsync: () => mockGal.get(),
  requestMediaLibraryPermissionsAsync: () => mockGal.request(),
}));
jest.mock("expo-document-picker", () => ({}));
jest.mock("expo-image-manipulator", () => ({ ImageManipulator: {}, SaveFormat: {} }));
jest.mock("expo-crypto", () => ({ randomUUID: () => "id" }));
jest.mock("../src/mediaFiles", () => ({}));
jest.mock("../src/AttachmentAudioPlayer", () => ({ AttachmentAudioPlayer: () => null }));

import { ensureCamera, ensureGallery, ensureMicrophone, setRecordingMode, watchInterruptions } from "../src/attachmentServices.native";

/** Press the button with this label on the dialog the code just opened. */
function press(label: string) {
  const [, , buttons] = (Alert.alert as jest.Mock).mock.calls.at(-1)!;
  buttons.find((button: { text: string }) => button.text === label).onPress?.();
}

beforeEach(() => {
  jest.spyOn(Alert, "alert").mockImplementation(() => undefined);
  jest.spyOn(Linking, "openSettings").mockResolvedValue(undefined);
  (Alert.alert as jest.Mock).mockClear();
  (Linking.openSettings as jest.Mock).mockClear();
  for (const mock of [mockMic.get, mockMic.request, mockCam.get, mockCam.request, mockGal.get, mockGal.request]) mock.mockReset();
});

describe("camera", () => {
  it("explains why before the first request, then asks", async () => {
    mockCam.get.mockResolvedValue({ granted: false, canAskAgain: true });
    mockCam.request.mockResolvedValue({ granted: true });
    const done = ensureCamera();
    await Promise.resolve();
    await Promise.resolve();
    expect((Alert.alert as jest.Mock).mock.calls[0][0]).toBe("Allow the camera?");
    expect(mockCam.request).not.toHaveBeenCalled();
    press("Continue");
    await expect(done).resolves.toBe(true);
    expect(mockCam.request).toHaveBeenCalledTimes(1);
  });

  it("does not ask when the explanation is declined, and asks nothing when already allowed", async () => {
    mockCam.get.mockResolvedValue({ granted: false, canAskAgain: true });
    const done = ensureCamera();
    await Promise.resolve();
    await Promise.resolve();
    press("Cancel");
    await expect(done).resolves.toBe(false);
    expect(mockCam.request).not.toHaveBeenCalled();
    (Alert.alert as jest.Mock).mockClear();
    mockCam.get.mockResolvedValue({ granted: true });
    await expect(ensureCamera()).resolves.toBe(true);
    expect(Alert.alert).not.toHaveBeenCalled();
  });

  it("when refused for good, points to the app's settings", async () => {
    mockCam.get.mockResolvedValue({ granted: false, canAskAgain: false });
    await expect(ensureCamera()).resolves.toBe(false);
    expect((Alert.alert as jest.Mock).mock.calls[0][0]).toBe("Camera is off");
  });
});

describe("audio mode", () => {
  it("recording mode keeps sound on silent; leaving it restores playback mode that still plays on silent", async () => {
    const { setAudioModeAsync } = jest.requireMock("expo-audio");
    await setRecordingMode(true);
    expect(setAudioModeAsync).toHaveBeenLastCalledWith({ allowsRecording: true, playsInSilentMode: true });
    await setRecordingMode(false);
    expect(setAudioModeAsync).toHaveBeenLastCalledWith({ allowsRecording: false, playsInSilentMode: true });
  });

  it("an app state other than active is an interruption; the unsubscribe removes the listener", () => {
    const remove = jest.fn();
    let listener: (state: string) => void = () => {};
    jest.spyOn(AppState, "addEventListener").mockImplementation(((_: string, cb: (state: string) => void) => { listener = cb; return { remove }; }) as never);
    const onInterrupt = jest.fn();
    const stop = watchInterruptions(onInterrupt);
    listener("active");
    expect(onInterrupt).not.toHaveBeenCalled();
    listener("background");
    listener("inactive");
    expect(onInterrupt).toHaveBeenCalledTimes(2);
    stop();
    expect(remove).toHaveBeenCalled();
  });
});

describe("microphone", () => {
  it("explains why before the first request, then asks", async () => {
    mockMic.get.mockResolvedValue({ granted: false, canAskAgain: true });
    mockMic.request.mockResolvedValue({ granted: true, canAskAgain: true });
    const done = ensureMicrophone();
    await Promise.resolve();
    await Promise.resolve();
    expect((Alert.alert as jest.Mock).mock.calls[0][0]).toBe("Allow the microphone?");
    expect(mockMic.request).not.toHaveBeenCalled();
    press("Continue");
    await expect(done).resolves.toBeUndefined();
    expect(mockMic.request).toHaveBeenCalledTimes(1);
  });

  it("asks nothing when already allowed", async () => {
    mockMic.get.mockResolvedValue({ granted: true, canAskAgain: true });
    await expect(ensureMicrophone()).resolves.toBeUndefined();
    expect(Alert.alert).not.toHaveBeenCalled();
    expect(mockMic.request).not.toHaveBeenCalled();
  });

  it("does not ask when the interviewer declines the explanation", async () => {
    mockMic.get.mockResolvedValue({ granted: false, canAskAgain: true });
    const done = ensureMicrophone();
    await Promise.resolve();
    await Promise.resolve();
    press("Cancel");
    await expect(done).rejects.toMatchObject({ name: "NotAllowedError" });
    expect(mockMic.request).not.toHaveBeenCalled();
  });

  it("when refused for good, says so and links to the app's settings", async () => {
    mockMic.get.mockResolvedValue({ granted: false, canAskAgain: false });
    await expect(ensureMicrophone()).rejects.toMatchObject({ name: "NotAllowedError" });
    expect((Alert.alert as jest.Mock).mock.calls[0][0]).toBe("Microphone is off");
    press("Open settings");
    expect(Linking.openSettings).toHaveBeenCalled();
    expect(mockMic.request).not.toHaveBeenCalled();
  });

  it("when the system request is refused, offers the settings link", async () => {
    mockMic.get.mockResolvedValue({ granted: false, canAskAgain: true });
    mockMic.request.mockResolvedValue({ granted: false, canAskAgain: false });
    const done = ensureMicrophone();
    await Promise.resolve();
    await Promise.resolve();
    press("Continue");
    await expect(done).rejects.toMatchObject({ name: "NotAllowedError" });
    expect((Alert.alert as jest.Mock).mock.calls.at(-1)![0]).toBe("Microphone is off");
  });
});

describe("camera", () => {
  it("is true when allowed, and points to settings when refused", async () => {
    mockCam.get.mockResolvedValue({ granted: true });
    await expect(ensureCamera()).resolves.toBe(true);
    mockCam.get.mockResolvedValue({ granted: false, canAskAgain: false });
    await expect(ensureCamera()).resolves.toBe(false);
    expect((Alert.alert as jest.Mock).mock.calls.at(-1)![0]).toBe("Camera is off");
    press("Open settings");
    expect(Linking.openSettings).toHaveBeenCalled();
  });
});

describe("gallery", () => {
  const setPlatform = (os: string, version: number) => {
    Object.defineProperty(Platform, "OS", { configurable: true, get: () => os });
    Object.defineProperty(Platform, "Version", { configurable: true, get: () => version });
  };
  afterEach(() => setPlatform("ios", 17));

  it("on Android 12 explains, then asks; on a refusal for good points to settings", async () => {
    setPlatform("android", 31);
    mockGal.get.mockResolvedValue({ granted: false, canAskAgain: true });
    mockGal.request.mockResolvedValue({ granted: true });
    const done = ensureGallery();
    await Promise.resolve();
    await Promise.resolve();
    expect((Alert.alert as jest.Mock).mock.calls[0][0]).toBe("Allow access to photos?");
    expect(mockGal.request).not.toHaveBeenCalled();
    press("Continue");
    await expect(done).resolves.toBe(true);
    mockGal.get.mockResolvedValue({ granted: false, canAskAgain: false });
    await expect(ensureGallery()).resolves.toBe(false);
    expect((Alert.alert as jest.Mock).mock.calls.at(-1)![0]).toBe("Photos are off");
  });

  it("on Android 13+ and iOS asks nothing (the system photo picker)", async () => {
    setPlatform("android", 33);
    await expect(ensureGallery()).resolves.toBe(true);
    setPlatform("ios", 17);
    await expect(ensureGallery()).resolves.toBe(true);
    expect(mockGal.get).not.toHaveBeenCalled();
    expect(Alert.alert).not.toHaveBeenCalled();
  });
});
