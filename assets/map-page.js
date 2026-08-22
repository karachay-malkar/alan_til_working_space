(() => {
  'use strict';

  const VERSION = '7.3.6';
  const RANGE_CACHE_BYTES = (() => {
    const memory = Number(navigator.deviceMemory || 0);
    if (memory > 0 && memory <= 2) return 12 * 1024 * 1024;
    if (memory > 0 && memory <= 4) return 24 * 1024 * 1024;
    return 40 * 1024 * 1024;
  })();
  const RANGE_CACHE_ENTRIES = 256;
  const RANGE_RETRY_DELAYS_MS = Object.freeze([0,220,680]);
  const VECTOR_RANGE_RETRY_DELAYS_MS = Object.freeze([0,360,1050,2200]);
  const VECTOR_FULL_FILE_FALLBACK_MAX_BYTES = 24 * 1024 * 1024;

  const root = document.getElementById('alan-map-root');
  if (!root) throw new Error('Alan Map root container was not found.');

  document.documentElement.classList.add('alan-map-document');
  document.body.classList.add('alan-map-document');
  root.classList.add('alan-map-viewport-root');

  let resizeFrame = null;
  let orientationTimer = null;
  let mapInstance = null;
  const startedAt = performance.now();
  const performanceState = {
    readyMs:null,
    firstIdleMs:null,
    renderFrames:0,
    renderFps:null,
    renderIntervals:[],
    lastRenderAt:null,
    deferredDataRequestedMs:null,
    deferredDataReadyMs:null,
    deferredPointsRequestedMs:null,
    deferredPointsReadyMs:null,
    snowSourceRegisteredMs:null
  };

  class RangeLruCache {
    constructor(maxEntries, maxBytes) {
      this.maxEntries = maxEntries;
      this.maxBytes = maxBytes;
      this.entries = new Map();
      this.pending = new Map();
      this.bytes = 0;
      this.hits = 0;
      this.misses = 0;
      this.evictions = 0;
    }

    get(key) {
      const record = this.entries.get(key);
      if (!record) return null;
      this.entries.delete(key);
      this.entries.set(key, record);
      this.hits += 1;
      return record.value;
    }

    remember(key, value) {
      const size = Number(value?.data?.byteLength || 0);
      if (!Number.isFinite(size) || size <= 0 || size > this.maxBytes) return value;
      if (this.entries.has(key)) {
        this.bytes -= this.entries.get(key).size;
        this.entries.delete(key);
      }
      this.entries.set(key, {value, size});
      this.bytes += size;
      while (this.entries.size > this.maxEntries || this.bytes > this.maxBytes) {
        const oldestKey = this.entries.keys().next().value;
        if (oldestKey === undefined) break;
        const oldest = this.entries.get(oldestKey);
        this.entries.delete(oldestKey);
        this.bytes -= oldest?.size || 0;
        this.evictions += 1;
      }
      return value;
    }

    async getOrCreate(key, factory) {
      const cached = this.get(key);
      if (cached) return cached;
      if (this.pending.has(key)) {
        this.hits += 1;
        return this.pending.get(key);
      }
      this.misses += 1;
      const pending = Promise.resolve().then(factory).then((value) => this.remember(key, value));
      this.pending.set(key, pending);
      try {
        return await pending;
      } finally {
        this.pending.delete(key);
      }
    }

    diagnostics() {
      return {
        maxEntries:this.maxEntries,
        maxBytes:this.maxBytes,
        entries:this.entries.size,
        bytes:this.bytes,
        pending:this.pending.size,
        hits:this.hits,
        misses:this.misses,
        evictions:this.evictions
      };
    }
  }

  class NetworkGate {
    constructor(limit) {
      this.limit = Math.max(1,Number(limit) || 1);
      this.active = 0;
      this.queue = [];
    }

    acquire(signal) {
      if (signal?.aborted) return Promise.reject(signal.reason || new DOMException('Aborted','AbortError'));
      if (this.active < this.limit) {
        this.active += 1;
        return Promise.resolve();
      }
      return new Promise((resolve,reject) => {
        const entry = {resolve,reject,signal,onAbort:null};
        entry.onAbort = () => {
          const index = this.queue.indexOf(entry);
          if (index >= 0) this.queue.splice(index,1);
          reject(signal.reason || new DOMException('Aborted','AbortError'));
        };
        signal?.addEventListener?.('abort',entry.onAbort,{once:true});
        this.queue.push(entry);
      });
    }

    release() {
      this.active = Math.max(0,this.active - 1);
      while (this.queue.length) {
        const entry = this.queue.shift();
        entry.signal?.removeEventListener?.('abort',entry.onAbort);
        if (entry.signal?.aborted) continue;
        this.active += 1;
        entry.resolve();
        break;
      }
    }

    async run(factory, signal) {
      await this.acquire(signal);
      try { return await factory(); } finally { this.release(); }
    }

    diagnostics() { return {limit:this.limit,active:this.active,queued:this.queue.length}; }
  }

  class InstrumentedRangeSource {
    constructor(archivePath, cache, options = {}) {
      this.archivePath = archivePath;
      this.sourceId = String(options.sourceId || 'unknown');
      this.url = new URL(archivePath, document.baseURI).href;
      this.cache = cache;
      this.customHeaders = new Headers();
      this.mustReload = false;
      this.retryDelays = Object.freeze([...(options.retryDelays || RANGE_RETRY_DELAYS_MS)]);
      this.gate = new NetworkGate(options.maxConcurrent || 8);
      this.allowFullFileFallback = Boolean(options.allowFullFileFallback);
      this.fullFileFallbackMaxBytes = Number(options.fullFileFallbackMaxBytes || 0);
      this.fullBuffer = null;
      this.fullFilePromise = null;
      this.fullEtag = undefined;
      this.requests = 0;
      this.networkBytes = 0;
      this.rangeBytesRequested = 0;
      this.lastRequestMs = 0;
      this.status206Confirmed = false;
      this.retries = 0;
      this.failures = 0;
      this.lastHttpStatus = null;
      this.lastError = '';
      this.lastFailureOffset = null;
      this.lastFailureLength = null;
      this.fullFileFallbackDownloads = 0;
      this.fullFileFallbackBytes = 0;
      this.fullFileFallbackFailures = 0;
    }

    getKey() { return this.url; }

    setHeaders(headers) { this.customHeaders = new Headers(headers || {}); }

    responseHeaders(response) {
      let etag = response.headers.get('Etag');
      if (etag?.startsWith('W/')) etag = null;
      return {
        etag:etag || undefined,
        cacheControl:response.headers.get('Cache-Control') || undefined,
        expires:response.headers.get('Expires') || undefined
      };
    }

    async useWholeResponse(response, offset, length, expectedEtag) {
      const headerLength = Number(response.headers.get('Content-Length') || 0);
      if (!this.allowFullFileFallback || !(this.fullFileFallbackMaxBytes > 0) || !headerLength || headerLength > this.fullFileFallbackMaxBytes) {
        throw new Error(`Server returned HTTP 200 for a byte-range request (${headerLength || 'unknown'} bytes).`);
      }
      const before = performance.now();
      const buffer = await response.arrayBuffer();
      if (buffer.byteLength > this.fullFileFallbackMaxBytes || offset + length > buffer.byteLength) {
        throw new Error(`Full-file fallback size is invalid: ${buffer.byteLength} bytes.`);
      }
      const headers = this.responseHeaders(response);
      this.fullBuffer = buffer;
      this.fullEtag = expectedEtag || headers.etag;
      this.fullFileFallbackDownloads += 1;
      this.fullFileFallbackBytes += buffer.byteLength;
      this.networkBytes += buffer.byteLength;
      this.requests += 1;
      this.lastRequestMs = performance.now() - before;
      document.dispatchEvent(new CustomEvent('alan-map:pmtiles-range-loaded',{detail:{archivePath:this.archivePath,sourceId:this.sourceId,offset,length,bytes:length,durationMs:this.lastRequestMs,transport:'full-file-fallback'}}));
      return {data:buffer.slice(offset,offset + length),etag:this.fullEtag,cacheControl:headers.cacheControl,expires:headers.expires};
    }

    async fetchRange(offset, length, signal, etag) {
      return this.gate.run(async () => {
        const before = performance.now();
        const headers = new Headers(this.customHeaders);
        headers.set('Range',`bytes=${offset}-${offset + length - 1}`);
        const response = await fetch(this.url,{signal,headers,cache:this.mustReload ? 'reload' : undefined});
        this.lastHttpStatus = response.status;
        if (offset === 0 && response.status === 416) {
          const contentRange = response.headers.get('Content-Range');
          if (!contentRange?.startsWith('bytes */')) throw new Error('Missing content-length on HTTP 416 response.');
        }
        const responseHeaders = this.responseHeaders(response);
        if (response.status === 416 || (etag && responseHeaders.etag && etag !== responseHeaders.etag)) {
          this.mustReload = true;
          throw new Error(`PMTiles ETag/range mismatch (HTTP ${response.status}).`);
        }
        if (response.status >= 300) throw new Error(`Bad response code: ${response.status}`);
        if (response.status === 200) return this.useWholeResponse(response,offset,length,etag);
        if (response.status !== 206) throw new Error(`Unexpected byte-range response: HTTP ${response.status}`);
        const result = {data:await response.arrayBuffer(),...responseHeaders};
        if (result.data.byteLength !== length) throw new Error(`Incomplete byte range: expected ${length}, received ${result.data.byteLength}.`);
        this.requests += 1;
        this.networkBytes += result.data.byteLength;
        this.lastRequestMs = performance.now() - before;
        this.status206Confirmed = true;
        this.lastError = '';
        document.dispatchEvent(new CustomEvent('alan-map:pmtiles-range-loaded',{detail:{archivePath:this.archivePath,sourceId:this.sourceId,offset,length,bytes:result.data.byteLength,durationMs:this.lastRequestMs,retries:this.retries,httpStatus:response.status,transport:'http-range'}}));
        return result;
      },signal);
    }

    async ensureFullFile() {
      if (this.fullBuffer) return this.fullBuffer;
      if (!this.allowFullFileFallback || !(this.fullFileFallbackMaxBytes > 0)) throw new Error('Full-file fallback is disabled.');
      if (this.fullFilePromise) return this.fullFilePromise;
      this.fullFilePromise = (async () => {
        try {
          const before = performance.now();
          const response = await fetch(this.url,{headers:this.customHeaders,cache:'reload'});
          this.lastHttpStatus = response.status;
          if (!response.ok) throw new Error(`Full-file fallback failed: HTTP ${response.status}`);
          const contentLength = Number(response.headers.get('Content-Length') || 0);
          if (contentLength && contentLength > this.fullFileFallbackMaxBytes) throw new Error(`Full-file fallback exceeds ${this.fullFileFallbackMaxBytes} bytes.`);
          const buffer = await response.arrayBuffer();
          if (buffer.byteLength > this.fullFileFallbackMaxBytes) throw new Error(`Full-file fallback exceeds ${this.fullFileFallbackMaxBytes} bytes.`);
          const headers = this.responseHeaders(response);
          this.fullBuffer = buffer;
          this.fullEtag = headers.etag;
          this.fullFileFallbackDownloads += 1;
          this.fullFileFallbackBytes += buffer.byteLength;
          this.networkBytes += buffer.byteLength;
          this.requests += 1;
          this.lastRequestMs = performance.now() - before;
          this.lastError = '';
          return buffer;
        } catch (error) {
          this.fullFileFallbackFailures += 1;
          throw error;
        } finally {
          if (!this.fullBuffer) this.fullFilePromise = null;
        }
      })();
      return this.fullFilePromise;
    }

    async fallbackSlice(offset, length, etag) {
      const buffer = await this.ensureFullFile();
      if (offset + length > buffer.byteLength) throw new Error(`Full-file fallback range exceeds archive size: ${offset}+${length}>${buffer.byteLength}.`);
      document.dispatchEvent(new CustomEvent('alan-map:pmtiles-range-loaded',{detail:{archivePath:this.archivePath,sourceId:this.sourceId,offset,length,bytes:length,durationMs:0,transport:'full-file-fallback'}}));
      return {data:buffer.slice(offset,offset + length),etag:etag || this.fullEtag};
    }

    async getBytes(offset, length, signal, etag) {
      this.rangeBytesRequested += Number(length || 0);
      if (this.fullBuffer) return this.fallbackSlice(offset,length,etag);
      const key = `${this.url}|${offset}|${length}|${etag || ''}`;
      return this.cache.getOrCreate(key, async () => {
        let lastError = null;
        for (let attempt = 0; attempt < this.retryDelays.length; attempt += 1) {
          if (attempt > 0) {
            this.retries += 1;
            await waitForRetry(this.retryDelays[attempt],signal);
          }
          try {
            return await this.fetchRange(offset,length,signal,etag);
          } catch (error) {
            lastError = error;
            this.lastError = String(error?.message || error || 'Range request failed');
            this.lastFailureOffset = offset;
            this.lastFailureLength = length;
            if (!retryableRangeError(error,signal) || attempt === this.retryDelays.length - 1) break;
          }
        }
        if (this.allowFullFileFallback && !signal?.aborted && retryableRangeError(lastError,signal)) {
          try { return await this.fallbackSlice(offset,length,etag); } catch (fallbackError) { lastError = fallbackError; this.lastError = String(fallbackError?.message || fallbackError); }
        }
        this.failures += 1;
        document.dispatchEvent(new CustomEvent('alan-map:pmtiles-range-failed',{detail:{archivePath:this.archivePath,sourceId:this.sourceId,offset,length,httpStatus:this.lastHttpStatus,error:this.lastError}}));
        throw lastError || new Error(`Range request failed for ${this.archivePath}`);
      });
    }

    diagnostics() {
      return {
        archivePath:this.archivePath,sourceId:this.sourceId,url:this.url,
        mode:this.fullBuffer ? 'full-file-fallback' : 'http-range',
        requests:this.requests,networkBytes:this.networkBytes,rangeBytesRequested:this.rangeBytesRequested,
        lastRequestMs:this.lastRequestMs,byteServingConfirmed:this.status206Confirmed,retries:this.retries,failures:this.failures,
        lastHttpStatus:this.lastHttpStatus,lastError:this.lastError,lastFailureOffset:this.lastFailureOffset,lastFailureLength:this.lastFailureLength,
        fullFileFallbackAllowed:this.allowFullFileFallback,fullFileFallbackActive:Boolean(this.fullBuffer),
        fullFileFallbackDownloads:this.fullFileFallbackDownloads,fullFileFallbackBytes:this.fullFileFallbackBytes,fullFileFallbackFailures:this.fullFileFallbackFailures,
        concurrency:this.gate.diagnostics()
      };
    }
  }

  function viewportHeight() {
    const visualHeight = Number(window.visualViewport?.height || 0);
    const innerHeight = Number(window.innerHeight || 0);
    const documentHeight = Number(document.documentElement.clientHeight || 0);
    return Math.max(1, Math.round(visualHeight || innerHeight || documentHeight || 1));
  }

  function applyViewportHeight() {
    const height = viewportHeight();
    document.documentElement.style.setProperty('--alan-map-viewport-height', `${height}px`);
    root.style.height = `${height}px`;
    if (resizeFrame !== null) cancelAnimationFrame(resizeFrame);
    resizeFrame = requestAnimationFrame(() => {
      resizeFrame = null;
      mapInstance?.resize();
    });
  }

  function queueOrientationResize() {
    clearTimeout(orientationTimer);
    applyViewportHeight();
    orientationTimer = setTimeout(applyViewportHeight, 180);
  }

  function isMobileTransportProfile() {
    const coarsePointer = typeof matchMedia === 'function' && matchMedia('(pointer: coarse)').matches;
    const touchDevice = Number(navigator.maxTouchPoints || 0) > 0;
    const narrowViewport = Math.min(Number(window.innerWidth || 0), Number(window.innerHeight || 0)) > 0 && Math.min(Number(window.innerWidth || 0), Number(window.innerHeight || 0)) <= 820;
    return coarsePointer || touchDevice || narrowViewport;
  }

  function canUseVectorFullFileFallback() {
    const connection = navigator.connection || navigator.mozConnection || navigator.webkitConnection;
    if (connection?.saveData) return false;
    const effectiveType = String(connection?.effectiveType || '').toLowerCase();
    return !['slow-2g','2g','3g'].includes(effectiveType);
  }

  function waitForRetry(delayMs, signal) {
    if (!(delayMs > 0)) return Promise.resolve();
    return new Promise((resolve, reject) => {
      if (signal?.aborted) {
        reject(signal.reason || new DOMException('Aborted','AbortError'));
        return;
      }
      const timer = setTimeout(resolve,delayMs);
      signal?.addEventListener?.('abort',() => {
        clearTimeout(timer);
        reject(signal.reason || new DOMException('Aborted','AbortError'));
      },{once:true});
    });
  }

  function retryableRangeError(error, signal) {
    if (signal?.aborted || String(error?.name || '') === 'AbortError') return false;
    const message = String(error?.message || error || '');
    if (/404|416|range not satisfiable|etag mismatch/i.test(message)) return false;
    return /failed to fetch|network|load failed|timeout|timed out|connection|bad response code: (429|5\d\d)|unexpected byte-range response|http 200 for a byte-range request|incomplete byte range|502|503|504|429/i.test(message) || error instanceof TypeError;
  }

  function installRenderMetrics(map) {
    map.on('render',() => {
      const now = performance.now();
      performanceState.renderFrames += 1;
      if (performanceState.lastRenderAt !== null) {
        const interval = now - performanceState.lastRenderAt;
        if (interval > 0 && interval < 250) {
          performanceState.renderIntervals.push(interval);
          if (performanceState.renderIntervals.length > 90) performanceState.renderIntervals.shift();
          const average = performanceState.renderIntervals.reduce((sum,value) => sum + value,0) / performanceState.renderIntervals.length;
          performanceState.renderFps = average > 0 ? Math.min(240,1000 / average) : null;
        }
      }
      performanceState.lastRenderAt = now;
    });
    map.once('idle',() => {
      performanceState.firstIdleMs = performance.now() - startedAt;
    });
  }

  async function start() {
    if (!window.pmtiles?.Protocol || !window.pmtiles?.PMTiles || !window.pmtiles?.FetchSource) {
      throw new Error('Alan Map: локальный PMTiles-модуль не подключён.');
    }
    const data = window.ALAN_MAP_DATA;
    if (!data?.regionalDem?.archivePath || !data?.regionalVector?.archivePath) {
      throw new Error('Alan Map: в данных отсутствуют пути локальных PMTiles.');
    }

    const rangeCache = new RangeLruCache(RANGE_CACHE_ENTRIES,RANGE_CACHE_BYTES);
    const protocol = new window.pmtiles.Protocol();
    const archiveRecords = [];
    const archiveByPath = new Map();
    const mobileTransport = isMobileTransportProfile();
    const vectorFullFileFallbackAllowed = canUseVectorFullFileFallback();
    const registerArchive = (entry) => {
      if (!entry?.path) return null;
      if (archiveByPath.has(entry.path)) return archiveByPath.get(entry.path);
      const source = new InstrumentedRangeSource(entry.path,rangeCache,entry);
      const archive = new window.pmtiles.PMTiles(source);
      protocol.add(archive);
      const record = {...entry,source,archive};
      archiveByPath.set(entry.path,record);
      archiveRecords.push(record);
      return record;
    };
    const configurations = [
      {path:data.regionalDem.archivePath,sourceId:'terrain-dem',config:data.regionalDem,maxConcurrent:mobileTransport?6:10,retryDelays:RANGE_RETRY_DELAYS_MS},
      {path:data.regionalVector.archivePath,sourceId:'openmaptiles',config:data.regionalVector,maxConcurrent:mobileTransport?3:8,retryDelays:VECTOR_RANGE_RETRY_DELAYS_MS,allowFullFileFallback:vectorFullFileFallbackAllowed,fullFileFallbackMaxBytes:VECTOR_FULL_FILE_FALLBACK_MAX_BYTES},
      ...(data.regionalLandcover?.archivePath ? [{path:data.regionalLandcover.archivePath,sourceId:'copernicus-landcover',config:data.regionalLandcover,maxConcurrent:mobileTransport?3:6,retryDelays:RANGE_RETRY_DELAYS_MS}] : [])
    ];

    configurations.forEach(registerArchive);

    const prepareSnowSource = () => {
      if (!data.regionalSnow?.available || !data.regionalSnow?.archivePath) return null;
      const record = registerArchive({
        path:data.regionalSnow.archivePath,
        sourceId:'snow',
        config:data.regionalSnow,
        prefetch:false,
        maxConcurrent:mobileTransport?3:6,
        retryDelays:RANGE_RETRY_DELAYS_MS
      });
      if (record && performanceState.snowSourceRegisteredMs === null) performanceState.snowSourceRegisteredMs = performance.now() - startedAt;
      return record;
    };

    let deferredDataPromise = null;
    const loadDeferredData = () => {
      if (window.ALAN_MAP_DEFERRED_DATA?.version === VERSION) return Promise.resolve(window.ALAN_MAP_DEFERRED_DATA);
      if (deferredDataPromise) return deferredDataPromise;
      if (performanceState.deferredDataRequestedMs === null) performanceState.deferredDataRequestedMs = performance.now() - startedAt;
      const configuredPath = String(data.runtimeLoading?.deferredDataScript || 'assets/map-data-deferred.js');
      const url = new URL(configuredPath,document.baseURI);
      url.searchParams.set('v',VERSION);
      deferredDataPromise = new Promise((resolve,reject) => {
        const script = document.createElement('script');
        script.async = true;
        script.src = url.href;
        script.onload = () => {
          const payload = window.ALAN_MAP_DEFERRED_DATA;
          if (!payload || payload.version !== VERSION) {
            reject(new Error('Alan Map: отложенные данные имеют неверную версию.'));
            return;
          }
          performanceState.deferredDataReadyMs = performance.now() - startedAt;
          resolve(payload);
        };
        script.onerror = () => reject(new Error('Alan Map: не загружены отложенные данные.'));
        document.head.appendChild(script);
      }).catch((error) => {
        deferredDataPromise = null;
        throw error;
      });
      return deferredDataPromise;
    };

    let deferredPointsPromise = null;
    const loadDeferredPoints = () => {
      if (window.ALAN_MAP_POINT_DATA?.version === VERSION) return Promise.resolve(window.ALAN_MAP_POINT_DATA);
      if (deferredPointsPromise) return deferredPointsPromise;
      if (performanceState.deferredPointsRequestedMs === null) performanceState.deferredPointsRequestedMs = performance.now() - startedAt;
      const configuredPath = String(data.runtimeLoading?.deferredPointsScript || 'assets/map-data-points.js');
      const url = new URL(configuredPath,document.baseURI);
      url.searchParams.set('v',VERSION);
      deferredPointsPromise = new Promise((resolve,reject) => {
        const script = document.createElement('script');
        script.async = true;
        script.src = url.href;
        script.onload = () => {
          const payload = window.ALAN_MAP_POINT_DATA;
          if (!payload || payload.version !== VERSION) {
            reject(new Error('Alan Map: точечные данные имеют неверную версию.'));
            return;
          }
          performanceState.deferredPointsReadyMs = performance.now() - startedAt;
          resolve(payload);
        };
        script.onerror = () => reject(new Error('Alan Map: не загружены точечные данные.'));
        document.head.appendChild(script);
      }).catch((error) => {
        deferredPointsPromise = null;
        throw error;
      });
      return deferredPointsPromise;
    };

    window.maplibregl.addProtocol('pmtiles',protocol.tile);
    window.ALAN_MAP_PMTILES_PROTOCOL = protocol;
    window.ALAN_MAP_PMTILES_RANGE_DIAGNOSTICS = () => ({
      mode:'adaptive-http-range',
      mobileProfile:mobileTransport,
      vectorFullFileFallbackAllowed,
      cache:rangeCache.diagnostics(),
      archives:archiveRecords.map((record) => record.source.diagnostics())
    });

    root.addEventListener('alan-map:ready',() => {
      performanceState.readyMs = performance.now() - startedAt;
    },{once:true});

    applyViewportHeight();
    mapInstance = window.AlanMap.mount(root, {
      data,
      maplibregl:window.maplibregl,
      regionalLabels3D:window.RegionalLabels3D,
      storageKey:`alan-map-stage${VERSION}-view`,
      loadDeferredData,
      loadDeferredPoints,
      prepareSnowSource
    });
    window.ALAN_MAP_INSTANCE = mapInstance;

    const map = mapInstance?.map;
    if (map) installRenderMetrics(map);

    window.ALAN_MAP_PERFORMANCE_DIAGNOSTICS = () => {
      const transport = window.ALAN_MAP_PMTILES_RANGE_DIAGNOSTICS?.() || {};
      const totalNetworkBytes = (transport.archives || []).reduce((sum,item) => sum + Number(item.networkBytes || 0),0);
      const totalNetworkRequests = (transport.archives || []).reduce((sum,item) => sum + Number(item.requests || 0),0);
      return {
        version:VERSION,
        readyMs:performanceState.readyMs,
        firstIdleMs:performanceState.firstIdleMs,
        renderFrames:performanceState.renderFrames,
        renderFps:performanceState.renderFps,
        totalNetworkBytes,
        totalNetworkRequests,
        deferredDataRequestedMs:performanceState.deferredDataRequestedMs,
        deferredDataReadyMs:performanceState.deferredDataReadyMs,
        deferredPointsRequestedMs:performanceState.deferredPointsRequestedMs,
        deferredPointsReadyMs:performanceState.deferredPointsReadyMs,
        snowSourceRegisteredMs:performanceState.snowSourceRegisteredMs,
        transport
      };
    };

    window.addEventListener('resize',applyViewportHeight,{passive:true});
    window.addEventListener('orientationchange',queueOrientationResize,{passive:true});
    window.visualViewport?.addEventListener('resize',applyViewportHeight,{passive:true});
    document.addEventListener('fullscreenchange',applyViewportHeight);
    document.addEventListener('webkitfullscreenchange',applyViewportHeight);
  }

  start().catch((error) => {
    console.error(error);
    root.innerHTML = `<div class="alan-map-fatal-error">Карта не загрузилась: ${String(error?.message || error)}</div>`;
    root.dispatchEvent(new CustomEvent('alan-map:error',{detail:{message:String(error?.message || error)}}));
  });
})();
