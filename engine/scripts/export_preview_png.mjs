import fs from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { chromium } from 'playwright';

const [htmlPath, pngPath] = process.argv.slice(2);
if (!htmlPath || !pngPath) throw new Error('usage: export_preview_png.mjs HTML PNG');
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 1 });
  await page.goto(pathToFileURL(path.resolve(htmlPath)).href, { waitUntil: 'load' });
  await page.evaluate(async () => { if (document.fonts?.ready) await document.fonts.ready; });
  const downloadPromise = page.waitForEvent('download', { timeout: 30000 });
  await page.locator('#download-png').click();
  const download = await downloadPromise;
  await download.saveAs(path.resolve(pngPath));
} finally {
  await browser.close();
}
const header = await fs.readFile(path.resolve(pngPath));
if (header.length < 24 || header.readUInt32BE(0) !== 0x89504e47) throw new Error('PNG export did not produce a PNG');
const width = header.readUInt32BE(16), height = header.readUInt32BE(20);
if (width < 2480 || height < 3508) throw new Error(`PNG dimensions below contract: ${width}x${height}`);
console.log(JSON.stringify({ status: 'png_ready', width, height }));
