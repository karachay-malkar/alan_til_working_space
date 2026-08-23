(() => {
  'use strict';

  const RELEASE = '7.3.7';
  const baseUrl = new URL('.', document.currentScript.src);
  const scripts = [
    'maplibre.js',
    'pmtiles.js',
    'map-data-core.js',
    'map-core.js',
    'map-ui.js',
    'map-presentation-r2.js',
    'map-granite-frame.js',
    'map-page.js'
  ];

  const assetUrl = (name) => {
    const url = new URL(name, baseUrl);
    url.searchParams.set('v', RELEASE);
    return url.href;
  };

  let failed = false;
  const fail = (name) => {
    if (failed) return;
    failed = true;
    const error = new Error(`Alan Map: не загружен ${name}.`);
    console.error(error);
    const root = document.getElementById('alan-map-root');
    if (root) root.innerHTML = `<div style="padding:20px;color:#fff;background:#25282a">Карта не загрузилась: ${error.message}</div>`;
  };

  // Dynamic classic scripts with async=false are fetched in parallel but executed in insertion order.
  for (const name of scripts) {
    const script = document.createElement('script');
    script.async = false;
    script.src = assetUrl(name);
    script.onerror = () => fail(name);
    document.head.appendChild(script);
  }

  window.ALAN_MAP_BOOTSTRAP_DIAGNOSTICS = () => ({
    version: RELEASE,
    strategy: 'parallel-fetch-ordered-execution',
    runtimeEval: false,
    terrainRuntime: 'maplibre-native-single-source',
    scripts: [...scripts]
  });
})();
