/** Plain files are only ever deleted inside the app's private cache, and the playback folder is emptied as a whole. */
const mockDelete = jest.fn();
const mockDirDelete = jest.fn();
jest.mock("expo-file-system", () => ({
  Paths: { cache: { uri: "file:///data/user/0/app/cache/" } },
  File: class { uri: string; exists = true; constructor(uri: string) { this.uri = uri; } delete() { mockDelete(this.uri); } },
  Directory: class { exists = true; delete() { mockDirDelete(); } },
}));

import { inPrivateCache, removeFile, wipeMediaCache } from "../src/mediaFiles";

beforeEach(() => { mockDelete.mockClear(); mockDirDelete.mockClear(); });

it("deletes a cache file and leaves any other path alone", () => {
  removeFile("file:///data/user/0/app/cache/va-media/a.m4a");
  removeFile("file:///storage/emulated/0/DCIM/Camera/IMG_1.jpg"); // the user's own photo from the gallery
  removeFile(undefined);
  expect(mockDelete).toHaveBeenCalledTimes(1);
  expect(mockDelete).toHaveBeenCalledWith("file:///data/user/0/app/cache/va-media/a.m4a");
});

it("empties the playback folder and the picker, manipulator, document and recorder temporaries", () => {
  wipeMediaCache();
  expect(mockDirDelete).toHaveBeenCalledTimes(5);
});

it("accepts a cache path and fails closed on traversal, encoded traversal and other roots", () => {
  const root = "file:///data/user/0/app/cache/";
  expect(inPrivateCache(`${root}ImagePicker/a.jpg`)).toBe(true);
  expect(inPrivateCache(`${root}va-media/../ImagePicker/a.jpg`)).toBe(true);
  expect(inPrivateCache(`${root}../files/answers.db`)).toBe(false);
  expect(inPrivateCache(`${root}va-media/%2e%2e/%2e%2e/files/x`)).toBe(false);
  expect(inPrivateCache(`${root}%zz`)).toBe(false);
  expect(inPrivateCache(root)).toBe(false);
  expect(inPrivateCache("file:///data/user/0/app/files/x")).toBe(false);
  removeFile(`${root}../files/answers.db`);
  expect(mockDelete).not.toHaveBeenCalled();
});
