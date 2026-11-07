/**
 * Photo sharpness, on the phone only (docs/policy/phone-attachments.md, "Document photos"): the variance of the
 * Laplacian of a grey copy about 512 px wide. A sharp page has strong edges and scores high; a shaken or
 * out-of-focus one scores low. Pure JS (jpeg-js, typed arrays only: Hermes has no Buffer).
 */
import { decode } from "jpeg-js";

/** The width the photo is scaled to before scoring, so the score does not depend on the camera's resolution. */
export const SHARPNESS_SAMPLE_WIDTH = 512;

// ponytail: a first guess (the usual 100 for a 512 px copy); calibrate on real phones with field photos of
// written narratives and certificates before relying on it. Too high nags about sharp photos; too low misses blur.
export const BLUR_THRESHOLD = 100;

/** Variance of the 4-neighbour Laplacian over the interior pixels of a grey image (one value per pixel). */
export function laplacianVariance(gray: ArrayLike<number>, width: number, height: number): number {
  if (width < 3 || height < 3) return 0;
  let sum = 0;
  let sumOfSquares = 0;
  for (let y = 1; y < height - 1; y++) {
    for (let x = 1; x < width - 1; x++) {
      const i = y * width + x;
      const edge = gray[i - width] + gray[i + width] + gray[i - 1] + gray[i + 1] - 4 * gray[i];
      sum += edge;
      sumOfSquares += edge * edge;
    }
  }
  const count = (width - 2) * (height - 2);
  const mean = sum / count;
  return sumOfSquares / count - mean * mean;
}

/** Rec. 601 luma of RGB pixels (3 bytes each). */
export function toGray(rgb: Uint8Array, width: number, height: number): Uint8Array {
  const gray = new Uint8Array(width * height);
  for (let i = 0; i < gray.length; i++) {
    gray[i] = (rgb[i * 3] * 299 + rgb[i * 3 + 1] * 587 + rgb[i * 3 + 2] * 114) / 1000;
  }
  return gray;
}

/** The sharpness of a small JPEG and whether it is below the threshold. Throws on a file that is not a JPEG. */
export function jpegSharpness(bytes: Uint8Array): { score: number; blurry: boolean } {
  // 2 MP bounds the work: the caller passes a ~512 px copy, never the camera frame.
  const image = decode(bytes, { useTArray: true, formatAsRGBA: false, maxResolutionInMP: 2 });
  const score = laplacianVariance(toGray(image.data, image.width, image.height), image.width, image.height);
  return { score, blurry: score < BLUR_THRESHOLD };
}
