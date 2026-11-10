// Lottie light 5.13: SVG DOMLoaded does not wait for images; image errors are swallowed.
async function loadSceneLottie(o) {
  const id = o?.it?.id ?? o?.box?.dataset?.sid ?? o?.box?.id ?? "[без id]";
  const label = `Lottie ${id}`;
  let a, timer, cancelled = false;
  const cleanup = [];
  try {
    const it = o.it;
    if (!o.box || typeof o.box.appendChild !== "function") throw new Error("нет контейнера");
    // Lottie completes/mutates its input, including nested precompositions.
    const data = JSON.parse(typeof it.data === "string" ? it.data : JSON.stringify(it.data));
    const positive = n => Number.isFinite(n) && n > 0;
    if (!data || typeof data !== "object" || Array.isArray(data)
        || typeof data.v !== "string" || !/^\d+\.\d+\.\d+/.test(data.v)
        || !positive(data.w) || !positive(data.h) || !positive(data.fr)
        || !Number.isFinite(data.ip) || !Number.isFinite(data.op)
        || data.op - data.ip < 1 || !Array.isArray(data.layers)
        || (data.assets !== undefined && !Array.isArray(data.assets))) {
      throw new Error("невалидные metadata (v, w, h, fr, ip, op, layers, assets)");
    }
    if (data.segments !== undefined && (!Array.isArray(data.segments) || data.segments.length)) {
      throw new Error("внешние segments не поддерживаются загрузчиком");
    }
    const assets = data.assets || [];
    const byId = new Map();
    for (const asset of assets) {
      if (!asset || typeof asset !== "object" || Array.isArray(asset)
          || (asset.layers !== undefined && !Array.isArray(asset.layers))) {
        throw new Error("невалидные metadata assets");
      }
      byId.set(asset.id, asset);
    }
    for (const layers of [data.layers, ...assets.filter(s => s.layers).map(s => s.layers)]) {
      for (const layer of layers) {
        if (!layer || typeof layer !== "object" || !Number.isInteger(layer.ty)) {
          throw new Error("невалидные metadata layers");
        }
        if (layer.ty === 2 && (!byId.has(layer.refId) || byId.get(layer.refId).layers)) {
          throw new Error(`не найден image asset ${layer.refId}`);
        }
      }
    }
    const base = new URL(it.assetBase || document.baseURI, document.baseURI);
    if (it.assetBase && !base.pathname.endsWith("/")) base.pathname += "/";
    const urls = new Set();
    for (const asset of assets) {
      // Match the vendored ImagePreloader: compositions/footage are not images.
      if (asset.layers || (asset.t && asset.t !== "seq")) continue;
      if (typeof asset.p !== "string" || !asset.p.trim()
          || (asset.u !== undefined && typeof asset.u !== "string")) {
        throw new Error(`невалидный image asset ${asset.id}: u/p`);
      }
      const path = asset.e || /^(?:[a-z][a-z\d+.-]*:|\/)/i.test(asset.p)
        ? asset.p : (asset.u || "") + asset.p;
      asset.p = new URL(path, base).href;
      asset.u = "";
      asset.e = 1; // Both SVG renderer and ImagePreloader use p verbatim.
      urls.add(asset.p);
    }

    // waitForImage has no cancellation API. Own these listeners so a sibling
    // failure/overall timeout can remove every listener and abandon pending images.
    const preload = url => new Promise((resolve, reject) => {
      const im = new Image();
      let settled = false;
      const finish = error => {
        if (settled) return;
        settled = true;
        im.removeEventListener("load", loaded);
        im.removeEventListener("error", failed);
        error ? reject(error) : resolve();
      };
      const loaded = () => finish(im.naturalWidth > 0 && im.naturalHeight > 0
        ? null : new Error(`image ${url}: изображение не декодировано`));
      const failed = () => finish(new Error(`image ${url}: не удалось загрузить или декодировать`));
      cleanup.push(() => {
        if (!settled) {
          finish(new Error(`image ${url}: ожидание отменено`));
          im.removeAttribute("src");
        }
      });
      im.addEventListener("load", loaded);
      im.addEventListener("error", failed);
      im.src = url;
      if (im.complete) loaded();
    });
    const work = async () => {
      await Promise.all([...urls].map(preload));
      if (cancelled) return;
      // Create the real instance first: setupAnimation may emit errors synchronously.
      // This method is verified in the vendored light build; no global API patching.
      a = lottie.loadAnimation({ container: o.box, renderer: "svg", autoplay: false, loop: false,
        rendererSettings: { preserveAspectRatio: it.fit === "cover" ? "xMidYMid slice" : "xMidYMid meet" } });
      await new Promise((resolve, reject) => {
        let domReady = false, imagesReady = urls.size === 0;
        const complete = () => { if (domReady && imagesReady) resolve(); };
        const ready = () => { domReady = true; complete(); };
        const failed = e => reject(new Error(e?.nativeError?.message || e?.message || e?.type || "data_failed"));
        const images = () => {
          // SVG may fetch again after preload. Do not accept Lottie's fallback canvas.
          for (const entry of a.imagePreloader.images) {
            if (urls.has(entry.assetData.p) && entry.img?.localName !== "image") {
              reject(new Error(`image ${entry.assetData.p}: ошибка SVG-загрузки`));
              return;
            }
          }
          imagesReady = true;
          complete();
        };
        for (const [event, fn] of [["DOMLoaded", ready], ["loaded_images", images],
          ["data_failed", failed], ["error", failed]]) {
          a.addEventListener(event, fn);
          cleanup.push(() => a.removeEventListener(event, fn));
        }
        a.setupAnimation(data);
      });
    };
    await Promise.race([
      new Promise((_, reject) => {
        timer = setTimeout(() => reject(new Error("таймаут загрузки 30000 мс")), 30000);
      }),
      work(),
    ]);
    o.a = a;
  } catch (cause) {
    const error = new Error(`${label}: ${cause?.message || cause}`, { cause });
    error.name = "SceneLottieLoadError";
    error.id = id;
    throw error;
  } finally {
    cancelled = true;
    clearTimeout(timer);
    for (const dispose of cleanup) dispose();
    if (a && o.a !== a) a.destroy();
  }
}
