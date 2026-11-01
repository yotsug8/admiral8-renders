/** Decode the licensed launcher KTX2 textures for Blender, preserving UVs.
 * Requires the official Basis Universal transcoder in the local asset folder.
 * Source files stay unchanged; output is a separate standard PNG-textured GLB.
 */
const fs = require('node:fs');
const path = require('node:path');
const sharp = require('sharp');
const base = path.resolve(__dirname, '../_game/external/pudge_tank');
async function main() {
  const BASIS = require(path.join(base, 'basis/basis_transcoder.cjs'));
  const basis = await BASIS({wasmBinary: fs.readFileSync(path.join(base, 'basis/basis_transcoder.wasm'))});
  basis.initializeBasis();
  const raw = fs.readFileSync(path.join(base, 'fps-weapons/fps-weapons-pack-v1.0.0/models/glb/rocket.glb'));
  const jsonSize = raw.readUInt32LE(12);
  const json = JSON.parse(raw.subarray(20, 20+jsonSize).toString());
  const binary = raw.subarray(28+jsonSize);
  const chunks = [binary];
  let offset = binary.length;
  for (const img of json.images) {
    if (img.mimeType !== 'image/ktx2') continue;
    const view = json.bufferViews[img.bufferView];
    const file = new basis.KTX2File(new Uint8Array(binary.subarray(view.byteOffset||0, (view.byteOffset||0)+view.byteLength)));
    if (!file.isValid() || !file.startTranscoding()) throw new Error('Invalid KTX2 texture');
    const width=file.getWidth(), height=file.getHeight();
    const pixels = new Uint8Array(file.getImageTranscodedSizeInBytes(0,0,0,13));
    if (!file.transcodeImage(pixels,0,0,0,13,0,-1,-1)) throw new Error('Texture decode failed');
    const png = await sharp(Buffer.from(pixels), {raw:{width,height,channels:4}}).png().toBuffer();
    const pad = (4-offset%4)%4;
    chunks.push(Buffer.alloc(pad), png);
    offset += pad;
    img.bufferView = json.bufferViews.length;
    json.bufferViews.push({buffer:0, byteOffset:offset, byteLength:png.length});
    img.mimeType = 'image/png';
    offset += png.length;
    file.close(); file.delete();
    console.log(`Decoded ${width}x${height}`);
  }
  for (const tex of json.textures) {
    if (tex.extensions?.KHR_texture_basisu) {
      tex.source = tex.extensions.KHR_texture_basisu.source;
      delete tex.extensions.KHR_texture_basisu;
    }
  }
  for (const key of ['extensionsUsed','extensionsRequired'])
    if (json[key]) json[key]=json[key].filter(x=>x!=='KHR_texture_basisu');
  json.buffers[0].byteLength = offset;
  const data=Buffer.concat([...chunks,Buffer.alloc((4-offset%4)%4)]);
  let meta=Buffer.from(JSON.stringify(json));
  meta=Buffer.concat([meta,Buffer.alloc((4-meta.length%4)%4,32)]);
  const header=Buffer.alloc(20), bh=Buffer.alloc(8);
  header.writeUInt32LE(0x46546c67,0); header.writeUInt32LE(2,4);
  header.writeUInt32LE(28+meta.length+data.length,8);
  header.writeUInt32LE(meta.length,12); header.writeUInt32LE(0x4e4f534a,16);
  bh.writeUInt32LE(data.length,0); bh.writeUInt32LE(0x004e4942,4);
  fs.writeFileSync(path.join(base,'heavy_launcher.glb'),Buffer.concat([header,meta,bh,data]));
}
main().catch(e=>{ console.error(e); process.exitCode=1; });
