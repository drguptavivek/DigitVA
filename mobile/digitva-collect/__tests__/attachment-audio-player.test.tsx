import { act, create } from "react-test-renderer";

const calls: string[] = [];
const mockPlayer = { play: () => calls.push("play"), pause: () => calls.push("pause"), seekTo: async (s: number) => { calls.push(`seek:${s}`); } };
let mockStatus = { playing: true, didJustFinish: false, currentTime: 0, duration: 5 };
jest.mock("expo-audio", () => ({
  useAudioPlayer: () => mockPlayer,
  useAudioPlayerStatus: () => mockStatus,
}));

import { AttachmentAudioPlayer } from "../src/AttachmentAudioPlayer";

describe("AttachmentAudioPlayer", () => {
  it("stops and rewinds at the end of a recording instead of starting it again", () => {
    const element = () => <AttachmentAudioPlayer uri="file:///take.m4a" accessibilityLabel="Narrative" onError={() => undefined} />;
    let tree!: ReturnType<typeof create>;
    act(() => { tree = create(element()); });
    expect(calls).toEqual([]);
    // Android reports the player still playing when it reaches the end.
    mockStatus = { playing: true, didJustFinish: true, currentTime: 5, duration: 5 };
    act(() => { tree.update(element()); });
    expect(calls).toEqual(["pause", "seek:0"]);
    expect(calls).not.toContain("play");
    act(() => tree.unmount());
  });
});
