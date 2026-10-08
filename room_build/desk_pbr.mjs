// Shared PBR maps for the keyboard and the mouse modelled in code (build_keyboard.mjs, build_mouse.mjs). From ambientCG's
// "Plastic 016 A" (CC0 1.0, https://ambientcg.com/a/Plastic016A; its 1K JPG set in <folder>): its fine speckle as the
// micro-texture. Each map is two squares side by side, sampled with u in [0, 0.5) or [0.5, 1): the left a matte, slightly
// worn ABS (roughness ~0.72), the right the same plastic polished by use (~0.42; the keys most pressed, the mouse's wheel).
// glTF's metal/roughness map: roughness in G, metalness in B (0). Plus a soft round blob for contact shadows.
import sharp from "sharp";

export async function plasticMaps(folder, size = 512){
  const rough = await sharp(`${folder}/Plastic016A_1K-JPG_Roughness.jpg`).resize(size, size).greyscale().raw().toBuffer();
  let mean = 0; for (const v of rough) mean += v; mean /= rough.length;
  const half = (m, spread) => { const out = Buffer.alloc(size * size * 3);
    for (let i = 0; i < size * size; i++) { const r = Math.max(0, Math.min(255, Math.round(255 * (m + spread * (rough[i] - mean) / 128))));
      out[3 * i] = 255; out[3 * i + 1] = r; out[3 * i + 2] = 0; } return out; };
  const two = async (a, b) => sharp({create: {width: 2 * size, height: size, channels: 3, background: {r: 0, g: 0, b: 0}}})
    .composite([{input: a, raw: {width: size, height: size, channels: 3}, left: 0, top: 0},
                {input: b, raw: {width: size, height: size, channels: 3}, left: size, top: 0}]).png().toBuffer();
  const mr = await two(half(0.72, 0.10), half(0.42, 0.08));
  const n = await sharp(`${folder}/Plastic016A_1K-JPG_NormalGL.jpg`).resize(size, size).removeAlpha().raw().toBuffer();
  const normal = await two(n, n);
  return {mr: await sharp(mr).webp({quality: 90}).toBuffer(), normal: await sharp(normal).webp({quality: 90}).toBuffer()};
}

// a soft dark blob (alpha falls off from the middle), for a quad laid just over the desk under an object
export async function contactBlob(size = 128){
  const px = Buffer.alloc(size * size * 4);
  for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) {
    const dx = (x + 0.5) / size * 2 - 1, dy = (y + 0.5) / size * 2 - 1, d = Math.max(Math.abs(dx) ** 4 + Math.abs(dy) ** 4, 0) ** 0.25;
    const a = Math.max(0, 1 - d) ** 1.6, i = 4 * (y * size + x);
    px[i] = px[i + 1] = px[i + 2] = 0; px[i + 3] = Math.round(255 * a);
  }
  return sharp(px, {raw: {width: size, height: size, channels: 4}}).png().toBuffer();
}
