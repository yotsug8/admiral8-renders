// Материалы карты Dota 2 для three.js: террейн multiblend (4 слоя с масками смешивания и оттенками, как в шейдере
// игры — по исходникам Source 2 Viewer), вода water_dota (своя: цвет и рябь под дотовскую), листва — с отсечением по альфе.
// Использование: prepareDotaMap(THREE, gltfScene, texUrl, sunDir) после загрузки куска карты (tools/dota_export.py map).
export function prepareDotaMap(THREE, root, texUrl, opts = {}) {
  const TL = new THREE.TextureLoader(), cache = {}, wait = [];
  const tex = (vtexPath, srgb) => {
    const name = vtexPath.split("/").pop().replace(/\.vtex$/, "") + ".png";
    if (!cache[name]) {
      let done; wait.push(new Promise(r => { done = r; }));
      const t = TL.load(texUrl + name, done, undefined, done);   // ждём и удачную, и неудачную загрузку
      t.wrapS = t.wrapT = THREE.RepeatWrapping; t.anisotropy = 4;
      t.colorSpace = srgb ? THREE.SRGBColorSpace : THREE.NoColorSpace;
      cache[name] = t;
    }
    return cache[name];
  };
  const sun = new THREE.Vector3(...(opts.sun || [0.45, 0.8, 0.35])).normalize();
  const water = [];
  root.traverse(o => {
    if (!o.isMesh) return;
    const v = (o.material.userData || {}).vmat;
    if (!v) return;
    if (v.ShaderName === "multiblend.vfx") o.material = multiblend(THREE, v, tex, sun, o.geometry);
    else if (v.ShaderName === "water_dota.vfx") { o.material = waterMat(THREE, opts.water || {}); water.push(o); o.renderOrder = 3; }
    else if (o.material.map) { o.material.alphaTest = 0.4; o.material.transparent = false; }   // листва и трава — края по альфе
  });
  return { water, ready: Promise.all(wait), update: t => water.forEach(w => { w.material.uniforms.t.value = t; }) };
}

