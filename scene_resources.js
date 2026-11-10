// CSS images do not belong to document.images; fonts.ready also resolves on failure.
const failedSceneStylesheets = new WeakSet();
document.addEventListener('error', event => {
  if (event.target instanceof HTMLLinkElement && event.target.relList.contains('stylesheet'))
    failedSceneStylesheets.add(event.target);
}, true);

async function waitForSceneStyles() {
  for (const link of document.querySelectorAll('link[rel="stylesheet"]')) {
    if (!link.disabled && (failedSceneStylesheets.has(link) || !link.sheet))
      throw new Error(`CSS: не загружена таблица стилей ${link.href}`);
  }

  const bounded = async (promise, label) => {
    let timer;
    try {
      return await Promise.race([promise, new Promise((_, reject) => {
        timer = setTimeout(() => reject(new Error(`${label}: таймаут загрузки 30000 мс`)), 30000);
      })]);
    } finally { clearTimeout(timer); }
  };
  // getComputedStyle serializes url() with CSS quoting/escapes. Resolve all plans,
  // including currently hidden ones, before timeline changes display/visibility.
  const unescapeCSS = text => text.replace(/\\([\da-f]{1,6}\s?|\r\n|[\n\r\f]|.)/gi, (_, esc) => {
    if (/^[\da-f]/i.test(esc)) {
      const n = parseInt(esc.trim(), 16);
      return n && n <= 0x10ffff && !(n >= 0xd800 && n <= 0xdfff) ? String.fromCodePoint(n) : '\ufffd';
    }
    return /^[\n\r\f]/.test(esc) ? '' : esc;
  });
  const images = new Map();
  const props = ['background-image', 'mask-image', 'border-image-source', 'list-style-image', 'content'];
  const urlPattern = /url\(\s*(?:"((?:\\.|[^"\\])*)"|'((?:\\.|[^'\\])*)'|([^)]*?))\s*\)/gi;
  for (const el of document.querySelectorAll('body, body *')) {
    for (const pseudo of [null, '::before', '::after']) {
      const style = getComputedStyle(el, pseudo);
      if (pseudo && (style.content === 'none' || style.content === 'normal')) continue;
      for (const prop of props) {
        const value = style.getPropertyValue(prop);
        for (const match of value.matchAll(urlPattern)) {
          const raw = unescapeCSS(match[1] ?? match[2] ?? match[3]);
          const url = new URL(raw, document.baseURI);
          const page = new URL(document.baseURI);
          // An SVG reference to a mask in this document is not an external image.
          if (url.hash && url.href.split('#')[0] === page.href.split('#')[0]) continue;
          if (!images.has(url.href)) {
            const id = el.dataset.sid || el.id || el.tagName.toLowerCase();
            images.set(url.href, `CSS ${id}${pseudo || ''} ${prop}`);
          }
        }
      }
    }
  }
  const fonts = [...document.fonts].map(async face => {
    const label = `Шрифт ${face.family} ${face.weight} ${face.style} (${face.unicodeRange})`;
    try { await bounded(face.load(), label); }
    catch (error) { throw new Error(`${label}: ${error.message}`); }
  });
  const loads = [...images].map(([url, label]) => {
    const im = new Image(); im.src = url;
    return waitForImage(im, label);
  });
  await Promise.all([...fonts, ...loads]);
  await bounded(document.fonts.ready, 'Шрифты');
}
