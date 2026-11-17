/** The phone's narration/documents gallery (src/workspace/media/AttachmentGallery.native.tsx), parity item 10 and 14. */
import React from "react";
import { Text } from "react-native";
import { act, create, type ReactTestRenderer } from "react-test-renderer";

import { CategoryPanel } from "../src/workspace/CategoryPanel";
import { AttachmentGallery } from "../src/workspace/media/AttachmentGallery.native";

const imagenarr = "/api/v1/attachments/0123456789abcdef0123456789abcdef.jpg";
const pdf = "/api/v1/attachments/abcdef0123456789abcdef0123456789.pdf";
const audio = "/api/v1/attachments/11111111111111111111111111111111.amr";
const local = "digitva-local-attachment:imagenarr";

const items = [
  { label: "Narration image", value: imagenarr, flip: false, info: false },
  { label: "Death certificate", value: [pdf], flip: false, info: false },
  { label: "Narration audio", value: { file: audio }, flip: false, info: false },
  { label: "Unsafe", value: "https://external.example/x.jpg", flip: false, info: false },
];

const renderMedia = (path: string) => <Text>{`media:${path}`}</Text>;
const texts = (tree: ReactTestRenderer) => tree.root.findAllByType(Text).map((node) => [node.props.children].flat().join(""));
const press = (tree: ReactTestRenderer, label: string) => act(() => {
  tree.root.find((node) => node.props.accessibilityLabel === label && typeof node.props.onPress === "function").props.onPress();
});
const rotation = (tree: ReactTestRenderer) => tree.root.findByProps({ testID: "attachment-gallery-media" }).props.style.transform[0].rotate;

it("walks the same items as web, in order, including wrapped audio and documents, and skips unsafe values", () => {
  let tree!: ReactTestRenderer;
  act(() => { tree = create(<AttachmentGallery items={items} label="Narration" renderMedia={renderMedia} />); });
  expect(texts(tree)).toContain(`media:${imagenarr}`);
  expect(texts(tree)).toContain("Narration image  1 / 3");
  press(tree, "Next attachment");
  expect(texts(tree)).toContain(`media:${pdf}`);
  press(tree, "Next attachment");
  expect(texts(tree)).toContain(`media:${audio}`);
  expect(texts(tree).some((text) => text.includes("external.example"))).toBe(false);
  press(tree, "Next attachment");
  expect(texts(tree)).toContain(`media:${imagenarr}`);
});

it("rotates only images, per image", () => {
  let tree!: ReactTestRenderer;
  act(() => { tree = create(<AttachmentGallery items={items} label="Narration" renderMedia={renderMedia} />); });
  expect(rotation(tree)).toBe("0deg");
  press(tree, "↷ Rotate right");
  press(tree, "↷ Rotate right");
  expect(rotation(tree)).toBe("180deg");
  press(tree, "↶ Rotate left");
  expect(rotation(tree)).toBe("90deg");
  press(tree, "Next attachment");
  expect(rotation(tree)).toBe("0deg");
  expect(tree.root.findAll((node) => node.props.accessibilityLabel === "↷ Rotate right" || node.props.label === "↷ Rotate right")).toHaveLength(0);
});

it("shows offline draft attachments and renders nothing without a slot or items", () => {
  let tree!: ReactTestRenderer;
  act(() => { tree = create(<AttachmentGallery items={[{ label: "Narration image", value: local, flip: false, info: false }]} label="Narration" renderMedia={renderMedia} />); });
  expect(texts(tree)).toContain(`media:${local}`);
  act(() => { tree.update(<AttachmentGallery items={items} label="Narration" />); });
  expect(tree.toJSON()).toBeNull();
  act(() => { tree.update(<AttachmentGallery items={[]} label="Narration" renderMedia={renderMedia} />); });
  expect(tree.toJSON()).toBeNull();
});

it("CategoryPanel mounts the gallery for media_gallery subcategories only", () => {
  const category = {
    code: "vanarrationanddocuments", label: "Narration", render_mode: "attachments", summary_items: [],
    subcategories: [{ code: "narration", label: "Narration", render_mode: "media_gallery", items }],
  } as never;
  let tree!: ReactTestRenderer;
  act(() => { tree = create(<CategoryPanel category={category} renderMedia={renderMedia} />); });
  expect(tree.root.findAllByType(AttachmentGallery)).toHaveLength(1);
  expect(texts(tree)).toContain(`media:${imagenarr}`);
});
