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
    g.sc = { root, items: {}, anims: [], list: [] };
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
    if (it.tint) css.setProperty("--tb", `linear-gradient(180deg, ${[].concat(it.tint).map(col).join(", ")})`);
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
  }
  return { build, timeline, draw };
})();
