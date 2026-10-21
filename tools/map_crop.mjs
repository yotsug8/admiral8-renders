// Вырезать кусок карты: оставить узлы, чьи габариты пересекают квадрат [cx±r, cz±r], убрать лишнее, текстуры — внутрь GLB
import { NodeIO, getBounds } from '@gltf-transform/core';
import { prune, dedup } from '@gltf-transform/functions';
const [src, out, cx, cz, r] = [process.argv[2], process.argv[3], +process.argv[4], +process.argv[5], +process.argv[6]];
const io = new NodeIO(), doc = await io.read(src), root = doc.getRoot();
let kept = 0, drop = 0;
for (const n of root.listNodes()) {
  if (!n.getMesh()) continue;
  const b = getBounds(n);
  const hit = b.max[0] > cx - r && b.min[0] < cx + r && b.max[2] > cz - r && b.min[2] < cz + r;
  if (hit) kept++; else { n.setMesh(null); drop++; }
}
await doc.transform(prune(), dedup());
await io.write(out, doc);
console.log('оставлено', kept, 'убрано', drop);
