import React from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";

import { AttachmentGallery } from "../src/workspace/media/AttachmentGallery.web";
import { AttachmentMedia } from "../src/workspace/media/AttachmentMedia.web";
import { attachmentMediaExtension, attachmentMediaKind, browserAudioSupported } from "../src/workspace/media/path";

const imageOne = "/api/v1/attachments/0123456789abcdef0123456789abcdef.jpg";
const imageTwo = "/api/v1/attachments/abcdef0123456789abcdef0123456789.webp";
const amr = "/api/v1/attachments/11111111111111111111111111111111.amr";
const validPdf = "/api/v1/attachments/0123456789abcdef0123456789abcdef.pdf";
const unsafe = "https://external.example/attachment.jpg";

const items = [
  { label: "Document one", value: imageOne, flip: false, info: false },
  { label: "Document two", value: { nested: imageTwo }, flip: false, info: false },
  { label: "Narration", value: amr, flip: false, info: false },
  { label: "Unsafe", value: unsafe, flip: false, info: false },
];

it("keeps attachment paths same-origin and recognizes browser image/audio formats", () => {
  expect(attachmentMediaExtension(imageTwo)).toBe("webp");
  expect(attachmentMediaKind(imageTwo)).toBe("image");
  expect(attachmentMediaKind(amr)).toBe("audio");
  expect(browserAudioSupported(amr)).toBe(false);
  expect(attachmentMediaExtension(validPdf)).toBe("pdf");
  expect(attachmentMediaKind(validPdf)).toBeNull();
  expect(attachmentMediaKind(unsafe)).toBeNull();
  expect(attachmentMediaExtension("/api/v1/attachments/legacy/form/file.pdf?download=1")).toBeNull();
});

it("renders a bounded slider with thumbnails, counter, rotation, and full-screen controls", async () => {
  const renderMedia = jest.fn((path: string) => <span>media:{path}</span>);
  let renderer!: ReactTestRenderer;
  await act(async () => {
    renderer = create(<AttachmentGallery
      items={items}
      label="Medical documents"
      workspaceIdentity="coding:case-1"
      renderMedia={renderMedia}
    />);
  });

  expect(renderer.root.findAllByType("img")).toHaveLength(3);
  expect(JSON.stringify(renderer.toJSON())).toContain('"children":["1"," / ","3"]');
  const next = renderer.root.findByProps({ "aria-label": "Next attachment" });
  await act(async () => next.props.onClick());
  expect(JSON.stringify(renderer.toJSON())).toContain('"children":["2"," / ","3"]');
  const rotate = renderer.root.findAllByType("button").find((node) => node.props.children === "↷ Rotate right");
  if (!rotate) throw new Error("rotate control missing");
  await act(async () => rotate.props.onClick());
  expect(JSON.stringify(renderer.toJSON())).toContain("rotate(90deg)");

  const open = renderer.root.findByProps({ "aria-label": "Open Document two full screen" });
  await act(async () => open.props.onClick({ currentTarget: open }));
  expect(renderer.root.findByProps({ role: "dialog" })).toBeDefined();
  expect(renderer.root.findByProps({ "aria-label": "Zoom in" })).toBeDefined();
  expect(renderer.root.findByProps({ "aria-label": "Close full screen" })).toBeDefined();
  expect(renderMedia).not.toHaveBeenCalledWith(amr);
});

it("uses the supplied media boundary for audio and resets selection on workspace identity", async () => {
  const renderMedia = jest.fn((path: string) => <span>media:{path}</span>);
  let renderer!: ReactTestRenderer;
  await act(async () => {
    renderer = create(<AttachmentGallery items={items} label="Documents" workspaceIdentity="coding:case-1" renderMedia={renderMedia} />);
  });
  const next = renderer.root.findByProps({ "aria-label": "Next attachment" });
  await act(async () => {
    next.props.onClick();
    next.props.onClick();
  });
  expect(JSON.stringify(renderer.toJSON())).toContain('"children":["3"," / ","3"]');
  expect(renderMedia).toHaveBeenCalledWith(amr);

  await act(async () => renderer.update(<AttachmentGallery items={items} label="Documents" workspaceIdentity="coding:case-2" renderMedia={renderMedia} />));
  expect(JSON.stringify(renderer.toJSON())).toContain('"children":["1"," / ","3"]');
});

it("does not mount hidden or empty galleries", async () => {
  let hidden!: ReactTestRenderer;
  let empty!: ReactTestRenderer;
  await act(async () => {
    hidden = create(<AttachmentGallery items={items} label="Hidden" visible={false} />);
    empty = create(<AttachmentGallery items={[]} label="Empty" />);
  });
  expect(hidden.toJSON()).toBeNull();
  expect(empty.toJSON()).toBeNull();
});

