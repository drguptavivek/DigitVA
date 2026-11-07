/**
 * Document photos on the phone (digitva-lq5m): the blur score, the sharpness service, and the document scanner with
 * its fall-back to the camera.
 */
import { encode } from "jpeg-js";
import { Image, Platform } from "react-native";

const mockReadBytes = jest.fn();
const mockRemoveFile = jest.fn();
const mockWriteCaptureFile = jest.fn((id: string, _base64: string) => `file:///cache/va-media/${id}-scan.jpg`);
const mockResize = jest.fn();
const mockScan = jest.fn();
let mockScannerMissing = false;
jest.mock("expo-audio", () => ({
  RecordingPresets: { HIGH_QUALITY: { extension: ".m4a" } },
  getRecordingPermissionsAsync: jest.fn(),
  requestRecordingPermissionsAsync: jest.fn(),
  setAudioModeAsync: jest.fn(),
  useAudioRecorder: jest.fn(() => ({})),
}));
jest.mock("expo-image-picker", () => ({
  getCameraPermissionsAsync: jest.fn(async () => ({ granted: true })),
  requestCameraPermissionsAsync: jest.fn(),
}));
jest.mock("expo-document-picker", () => ({}));
jest.mock("expo-image-manipulator", () => ({
  SaveFormat: { JPEG: "jpeg" },
  ImageManipulator: {
    manipulate: () => ({
      resize: mockResize,
      renderAsync: async () => ({ saveAsync: async () => ({ uri: "file:///cache/ImageManipulator/sample.jpg" }), release: jest.fn() }),
      release: jest.fn(),
    }),
  },
}));
jest.mock("expo-crypto", () => ({ randomUUID: () => "page" }));
jest.mock("../src/mediaFiles", () => ({
  readBytes: (uri: string) => mockReadBytes(uri),
  removeFile: (uri: string) => mockRemoveFile(uri),
  writeCaptureFile: (id: string, base64: string) => mockWriteCaptureFile(id, base64),
  fileSize: jest.fn(),
  writePlaybackCopy: jest.fn(),
}));
jest.mock("../src/AttachmentAudioPlayer", () => ({ AttachmentAudioPlayer: () => null }));
jest.mock("../src/AttachmentImageViewer", () => ({ AttachmentImageViewer: () => null }));
jest.mock("react-native-document-scanner-plugin", () => ({
  __esModule: true,
  // A build without the native module throws as soon as the module is used (TurboModuleRegistry.getEnforcing).
  get default() {
    if (mockScannerMissing) throw new Error("TurboModuleRegistry.getEnforcing(...): 'DocumentScanner' could not be found");
    return { scanDocument: (options: unknown) => mockScan(options) };
  },
  ResponseType: { Base64: "base64", ImageFilePath: "imageFilePath" },
  ScanDocumentResponseStatus: { Success: "success", Cancel: "cancel" },
}));

import { checkSharpness, scanDocument } from "../src/attachmentServices.native";
import { BLUR_THRESHOLD, jpegSharpness, laplacianVariance } from "../src/sharpness";

const SIZE = 64;

/** A black-and-white checkerboard of 8 px squares: a page of crisp edges. */
function sharpPage(): Uint8Array {
  const gray = new Uint8Array(SIZE * SIZE);
  for (let y = 0; y < SIZE; y++) for (let x = 0; x < SIZE; x++) gray[y * SIZE + x] = ((x >> 3) + (y >> 3)) % 2 ? 255 : 0;
  return gray;
}

/** One pass of a (2r+1)-square box blur. */
function boxBlur(gray: Uint8Array, radius: number): Uint8Array {
  const out = new Uint8Array(gray.length);
  for (let y = 0; y < SIZE; y++) {
    for (let x = 0; x < SIZE; x++) {
      let sum = 0;
      let count = 0;
      for (let dy = -radius; dy <= radius; dy++) {
        for (let dx = -radius; dx <= radius; dx++) {
          const yy = y + dy;
          const xx = x + dx;
          if (yy < 0 || yy >= SIZE || xx < 0 || xx >= SIZE) continue;
          sum += gray[yy * SIZE + xx];
          count++;
        }
      }
      out[y * SIZE + x] = sum / count;
    }
  }
  return out;
}

/** The same page through two 9x9 box blurs (close to a Gaussian): an out-of-focus photo of it. */
function blurred(gray: Uint8Array): Uint8Array {
  return boxBlur(boxBlur(gray, 4), 4);
}

function jpegOf(gray: Uint8Array): Uint8Array {
  const rgba = new Uint8Array(gray.length * 4);
  gray.forEach((value, i) => rgba.set([value, value, value, 255], i * 4));
  return new Uint8Array(encode({ data: rgba, width: SIZE, height: SIZE }, 95).data);
}

