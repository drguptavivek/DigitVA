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

  it("lets its row keep room for the engine's Delete button beside it (digitva-j9vk)", () => {
    // The engine puts the player and the Delete IconButton in one row. The seek track is flex: 1, so a
    // player that cannot shrink takes the whole row and squeezes Delete to zero width.
    let tree!: ReturnType<typeof create>;
    act(() => { tree = create(<AttachmentAudioPlayer uri="file:///take.m4a" accessibilityLabel="Narrative" onError={() => undefined} />); });
    const [root] = tree.root.findAll((node) => node.props.accessibilityLabel === "Narrative" && node.props.style !== undefined);
    expect(root).toBeDefined();
    expect(root.props.style).toMatchObject({ flexDirection: "row", flexShrink: 1, minWidth: 0 });
    act(() => tree.unmount());
  });
});