it("keeps the lightbox on image boundaries, resets zoom, and closes on Escape", async () => {
  let renderer!: ReactTestRenderer;
  await act(async () => {
    renderer = create(<AttachmentGallery items={items} label="Documents" workspaceIdentity="coding:case-1" />);
  });
  const open = renderer.root.findByProps({ "aria-label": "Open Document one full screen" });
  await act(async () => open.props.onClick({ currentTarget: open }));
  const zoom = renderer.root.findByProps({ "aria-label": "Zoom in" });
  await act(async () => zoom.props.onClick());
  expect(JSON.stringify(renderer.toJSON())).toContain('"children":["125","%"]');
  const nextButtons = renderer.root.findAllByProps({ "aria-label": "Next attachment" });
  await act(async () => nextButtons.at(-1)?.props.onClick());
  expect(renderer.root.findByProps({ role: "dialog" })).toBeDefined();
  expect(JSON.stringify(renderer.toJSON())).toContain('"children":["100","%"]');
  expect(renderer.root.findAllByProps({ alt: "Document two" })).toHaveLength(2);
  const followingNext = renderer.root.findAllByProps({ "aria-label": "Next attachment" });
  await act(async () => followingNext.at(-1)?.props.onClick());
  expect(renderer.root.findAllByProps({ alt: "Document one" })).toHaveLength(2);
  if (typeof document !== "undefined") {
    await act(async () => { document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" })); });
    expect(() => renderer.root.findByProps({ role: "dialog" })).toThrow();
  }
});

it("exposes image controls for a default single-image attachment and an AMR download fallback", async () => {
  let imageRenderer!: ReactTestRenderer;
  await act(async () => {
    imageRenderer = create(<AttachmentMedia identity={{ vaSid: "case-1", mode: "view" }} attachmentPath={imageOne} />);
  });
  expect(imageRenderer.root.findByProps({ "aria-label": "Open Attached image full screen" })).toBeDefined();
  expect(imageRenderer.root.findAllByType("button").some((button) => button.props.children === "↶ Rotate left")).toBe(true);

  let audioRenderer!: ReactTestRenderer;
  await act(async () => {
    audioRenderer = create(<AttachmentGallery items={[items[2]]} label="Narration" />);
  });
  expect(audioRenderer.root.findByProps({ download: "11111111111111111111111111111111.amr" })).toBeDefined();
});

it("renders validated PDFs as same-origin downloads in both default and grouped views", async () => {
  let mediaRenderer!: ReactTestRenderer;
  await act(async () => {
    mediaRenderer = create(<AttachmentMedia identity={{ vaSid: "case-1", mode: "view" }} attachmentPath={validPdf} />);
  });
  expect(mediaRenderer.root.findByProps({ href: validPdf, download: "0123456789abcdef0123456789abcdef.pdf" })).toBeDefined();

  let galleryRenderer!: ReactTestRenderer;
  await act(async () => {
    galleryRenderer = create(<AttachmentGallery items={[{ label: "Medical record", value: validPdf, flip: false, info: false }, { label: "Photo", value: imageOne, flip: false, info: false }]} label="Documents" />);
  });
  expect(galleryRenderer.root.findByProps({ href: validPdf, download: "0123456789abcdef0123456789abcdef.pdf" })).toBeDefined();
  expect(JSON.stringify(galleryRenderer.toJSON())).toContain("PDF");
});

it("announces when bounded attachment extraction truncates nested data", async () => {
  const manyItems = Array.from({ length: 301 }, (_, index) => ({
    label: `Document ${index + 1}`,
    value: `/api/v1/attachments/${String(index).padStart(32, "0")}.jpg`,
    flip: false,
    info: false,
  }));
  let renderer!: ReactTestRenderer;
  await act(async () => {
    renderer = create(<AttachmentGallery items={manyItems} label="Documents" />);
  });
  expect(renderer.root.findByProps({ role: "status" })).toBeDefined();
  expect(JSON.stringify(renderer.toJSON())).toContain("safe display limit");
});

it("pauses browser audio through the callback ref before detachment", async () => {
  let renderer!: ReactTestRenderer;
  await act(async () => {
    renderer = create(<AttachmentMedia identity={{ vaSid: "case-1", mode: "view" }} attachmentPath="/api/v1/attachments/0123456789abcdef0123456789abcdef.mp3" />);
  });
  const audio = renderer.root.findByType("audio");
  const setRef = (audio.props as { ref?: (element: HTMLAudioElement | null) => void }).ref;
  if (!setRef) throw new Error("audio callback ref missing");
  const pause = jest.fn();
  await act(async () => {
    setRef({ pause } as unknown as HTMLAudioElement);
    setRef(null);
  });
  expect(pause).toHaveBeenCalledTimes(1);
});