describe("blur score", () => {
  it("scores a sharp page far above the threshold and its blurred copy below it", () => {
    const sharp = laplacianVariance(sharpPage(), SIZE, SIZE);
    const soft = laplacianVariance(blurred(sharpPage()), SIZE, SIZE);
    expect(sharp).toBeGreaterThan(BLUR_THRESHOLD * 10);
    expect(soft).toBeLessThan(BLUR_THRESHOLD);
    expect(soft).toBeGreaterThan(0);
  });

  it("scores a flat image and one too small for the kernel as zero", () => {
    expect(laplacianVariance(new Uint8Array(SIZE * SIZE).fill(128), SIZE, SIZE)).toBe(0);
    expect(laplacianVariance(new Uint8Array(4), 2, 2)).toBe(0);
  });

  it("decodes a JPEG on the typed-array path and flags only the blurred one", () => {
    expect(jpegSharpness(jpegOf(sharpPage())).blurry).toBe(false);
    expect(jpegSharpness(jpegOf(blurred(sharpPage())))).toEqual({ score: expect.any(Number), blurry: true });
    expect(() => jpegSharpness(new Uint8Array([1, 2, 3]))).toThrow();
  });
});

describe("checkSharpness", () => {
  beforeEach(() => {
    mockReadBytes.mockReset();
    mockRemoveFile.mockReset();
    mockResize.mockReset();
  });

  it("scores a 512 px copy and deletes the copy", async () => {
    mockReadBytes.mockResolvedValue(jpegOf(blurred(sharpPage())));
    await expect(checkSharpness("file:///cache/ImagePicker/photo.jpg")).resolves.toMatchObject({ blurry: true });
    expect(mockResize).toHaveBeenCalledWith({ width: 512 });
    expect(mockReadBytes).toHaveBeenCalledWith("file:///cache/ImageManipulator/sample.jpg");
    expect(mockRemoveFile).toHaveBeenCalledWith("file:///cache/ImageManipulator/sample.jpg");
  });

  it("still deletes the copy when it cannot be decoded, and rejects (the control then treats it as sharp)", async () => {
    mockReadBytes.mockResolvedValue(new Uint8Array([0, 1]));
    await expect(checkSharpness("file:///cache/ImagePicker/photo.jpg")).rejects.toThrow();
    expect(mockRemoveFile).toHaveBeenCalledWith("file:///cache/ImageManipulator/sample.jpg");
  });
});

describe("scanDocument", () => {
  beforeEach(() => {
    mockScan.mockReset();
    mockRemoveFile.mockReset();
    mockWriteCaptureFile.mockClear();
    Platform.OS = "android";
    (jest.spyOn(Image, "getSize") as jest.Mock).mockResolvedValue({ width: 1200, height: 1600 });
  });

  it("asks for one page as base64, writes it to the app cache, and returns it with its size", async () => {
    mockScan.mockResolvedValue({ status: "success", scannedImages: ["QUJD"] });
    await expect(scanDocument()).resolves.toEqual({
      uri: "file:///cache/va-media/page-scan.jpg",
      name: "scan.jpg",
      mimeType: "image/jpeg",
      width: 1200,
      height: 1600,
    });
    expect(mockScan).toHaveBeenCalledWith({ maxNumDocuments: 1, croppedImageQuality: 90, responseType: "base64" });
    expect(mockWriteCaptureFile).toHaveBeenCalledWith("page", "QUJD");
  });

  it("returns nothing on a cancel, so the control does not fall back to the camera", async () => {
    mockScan.mockResolvedValue({ status: "cancel" });
    await expect(scanDocument()).resolves.toBeUndefined();
    expect(mockWriteCaptureFile).not.toHaveBeenCalled();
  });

  it("rejects when the scanner fails (no Play services), which is the control's cue to use the camera", async () => {
    mockScan.mockRejectedValue(new Error("document scan error"));
    await expect(scanDocument()).rejects.toThrow("document scan error");
  });

  it("deletes the written page when its size cannot be read", async () => {
    mockScan.mockResolvedValue({ status: "success", scannedImages: ["QUJD"] });
    (Image.getSize as jest.Mock).mockRejectedValue(new Error("unreadable"));
    await expect(scanDocument()).rejects.toThrow("unreadable");
    expect(mockRemoveFile).toHaveBeenCalledWith("file:///cache/va-media/page-scan.jpg");
  });

  it("rejects in a build without the scanner module, instead of breaking the services at load", async () => {
    mockScannerMissing = true;
    try {
      await expect(scanDocument()).rejects.toThrow("DocumentScanner");
    } finally {
      mockScannerMissing = false;
    }
  });
});
