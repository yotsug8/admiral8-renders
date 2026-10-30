// Универсальные сцены: сегмент описывается в JSON списком элементов и таймлайном эффектов.
// Движение — на GSAP: у каждой сцены свой таймлайн на паузе, рендер перематывает его в нужное время кадра.
// Справка по полям — SCENES.md.
gsap.registerPlugin(SplitText, CustomEase);
gsap.ticker.lagSmoothing(0);

const SCN = (() => {
  // Цветовые токены → CSS-переменные; всё прочее (#hex, rgba) — как есть
  const TOK = ["acc", "ink", "red", "mint", "gold", "rad", "dire", "paper", "navy", "dark"];
  const col = c => (c && TOK.includes(c) ? `var(--${c})` : c);
  // Текст: «|» — перенос строки, *слово* — акцент, _слово_ — маркер-подчёркивание
  const rich = s => String(s).split("|").map(l => `<span class="ln"><span>${l
    .replace(/\*(.+?)\*/g, "<em>$1</em>").replace(/_(.+?)_/g, '<span class="mk">$1</span>')}</span></span>`).join("");

  // ---------- построение элементов ----------
  function build(g) {
    const S = g.s.scene, root = $("div", "scn", g.el);
    const bg = $("div", "bgl", root);
    if (S.bg) {
      if (S.bg.grad) bg.style.background = `linear-gradient(180deg, ${S.bg.grad.map(col).join(", ")})`;
      if (S.bg.color) bg.style.background = col(S.bg.color);
      if (S.bg.tex) bg.classList.add("tx-" + S.bg.tex);
    }
    g.parts.lines = [];                       // сцена рисует заголовки сама
    g.sc = { root, items: {}, anims: [], vids: [], lots: [], models: [], stages: [], list: [] };
    (S.items || []).forEach((it, k) => add(g, it, root, it.id || "i" + k));
  }

  function add(g, it, parent, id) {
    const box = $("div", "si", parent);
    box.dataset.sid = id;
    const css = box.style;
    const set = (k, v, u = "px") => { if (v != null) css[k] = typeof v === "number" ? v + u : v; };
    set("left", it.x); set("top", it.y); set("width", it.w); set("height", it.h);
    if (it.z != null) css.zIndex = it.z;
    if (it.rot) css.transform = `rotate(${it.rot}deg)`;
    if (it.color) css.color = col(it.color);
    if (it.bg) css.background = col(it.bg);
    if (it.radius != null) css.borderRadius = it.radius + "px";
    if (it.border) css.setProperty("--bc", col(it.border));
    if (it.tex) box.classList.add("tx-" + it.tex);
    if (it.tint) {            // оттенок: под шумом у процедурных текстур, поверх фото у фото-текстур
      const gr = `linear-gradient(180deg, ${[].concat(it.tint).map(col).join(", ")})`;
      css.setProperty("--tb", gr); css.setProperty("--tov", gr);
    }
    (it.frame ? [].concat(it.frame) : []).forEach(f => box.classList.add("fr-" + f));
    if (it.cls) box.className += " " + it.cls;
    if (it.pad != null) css.padding = it.pad + "px";
    const T = it.type || "text";
    if (T === "text") {
      box.classList.add("sx");
      if (it.font === "body") box.classList.add("body");
      if (it.font === "cap") box.classList.add("cap");
      if (it.align) box.classList.add(it.align);
      if (it.size) css.fontSize = it.size + "px";
      if (it.lh) css.lineHeight = it.lh;
      if (it.acc) css.setProperty("--acc", col(it.acc));
      box.innerHTML = rich(it.text);
    } else if (T === "chip") {
      box.classList.add("chip"); box.textContent = it.text;
      if (it.size) css.fontSize = it.size + "px";
      if (it.fill) css.background = col(it.fill);
    } else if (T === "stamp") {
      box.classList.add("stamp2"); box.textContent = it.text;
      if (it.size) css.fontSize = it.size + "px";
      if (it.color) { css.borderColor = col(it.color); css.outlineColor = col(it.color); }
    } else if (T === "number") {
      box.classList.add("num"); box.textContent = it.value;
      if (it.size) css.fontSize = it.size + "px";
    } else if (T === "img") {
      box.classList.add("pic"); if (it.fit === "contain") box.classList.add("contain");
      const im = $("img", null, box); im.src = it.src;
      if (it.pos) im.style.objectPosition = it.pos;
    } else if (T === "hero") {
      box.classList.add("hero2");
      const im = $("img", "hero", box); im.src = it.src;   // класс hero — аудит не даст положить на него текст
    } else if (T === "card") {
      box.classList.add("card2");
      const im = $("img", it.icon ? "ic" : null, box); im.src = it.src;
      if (it.label) $("div", "lbl", box).textContent = it.label;
      if (it.stamp) $("div", "stmp", box).textContent = it.stamp;
    } else if (T === "anim") {
      box.classList.add("animbox");
      g.sc.anims.push({ A: makeAnim(box, it.anim), box, it });
    } else if (T === "video") {
      // Клип: кадры заранее нарезаны под размер элемента (video.py), рисуются на холсте по времени сцены
      box.classList.add("vidbox");
      const pre = document.getElementById("preload");
      g.sc.vids.push({ cv: $("canvas", null, box), it, imgs: it.clip.frames.map(src => { const im = $("img", null, pre); im.src = src; return im; }) });
    } else if (T === "stage") {
      box.classList.add("modelbox");
      g.sc.stages.push({ box, it });
    } else if (T === "model") {
      box.classList.add("modelbox");
      g.sc.models.push({ box, it });
    } else if (T === "lottie") {
      box.classList.add("lotbox");
      g.sc.lots.push({ box, it });
    } else if (T === "shape") {
      box.innerHTML = shape(it);
    } else if (T === "row" || T === "col" || T === "panel") {
      // Контейнеры: row/col раскладывают детей поровну с зазором, panel — свободные координаты внутри
      const kids = it.items || [], gap = it.gap ?? 14, n = kids.length;
      kids.forEach((c, k) => {
        const cc = Object.assign({}, it.child || {}, c);
        if (T === "row") Object.assign(cc, { x: k * ((it.w - gap * (n - 1)) / n + gap), y: 0, w: (it.w - gap * (n - 1)) / n, h: cc.h ?? it.h });
        if (T === "col") Object.assign(cc, { x: 0, y: k * ((it.h - gap * (n - 1)) / n + gap), w: cc.w ?? it.w, h: (it.h - gap * (n - 1)) / n });
        add(g, cc, box, c.id || `${id}.${k}`);
      });
    }
    g.sc.items[id] = box;
    g.sc.list.push({ id, it, box });
    return box;
  }

  // Рисованные элементы интерфейса: стрелка, линия, скобка, разделитель
  function shape(it) {
    const w = it.w || 200, h = it.h || 60, c = col(it.color || "acc"), sw = it.stroke || 10;
    const d = {
      arrow: `M${sw} ${h / 2} H${w - sw * 3} M${w - sw * 4} ${sw} L${w - sw} ${h / 2} L${w - sw * 4} ${h - sw}`,
      line: `M0 ${h / 2} H${w}`,
      bracket: `M${sw} ${sw} V${h - sw} H${w - sw} V${sw}`,
      zig: Array.from({ length: Math.ceil(w / 40) + 1 }, (_, k) => `${k ? "L" : "M"}${k * 40} ${k % 2 ? sw : h - sw}`).join(" "),
    }[it.kind || "arrow"];
    return `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" style="overflow:visible"><path d="${d}" fill="none" stroke="${c}" stroke-width="${sw}" stroke-linecap="round" stroke-linejoin="round" pathLength="1" class="shp"/></svg>`;
  }

  // ---------- время: число, метка из озвучки или «метка+0.3» ----------
  function when(g, at) {
    if (at == null) return 0;
    if (typeof at === "number") return at;
    const m = String(at).match(/^([^+\-]+)([+\-][\d.]+)?$/);
    const base = (g.s.scene.at || {})[m[1]];
    return (base == null ? 0 : base) + (m[2] ? parseFloat(m[2]) : 0);
  }
  // Цели: "id", "id.*" (все дети контейнера), "id em" (CSS внутри элемента), "@all" (вся сцена)
  function pick(g, sel) {
    if (sel === "@all") return [g.sc.root];
    const [id, ...rest] = sel.split(" "), inner = rest.join(" ");
    let els = id.endsWith(".*") ? g.sc.list.filter(o => o.id.startsWith(id.slice(0, -1)) && !o.id.slice(id.length - 1).includes(".")).map(o => o.box)
                                : [g.sc.items[id]].filter(Boolean);
    if (inner) els = els.flatMap(e => [...e.querySelectorAll(inner)]);
    return els;
  }

  // ---------- пресеты появления (выбор и длительности — по DESIGN.md: вход ease-out, лесенка ≤ 0,5 с) ----------
  const IN = {
    fade:   (tl, e, t, o) => tl.fromTo(e, { opacity: 0 }, { opacity: 1, duration: o.dur || 0.35, ease: "power1.out", stagger: o.stagger }, t),
    rise:   (tl, e, t, o) => tl.fromTo(e, { opacity: 0, y: o.dist || 70 }, { opacity: 1, y: 0, duration: o.dur || 0.5, ease: "back.out(1.4)", stagger: o.stagger }, t),
    drop:   (tl, e, t, o) => tl.fromTo(e, { opacity: 0, y: -(o.dist || 90), rotation: -5 }, { opacity: 1, y: 0, rotation: 0, duration: o.dur || 0.5, ease: "back.out(1.6)", stagger: o.stagger }, t),
    pop:    (tl, e, t, o) => tl.fromTo(e, { opacity: 0, scale: 0.55 }, { opacity: 1, scale: 1, duration: o.dur || 0.4, ease: "back.out(1.7)", stagger: o.stagger }, t),
    slam:   (tl, e, t, o) => tl.fromTo(e, { opacity: 0, scale: o.from || 1.8 }, { opacity: 1, scale: 1, duration: o.dur || 0.28, ease: "power4.in", stagger: o.stagger }, t),
    left:   (tl, e, t, o) => tl.fromTo(e, { opacity: 0, x: -(o.dist || 220) }, { opacity: 1, x: 0, duration: o.dur || 0.5, ease: "power3.out", stagger: o.stagger }, t),
    right:  (tl, e, t, o) => tl.fromTo(e, { opacity: 0, x: o.dist || 220 }, { opacity: 1, x: 0, duration: o.dur || 0.5, ease: "power3.out", stagger: o.stagger }, t),
    wipe:   (tl, e, t, o) => tl.fromTo(e, { clipPath: "inset(0 100% 0 0)" }, { clipPath: "inset(0 0% 0 0)", duration: o.dur || 0.5, ease: "power3.inOut", stagger: o.stagger }, t),
    iris:   (tl, e, t, o) => tl.fromTo(e, { clipPath: "inset(50% 50% 50% 50% round 20px)" }, { clipPath: "inset(0% 0% 0% 0% round 20px)", duration: o.dur || 0.55, ease: "power3.out", stagger: o.stagger }, t),
    stamp:  (tl, e, t, o) => tl.fromTo(e, { opacity: 0, scale: 2.3, rotation: (o.rot ?? -10) - 8 }, { opacity: 1, scale: 1, rotation: o.rot ?? -10, duration: o.dur || 0.24, ease: "power4.in", stagger: o.stagger }, t),
    draw:   (tl, e, t, o) => tl.fromTo(e.flatMap(x => [...x.querySelectorAll(".shp")]), { strokeDasharray: 1, strokeDashoffset: 1 }, { strokeDashoffset: 0, duration: o.dur || 0.5, ease: "power2.inOut", stagger: o.stagger }, t),
    // Текст: строки из-под маски, буквы, печать
    lines:  (tl, e, t, o) => tl.fromTo(e.flatMap(x => [...x.querySelectorAll(".ln > span")]), { yPercent: 110 }, { yPercent: 0, duration: o.dur || 0.45, ease: "power3.out", stagger: o.stagger ?? 0.09 }, t),
    chars:  (tl, e, t, o) => tl.fromTo(chars(e), { opacity: 0, y: 40, rotation: 8 }, { opacity: 1, y: 0, rotation: 0, duration: o.dur || 0.35, ease: "back.out(1.6)", stagger: o.stagger ?? 0.025 }, t),
    type:   (tl, e, t, o) => tl.fromTo(chars(e), { opacity: 0 }, { opacity: 1, duration: 0.01, stagger: o.stagger ?? 0.045 }, t),
    none:   tl => tl,
  };
  // ---------- пресеты действий ----------
  const FX = {
    pulse:  (tl, e, t, o) => tl.to(e, { scale: o.to || 1.08, duration: 0.14, ease: "power2.out", yoyo: true, repeat: 1, stagger: o.stagger }, t),
    shake:  (tl, e, t, o) => tl.to(e, { keyframes: [{ x: -14 }, { x: 12 }, { x: -8 }, { x: 5 }, { x: 0 }], duration: o.dur || 0.3, ease: "none", stagger: o.stagger }, t),
    jump:   (tl, e, t, o) => tl.to(chars(e), { keyframes: [{ y: -(o.dist || 26), duration: 0.16, ease: "power2.out" }, { y: 0, duration: 0.32, ease: "back.out(2)" }], stagger: o.stagger ?? 0.045 }, t),
    // фильтр — всегда из явного начального значения: из «none» GSAP интерполирует через brightness(0), и кадр чернеет
    gray:   (tl, e, t, o) => tl.fromTo(e, { filter: "grayscale(0) brightness(1)" }, { filter: "grayscale(1) brightness(.55)", duration: o.dur || 0.3, ease: "power2.in", stagger: o.stagger }, t),
    color:  (tl, e, t, o) => tl.fromTo(e, { filter: "grayscale(1) brightness(.55)" }, { filter: "grayscale(0) brightness(1)", duration: o.dur || 0.3, stagger: o.stagger }, t),
    dim:    (tl, e, t, o) => tl.to(e, { opacity: o.to ?? 0.35, duration: o.dur || 0.3, stagger: o.stagger }, t),
    show:   (tl, e, t, o) => tl.to(e, { opacity: 1, duration: o.dur || 0.3, stagger: o.stagger }, t),
    hide:   (tl, e, t, o) => tl.to(e, { opacity: 0, duration: o.dur || 0.25, ease: "power2.in", stagger: o.stagger }, t),
    out:    (tl, e, t, o) => tl.to(e, { opacity: 0, y: -(o.dist || 60), duration: o.dur || 0.3, ease: "power3.in", stagger: o.stagger }, t),
    move:   (tl, e, t, o) => tl.to(e, { x: o.x || 0, y: o.y || 0, scale: o.scale ?? 1, rotation: o.rot || 0, duration: o.dur || 0.6, ease: o.ease || "power3.inOut", stagger: o.stagger }, t),
    mark:   (tl, e, t, o) => tl.fromTo(e.flatMap(x => [...x.querySelectorAll(".mk")]), { "--mk": 0 }, { "--mk": 1, duration: o.dur || 0.35, ease: "power2.out", stagger: o.stagger ?? 0.1 }, t),
    stamps: (tl, e, t, o) => IN.stamp(tl, e.flatMap(x => [...x.querySelectorAll(".stmp")]), t, Object.assign({ rot: -8, stagger: 0.08 }, o)),
    count:  (tl, e, t, o) => e.forEach(el => {             // число набегает от 0; формат как в исходном значении (пробелы, запятая, «:»)
      const txt = el.textContent, m = txt.match(/^(\D*)([\d\s]+)(?:([,:.])(\d+))?(.*)$/);
      if (!m) return;
      const sep = m[3], int = parseInt(m[2].replace(/\s/g, "")), frac = m[4], o2 = { v: 0 };
      const total = sep === ":" ? int * 60 + parseInt(frac) : parseFloat(int + (frac ? "." + frac : ""));
      const fmt = v => {
        if (sep === ":") { const mm = Math.floor(v / 60), ss = Math.floor(v % 60); return m[1] + String(mm).padStart(m[2].length, "0") + ":" + String(ss).padStart(2, "0") + m[5]; }
        const s = frac ? v.toFixed(frac.length).split(".") : [String(Math.round(v))];
        return m[1] + s[0].replace(/\B(?=(\d{3})+(?!\d))/g, " ") + (s[1] ? sep + s[1] : "") + m[5];
      };
      tl.fromTo(o2, { v: 0 }, { v: total, duration: o.dur || 1.0, ease: o.ease || "power2.out", onUpdate: () => { el.textContent = fmt(o2.v); } }, t);
    }),
    swap:   (tl, e, t, o) => e.forEach(el => {              // смена текста с переворотом (текст меняется на ребре)
      const old = el.innerHTML, p = { v: 0 };
      tl.to(el, { rotationX: 90, duration: 0.14, ease: "power2.in" }, t)
        .fromTo(p, { v: 0 }, { v: 1, duration: 0.34, ease: "none", onUpdate: () => { el.innerHTML = p.v < 0.41 ? old : rich(o.text); } }, t)
        .to(el, { rotationX: 0, duration: 0.2, ease: "back.out(2)" }, t + 0.14);
    }),
  };
  function chars(els) {
    return els.flatMap(e => { if (!e._split) e._split = new SplitText(e.querySelectorAll("em").length && e.dataset.split !== "all" ? e.querySelectorAll("em") : e, { type: "words,chars" }); return e._split.chars; });   // words — чтобы слово не рвалось при переносе
  }

  // ---------- 3D-модели героев: GLB из файлов игры (tools/dota_export.py), части привязываются к скелету героя ----------
  // Герой из набора GLB (база + части): части привязываются к скелету героя по именам костей
  async function hero(glbs, animName) {
    const { THREE, GLTFLoader } = window.T3, L = new GLTFLoader();
    const parse = b64 => new Promise((ok, no) => {
      const bin = Uint8Array.from(atob(b64), c => c.charCodeAt(0)).buffer;
      L.parse(bin, "", ok, no);
    });
    const [base, ...parts] = await Promise.all(glbs.map(parse));
    const root = new THREE.Group(); root.add(base.scene);
    const bones = {}; base.scene.traverse(o => { if (o.isBone) bones[o.name] = o; });
    for (const p of parts) {
      p.scene.traverse(o => {
        if (!o.isSkinnedMesh) return;
        const bs = o.skeleton.bones.map(bn => {
          if (bones[bn.name]) return bones[bn.name];
          const par = bn.parent && bones[bn.parent.name];       // кости меха и ткани — к родителю героя
          if (par && bn.parent !== par) par.add(bn);
          return bn;
        });
        o.bind(new THREE.Skeleton(bs, o.skeleton.boneInverses), o.bindMatrix);
      });
      root.add(p.scene);
    }
    const mixer = new THREE.AnimationMixer(base.scene);
    const clip = base.animations.find(a => a.name === animName) || base.animations[0];
    if (clip) mixer.clipAction(clip).play();
    mixer.setTime(0);
    const rootBone = base.scene.getObjectByProperty("isBone", true), r0 = rootBone ? rootBone.position.clone() : null;
    return { root, base, mixer, clip, rootBone, r0, names: base.animations.map(a => a.name) };
  }

  async function load(g) {
    for (const st of g.sc.stages) await stage(st);
    for (const m of g.sc.models) {
      const { THREE } = window.T3, it = m.it;
      const { root, mixer, clip, rootBone, r0 } = await hero(it.glb, it.anim);
      const W = it.w, H = it.h;
      const r = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
      r.setPixelRatio(1); r.setSize(W, H); r.outputColorSpace = THREE.SRGBColorSpace;
      m.box.appendChild(r.domElement);
      const sc = new THREE.Scene();
      sc.add(new THREE.HemisphereLight(0xdfe8ff, 0x2a2420, it.ambient ?? 1.5));
      const key = new THREE.DirectionalLight(0xffffff, it.key ?? 2.4); key.position.set(2, 3, 2.6); sc.add(key);
      const rim = new THREE.DirectionalLight(new THREE.Color(it.rim || "#5fd4c4"), it.rim_power ?? 2.2); rim.position.set(-2.5, 1.5, -2); sc.add(rim);
      sc.add(root);
      root.rotation.y = (it.yaw ?? 25) * Math.PI / 180;
      // Камера: кадр по габаритам героя в начале анимации, дальше не двигается
      root.updateMatrixWorld(true);
      const bb = new THREE.Box3().setFromObject(root, true), c = bb.getCenter(new THREE.Vector3()), sz = bb.getSize(new THREE.Vector3());
      const fov = it.fov || 28, cam = new THREE.PerspectiveCamera(fov, W / H, 0.01, 1000);
      const fit = Math.max(sz.y, sz.x * H / W) / (2 * Math.tan(fov * Math.PI / 360)) * (it.zoom ? 1 / it.zoom : 1.08);
      cam.position.set(c.x, c.y + sz.y * (it.tilt ?? 0.04), c.z + fit + sz.z / 2); cam.lookAt(c.x, c.y, c.z);
      Object.assign(m, { r, sc, cam, mixer, rootBone, r0, clip });
    }
  }

  // ---------- 3D-площадка: несколько героев, вода с кругами, берега, движение камеры ----------
  // it.heroes: { ключ: [GLB…] }, it.actors: [{ hero, anim, x, z, y, yaw, speed, phase }], it.water: { level, color }, it.cam: { pos, look, to: { pos, look } }
  async function stage(st) {
    const { THREE } = window.T3, it = st.it, W = it.w, H = it.h;
    const r = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
    r.setPixelRatio(1); r.setSize(W, H); r.outputColorSpace = THREE.SRGBColorSpace;
    st.box.appendChild(r.domElement);
    const sc = new THREE.Scene();
    const sky = new THREE.Color(it.sky || "#1d3a3a");
    sc.background = sky; sc.fog = new THREE.Fog(sky, it.fog_near ?? 18, it.fog_far ?? 60);
    sc.add(new THREE.HemisphereLight(0xe6f0ff, 0x2a3020, it.ambient ?? 1.4));
    const sun = new THREE.DirectionalLight(new THREE.Color(it.sun || "#fff1d6"), it.key ?? 2.6); sun.position.set(6, 10, 6); sc.add(sun);
    const rim = new THREE.DirectionalLight(new THREE.Color(it.rim || "#5fd4c4"), it.rim_power ?? 1.6); rim.position.set(-6, 4, -6); sc.add(rim);
    const lvl = (it.water && it.water.level) ?? 0;
    let map = null;
    if (it.map) {
      // Кусок настоящей карты (tools/map_crop.mjs): рельеф, деревья, камни, вода — с материалами как в игре
      const gm = await new window.T3.GLTFLoader().loadAsync(D.http + `_game/maps/${it.map}.glb`);
      sc.add(gm.scene);
      map = window.T3.prepareDotaMap(THREE, gm.scene, D.http + `_game/maps/${it.map}_tex/`, { water: it.water || {}, sun: it.sun_dir });
      await map.ready;
      // Небо: вертикальный градиент на большой сфере (в игре сверху неба не видно — делаем в тон туману)
      const skyGeo = new THREE.SphereGeometry(900, 32, 16);
      sc.add(new THREE.Mesh(skyGeo, new THREE.ShaderMaterial({ side: THREE.BackSide, depthWrite: false, fog: false,
        uniforms: { top: { value: new THREE.Color(it.sky_top || "#5f9ad0") }, bot: { value: new THREE.Color(it.sky || "#cfe3e6") } },
        vertexShader: "varying float h; void main(){ h = normalize(position).y; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.); }",
        fragmentShader: "uniform vec3 top, bot; varying float h; void main(){ gl_FragColor = vec4(mix(bot, top, smoothstep(0., .45, h)), 1.); }" })));
    }
    // Дно и берега — фото-текстуры из assets/tex
    const TL = new THREE.TextureLoader(), tex = (n, rep) => { const t = TL.load(`assets/tex/${n}.jpg`); t.wrapS = t.wrapT = THREE.RepeatWrapping; t.repeat.set(rep, rep); t.colorSpace = THREE.SRGBColorSpace; return t; };
    const own = !map;
    const bed = new THREE.Mesh(new THREE.PlaneGeometry(80, 80), new THREE.MeshStandardMaterial({ map: tex(it.bed || "cobble", 14), roughness: 1, color: 0x6f7d78 }));
    bed.rotation.x = -Math.PI / 2; bed.position.y = lvl - (it.depth ?? 2.2); if (own) sc.add(bed);
    const bankMat = new THREE.MeshStandardMaterial({ map: tex(it.bank || "forest", 6), roughness: 1 });
    // Дальний берег — пологий склон за рекой (ближнего нет: камера стоит на нём)
    const bank = new THREE.Mesh(new THREE.BoxGeometry(120, 6, 40), bankMat);
    bank.position.set(0, lvl - 2.2, -(it.river_width ?? 16) / 2 - 20); bank.rotation.x = 0.12; if (own) sc.add(bank);
    // Вода: волны в вершинах, круги вокруг героев, блик по Френелю
    const actorsXZ = new Array(8).fill(0).map(() => new THREE.Vector3(999, 0, 999));
    const water = new THREE.Mesh(new THREE.PlaneGeometry(80, 80, 200, 200), new THREE.ShaderMaterial({
      transparent: true, fog: true,
      uniforms: THREE.UniformsUtils.merge([THREE.UniformsLib.fog, {
        t: { value: 0 }, col: { value: new THREE.Color((it.water && it.water.color) || "#2f8f8a") }, deep: { value: new THREE.Color("#0f3b46") },
        A: { value: actorsXZ }, op: { value: (it.water && it.water.opacity) ?? 0.78 } }]),
      vertexShader: `uniform float t; varying vec3 wp; varying float h;
        #include <fog_pars_vertex>
        void main(){ vec3 p = position; vec4 w = modelMatrix * vec4(p,1.);
          h = sin(w.x*.9+t*1.6)*.05 + sin(w.z*1.3-t*1.2)*.04 + sin((w.x+w.z)*2.1+t*2.3)*.02;
          w.y += h; wp = w.xyz; vec4 mvPosition = viewMatrix * w; gl_Position = projectionMatrix * mvPosition;
          #include <fog_vertex>
        }`,
      fragmentShader: `uniform float t; uniform vec3 col; uniform vec3 deep; uniform vec3 A[8]; uniform float op; varying vec3 wp; varying float h;
        #include <fog_pars_fragment>
        void main(){ float ring = 0.;
          for (int i=0;i<8;i++){ float d = length(wp.xz - A[i].xz); float f = fract(d*.7 - t*.5);   // круги расходятся от героя
            ring += smoothstep(.05, 0., min(f, 1.-f)) * exp(-d*.45) * smoothstep(1.2, 2.4, d); }
          vec3 c = mix(deep, col, .55 + h*4.);
          vec3 V = normalize(cameraPosition - wp); float fr = pow(1.-max(V.y,0.), 3.);
          c += vec3(.75,.9,.95)*fr*.35 + vec3(.85,.95,1.)*min(ring,1.)*.3;
          gl_FragColor = vec4(c, op + fr*.15);
          #include <fog_fragment>
        }` }));
    water.rotation.x = -Math.PI / 2; water.position.y = lvl; water.renderOrder = 2; if (own) sc.add(water);
    // Герои
    const actors = [];
    for (const a of it.actors || []) {
      const h = await hero(it.heroes[a.hero], a.anim);
      h.root.position.set(a.x || 0, lvl + (a.y ?? -1.2), a.z || 0);
      h.root.rotation.y = (a.yaw || 0) * Math.PI / 180;
      h.root.scale.setScalar(a.scale || 1);
      sc.add(h.root); actors.push(Object.assign(h, { a }));
    }
    actors.slice(0, 8).forEach((h, k) => actorsXZ[k].set(h.root.position.x, 0, h.root.position.z));
    // Брызги у героев с splash: капли летят по параболе, время каждой капли — по кругу (кадры повторяемы)
    const drops = [];
    actors.filter(h => h.a.splash).forEach((h, k) => {
      const n = h.a.splash === true ? 70 : h.a.splash, geo = new THREE.BufferGeometry(), pos = new Float32Array(n * 3);
      geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
      const pts = new THREE.Points(geo, new THREE.PointsMaterial({ color: 0xe8fbff, size: it.drop_size || 0.22, transparent: true, opacity: .9, depthWrite: false }));
      let sd = 7 + k * 13; const rnd = () => (sd = (sd * 16807) % 2147483647) / 2147483647;
      const P = Array.from({ length: n }, () => ({ a: rnd() * 6.283, r: 1.2 + rnd() * 1.8, vy: 3 + rnd() * 4, vr: 1 + rnd() * 2, life: .7 + rnd() * .6, ph: rnd() }));
      sc.add(pts); drops.push({ pts, P, x: h.root.position.x, z: h.root.position.z });
    });
    const cam = new THREE.PerspectiveCamera(it.fov || 38, W / H, 0.1, 200);
    Object.assign(st, { r, sc, cam, water, actors, drops, lvl, map });
  }

  function drawStage(st, lt, dur) {
    const { THREE } = window.T3, it = st.it, c = it.cam || {};
    st.water.material.uniforms.t.value = lt;
    if (st.map) st.map.update(lt);
    st.drops.forEach(d => {
      const a = d.pts.geometry.attributes.position;
      d.P.forEach((p, i) => {
        const tau = ((lt / p.life + p.ph) % 1) * p.life, rr = p.r + p.vr * tau;
        a.setXYZ(i, d.x + Math.cos(p.a) * rr, st.lvl + Math.max(-.2, p.vy * tau - 4.9 * tau * tau), d.z + Math.sin(p.a) * rr);
      });
      a.needsUpdate = true;
    });
    st.actors.forEach(h => {
      h.mixer.setTime(Math.max(0, lt * (h.a.speed || 1) + (h.a.phase || 0)));
      if (h.rootBone) { h.rootBone.position.x = h.r0.x; h.rootBone.position.z = h.r0.z; }   // на месте, без ухода
    });
    // Камера: плавный переход от pos/look к to.pos/to.look за время сегмента
    const e = (x => x < .5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2)(Math.min(1, lt / dur));
    const P0 = new THREE.Vector3(...(c.pos || [0, 4, 14])), L0 = new THREE.Vector3(...(c.look || [0, 1, 0]));
    const P1 = c.to ? new THREE.Vector3(...(c.to.pos || c.pos)) : P0, L1 = c.to ? new THREE.Vector3(...(c.to.look || c.look)) : L0;
    st.cam.position.lerpVectors(P0, P1, e); st.cam.lookAt(new THREE.Vector3().lerpVectors(L0, L1, e));
    st.r.render(st.sc, st.cam);
  }

  // ---------- таймлайн сцены (после загрузки шрифтов и картинок) ----------
  function timeline(g, isFirst) {
    const S = g.s.scene, tl = gsap.timeline({ paused: true });
    g.sc.tl = tl;
    // Герои и анимации — по реальным пропорциям картинки в своей рамке, низом на нижний край рамки
    // fit: true — текст ужимается, пока самая длинная строка не влезет в ширину элемента
    g.sc.list.forEach(({ it, box }) => {
      if (!it.fit || !it.w) return;
      let fs = parseFloat(getComputedStyle(box).fontSize);
      const widest = () => Math.max(...[...box.querySelectorAll(".ln > span")].map(s => s.scrollWidth));
      while (fs > 20 && widest() > it.w - (it.pad || 0) * 2) { fs -= 2; box.style.fontSize = fs + "px"; }
    });
    // Старт клипа и Lottie: поле start, иначе время появления
    const start = it => when(g, it.start ?? (typeof it.in === "object" ? it.in.at : null) ?? it.at ?? 0);
    g.sc.vids.forEach(v => { v.cv.width = v.it.w; v.cv.height = v.it.h; v.t0 = start(v.it); });
    g.sc.models.forEach(o => { o.t0 = start(o.it); });
    g.sc.lots.forEach(o => {
      o.t0 = start(o.it);
      o.a = lottie.loadAnimation({ container: o.box, renderer: "svg", loop: false, autoplay: false, animationData: o.it.data,
                                   rendererSettings: { preserveAspectRatio: o.it.fit === "cover" ? "xMidYMid slice" : "xMidYMid meet" } });
    });
    g.sc.anims.forEach(o => { const b = o.box; placeAnim(o.A, b.offsetWidth / 2, b.offsetHeight, b.offsetWidth, b.offsetHeight); o.A.cv.style.position = "absolute"; });
    // Камера: медленный наезд на весь сегмент (можно выключить или задать)
    const cam = S.camera === false ? null : Object.assign({ from: 1, to: 1.03, x: 0, y: 0 }, S.camera || {});
    if (cam) tl.fromTo(g.sc.root, { scale: cam.from, x: 0, y: 0 }, { scale: cam.to, x: cam.x, y: cam.y, duration: g.s.dur, ease: "none" }, 0);
    // Первый кадр ролика собран: всё, что входит в первые 0,6 с, уже стоит на месте (обложка в ленте)
    const cover = isFirst && S.cover !== false;
    g.sc.list.forEach(({ it, box }) => {
      if (!it.in || it.in === "none") return;
      const o = typeof it.in === "string" ? { fx: it.in } : it.in, t = when(g, o.at ?? it.at);
      if (cover && t <= 0.6) return;
      (IN[o.fx] || IN.fade)(tl, [box], t, o);
    });
    (S.fx || []).forEach(o => {
      const els = pick(g, o.target || "@all"), t = when(g, o.at);
      if (!els.length) return;
      const fn = IN[o.fx] && !FX[o.fx] ? IN[o.fx] : FX[o.fx];
      if (fn) fn(tl, els, t, o);
    });
    tl.set({}, {}, g.s.dur);
  }

  function draw(g, lt) {
    g.sc.tl.seek(Math.max(0, lt), false);       // false — onUpdate срабатывает и при перемотке (счётчики)
    g.sc.anims.forEach(o => drawAnim(o.A, lt));
    g.sc.stages.forEach(st => { if (st.r) drawStage(st, lt, g.s.dur); });
    g.sc.models.forEach(m => {
      if (!m.r) return;
      m.mixer.setTime(Math.max(0, lt - (m.t0 || 0)) * (m.it.speed || 1));
      if (m.rootBone && m.it.in_place !== false) { m.rootBone.position.x = m.r0.x; m.rootBone.position.z = m.r0.z; }
      m.r.render(m.sc, m.cam);
    });
    g.sc.vids.forEach(v => {
      const n = v.imgs.length; if (!n) return;
      const raw = Math.floor((lt - v.t0) * v.it.clip.fps);
      const i = v.it.loop ? ((raw % n) + n) % n : Math.max(0, Math.min(n - 1, raw));   // до старта — первый кадр, после конца — последний
      if (v.it.hold === false) v.cv.parentNode.style.visibility = raw < 0 || raw >= n ? "hidden" : "visible";   // врезка (мем): только пока идёт
      v.cv.getContext("2d").drawImage(v.imgs[i], 0, 0, v.cv.width, v.cv.height);
    });
    g.sc.lots.forEach(o => {
      const tot = o.a.totalFrames; let f = (lt - o.t0) * o.a.frameRate * (o.it.speed || 1);
      f = o.it.loop ? ((f % tot) + tot) % tot : Math.max(0, Math.min(tot - 1, f));
      o.a.goToAndStop(f, true);
      o.box.style.visibility = lt < o.t0 ? "hidden" : "visible";   // до старта анимации не видно
    });
  }
  return { build, load, timeline, draw };
})();
