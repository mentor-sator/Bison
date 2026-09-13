import { promises as fs } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { PNG } from "pngjs";
import pngToIco from "png-to-ico";
import { readPNG, resize } from "png-to-ico/lib/png.js";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.join(here, "..");
const source = path.join(root, "assets", "icon.png");
const ico = path.join(root, "assets", "icon.ico");
const mark = path.join(root, "src", "renderer", "brand", "mark-128.png");

const png = await readPNG(source);

if (png.width !== png.height) {
  throw new Error(`${source} is ${png.width}x${png.height}, expected a square image`);
}

await fs.writeFile(ico, await pngToIco(source));
await fs.writeFile(mark, PNG.sync.write(resize(png, 128, 128)));

console.log(`icon.ico ${(await fs.stat(ico)).size} bytes`);
console.log(`mark-128.png ${(await fs.stat(mark)).size} bytes`);