function multiblend(THREE, v, tex, sun, geo) {
  const T = v.TextureParams || {}, F = v.FloatParams || {}, V = v.VectorParams || {}, I = v.IntParams || {};
  const col = k => new THREE.Color().setRGB(...((V[k] || [1, 1, 1]).slice(0, 3)), THREE.SRGBColorSpace);
  const u = { sun: { value: sun } };
  for (let i = 0; i < 4; i++) {
    u["c" + i] = { value: T["g_tColor" + i] ? tex(T["g_tColor" + i], true) : null };
    u["s" + i] = { value: [F["g_flTexCoordScale" + i] || 1, F["g_flTexCoordRotate" + i] || 0] };
    u["ta" + i] = { value: col("g_vColorTint" + i) };
    u["tb" + i] = { value: col("g_vColorTintB" + i) };
  }
  u.mask = { value: T.g_tTintMasks ? tex(T.g_tTintMasks, false) : null };
  const hasMask = !!(I.F_TINT_MASK && T.g_tTintMasks);
  // Имена атрибутов, как их называет GLTFLoader для нестандартных _TEXCOORD_n
  const a1 = geo.attributes._texcoord_1 ? "_texcoord_1" : null;
  return new THREE.ShaderMaterial({
    uniforms: THREE.UniformsUtils.merge([THREE.UniformsLib.fog, u]), fog: true,
    defines: { HAS_W: a1 ? 1 : 0, HAS_MASK: hasMask ? 1 : 0 },
    vertexShader: `
      #if HAS_W
      attribute vec4 _texcoord_1; attribute vec4 _texcoord_2; attribute vec4 _texcoord_3;
      #endif
      uniform vec2 s0, s1, s2, s3;
      varying vec2 u0, u1, u2, u3; varying vec4 W, A, VC; varying vec3 N;
      #include <fog_pars_vertex>
      vec2 tc(vec2 p, vec2 s){ float r = radians(s.y); return vec2(cos(r)*p.x - sin(r)*p.y, sin(r)*p.x + cos(r)*p.y) / s.x + .5; }
      void main(){
        u0 = tc(uv, s0); u1 = tc(uv, s1); u2 = tc(uv, s2); u3 = tc(uv, s3);
        #if HAS_W
        W = _texcoord_1; A = _texcoord_2; VC = _texcoord_3;
        #else
        W = vec4(0.); A = vec4(.5); VC = vec4(1.);
        #endif
        N = normalize(mat3(modelMatrix) * normal);
        vec4 mvPosition = modelViewMatrix * vec4(position, 1.); gl_Position = projectionMatrix * mvPosition;
        #include <fog_vertex>
      }`,
    fragmentShader: `
      uniform sampler2D c0, c1, c2, c3, mask; uniform vec3 ta0, ta1, ta2, ta3, tb0, tb1, tb2, tb3, sun;
      varying vec2 u0, u1, u2, u3; varying vec4 W, A, VC; varying vec3 N;
      #include <fog_pars_fragment>
      float bm(float f, float m, float s){ return smoothstep(max(0., m - s), min(1., m + s), f); }
      void main(){
        vec4 C0 = texture2D(c0, u0), C1 = texture2D(c1, u1), C2 = texture2D(c2, u2), C3 = texture2D(c3, u3);
        float w1 = bm(W.x, C1.a, A.x), i1 = 1. - w1;
        float w2 = clamp(bm(W.y, C2.a, A.y), 0., i1), i2 = i1 - w2;
        float w3 = clamp(bm(W.z, C3.a, A.z), 0., i2), w0 = i2 - w3;
        #if HAS_MASK
        vec3 t0 = mix(tb0, ta0, texture2D(mask, u0).r), t1 = mix(tb1, ta1, texture2D(mask, u1).g),
             t2 = mix(tb2, ta2, texture2D(mask, u2).b), t3 = mix(tb3, ta3, texture2D(mask, u3).a);
        #else
        vec3 t0 = ta0, t1 = ta1, t2 = ta2, t3 = ta3;
        #endif
        vec3 c = w0*C0.rgb*t0 + w1*C1.rgb*t1 + w2*C2.rgb*t2 + w3*C3.rgb*t3;
        c *= pow(VC.rgb, vec3(2.2));
        float il = max(0., dot(normalize(N), sun)) + .6; il *= il;          // освещение как в шейдере игры
        gl_FragColor = vec4(c * il * 1.15, 1.);
        #include <colorspace_fragment>
        #include <fog_fragment>
      }`,
  });
}

function waterMat(THREE, o) {
  return new THREE.ShaderMaterial({
    transparent: true, fog: true, depthWrite: false,
    uniforms: THREE.UniformsUtils.merge([THREE.UniformsLib.fog, {
      t: { value: 0 }, col: { value: new THREE.Color(o.color || "#3aa6a0") }, deep: { value: new THREE.Color(o.deep || "#0e4a55") },
      op: { value: o.opacity ?? 0.5 } }]),
    vertexShader: `varying vec3 wp;
      #include <fog_pars_vertex>
      void main(){ vec4 w = modelMatrix * vec4(position, 1.); wp = w.xyz; vec4 mvPosition = viewMatrix * w; gl_Position = projectionMatrix * mvPosition;
      #include <fog_vertex>
      }`,
    fragmentShader: `uniform float t; uniform vec3 col, deep; uniform float op; varying vec3 wp;
      #include <fog_pars_fragment>
      float n(vec2 p){ return sin(p.x + sin(p.y*.7)) * .5 + sin(dot(p, vec2(.6,.8)) * 1.3) * .3 + sin(dot(p, vec2(-.8,.5)) * 2.1) * .2; }
      void main(){
        vec2 p = wp.xz;
        float r = n(p*1.3 + vec2(t*.6, t*.4)) * .5 + n(p*2.7 - vec2(t*.5, -t*.7)) * .3 + n(p*5.1 + t) * .2;
        float glint = smoothstep(.55, .9, r);
        vec3 V = normalize(cameraPosition - wp); float fr = pow(1. - max(V.y, 0.), 3.);
        vec3 c = mix(deep, col, .55 + r*.25) + vec3(.9,1.,1.)*glint*.35 + vec3(.7,.85,.9)*fr*.4;
        gl_FragColor = vec4(c, op + fr*.2);
        #include <colorspace_fragment>
        #include <fog_fragment>
      }` });
}
