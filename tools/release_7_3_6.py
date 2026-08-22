#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = '7.3.6'
BASE_BRANCH_VERSION = '7.3.5'
OLD_RUNTIME_VERSION = '7.3.3'
OLD_DEM = 'data/alan-dem-7.3.5.pmtiles'
NEW_DEM = 'data/alan-dem-7.3.6.pmtiles'
DATA_VERSION = '7.3.6-dem-z7-z10-256-5m-sequential.1'
MARKER = 'window.ALAN_MAP_DATA = '
SOURCE_PARTS = [ROOT / 'assets/map-data.part-000.js', ROOT / 'assets/map-data.part-001.js']
EXPECTED_BOUNDS = [40.51784, 42.734095, 44.184003, 44.534975]
EXPECTED_CENTER = [42.350921, 43.634535]
EXPECTED_RING = [
    [40.51784, 43.41265],
    [43.731622, 42.734095],
    [44.184003, 43.85642],
    [40.970221, 44.534975],
    [40.51784, 43.41265],
]
LOD_MODEL = 'single-pyramid-native-z7-z10-overzoom-z10'
GENERALIZATION = 'sequential-z10-z9-z8-z7-area-average-5m'
RESOLUTION = {'7': 885.148, '8': 442.574, '9': 221.287, '10': 110.644}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def parse_wrapped(path: Path, marker: str) -> dict:
    source = path.read_text(encoding='utf-8').strip()
    if not source.startswith(marker) or not source.endswith(';'):
        raise RuntimeError(f'{path}: unexpected wrapper')
    return json.loads(source[len(marker):-1])


def write_wrapped(path: Path, marker: str, data: dict) -> None:
    path.write_text(marker + json.dumps(data, ensure_ascii=False, separators=(',', ':')) + ';\n', encoding='utf-8')


def read_source_parts() -> dict:
    source = ''.join(path.read_text(encoding='utf-8') for path in SOURCE_PARTS).strip()
    if not source.startswith(MARKER) or not source.endswith(';'):
        raise RuntimeError('Unexpected map-data source wrapper')
    return json.loads(source[len(MARKER):-1])


def write_source_parts(data: dict) -> None:
    payload = '\n' + MARKER + json.dumps(data, ensure_ascii=False, separators=(',', ':')) + ';\n'
    midpoint = len(payload) // 2
    SOURCE_PARTS[0].write_text(payload[:midpoint], encoding='utf-8')
    SOURCE_PARTS[1].write_text(payload[midpoint:], encoding='utf-8')


def replace_required(text: str, old: str, new: str, label: str, count: int = 1) -> str:
    occurrences = text.count(old)
    if occurrences < count:
        raise RuntimeError(f'{label}: expected at least {count} occurrence(s), found {occurrences}: {old!r}')
    return text.replace(old, new, count)


def regex_replace_required(text: str, pattern: str, replacement: str, label: str, flags: int = 0) -> str:
    output, count = re.subn(pattern, replacement, text, count=1, flags=flags)
    if count != 1:
        raise RuntimeError(f'{label}: expected one regex replacement, found {count}')
    return output


def frame_ring(data: dict) -> list:
    return (((data.get('mapFrame') or {}).get('features') or [{}])[0].get('geometry') or {}).get('coordinates', [[]])[0]


def validate_geography(data: dict) -> None:
    if data.get('bounds') != EXPECTED_BOUNDS:
        raise RuntimeError(f'map bounds changed: {data.get("bounds")}')
    if data.get('center') != EXPECTED_CENTER:
        raise RuntimeError(f'map center changed: {data.get("center")}')
    if frame_ring(data) != EXPECTED_RING:
        raise RuntimeError('map frame geometry changed')


def prepare() -> None:
    data = parse_wrapped(ROOT / 'assets/map-data-core.js', MARKER)
    validate_geography(data)
    build = ROOT / 'build'
    build.mkdir(exist_ok=True)
    (build / 'map-frame.geojson').write_text(json.dumps(data['mapFrame'], ensure_ascii=False, separators=(',', ':')) + '\n', encoding='utf-8')
    (build / 'rectangular-bounds.json').write_text(json.dumps({'bounds': EXPECTED_BOUNDS}, indent=2) + '\n', encoding='utf-8')
    (build / 'map-data-7.3.6-dem-config.js').write_text(
        MARKER + json.dumps({'center': EXPECTED_CENTER, 'regionalDem': {'minzoom': 7, 'maxzoom': 10, 'tileSize': 256}}, separators=(',', ':')) + ';\n',
        encoding='utf-8',
    )
    print(json.dumps({'version': VERSION, 'baseVersion': data.get('version'), 'bounds': EXPECTED_BOUNDS, 'center': EXPECTED_CENTER, 'targetTileSize': 256, 'physicalNativeZooms': [7,8,9,10]}, indent=2))


def patch_map_data(data: dict, dem_bytes: int, dem_sha256: str) -> dict:
    validate_geography(data)
    for key in ('version', 'applicationVersion', 'stage'):
        data[key] = VERSION
    data['dataVersion'] = DATA_VERSION
    runtime_loading = data.setdefault('runtimeLoading', {})
    runtime_loading['version'] = VERSION
    runtime_loading['terrainLoading'] = 'maplibre-native-visible-tiles-only'
    runtime_loading['manualTilePrefetch'] = False

    dem = data.get('regionalDem')
    if not isinstance(dem, dict):
        raise RuntimeError('regionalDem missing')
    dem.update({
        'available': True,
        'archivePath': NEW_DEM,
        'archiveBytes': dem_bytes,
        'archiveSha256': dem_sha256,
        'tileSize': 256,
        'minzoom': 7,
        'maxzoom': 10,
        'encoding': 'mapbox',
        'heightQuantizationM': 5,
        'lodModel': LOD_MODEL,
        'highestNativeZoom': 10,
        'overzoomFrom': 10,
        'physicalNativeZooms': [7, 8, 9, 10],
        'nativeZ8': True,
        'runtimeNativeZooms': [7, 8, 9, 10],
        'runtimeNetworkLevels': 4,
        'runtimeTerrainSources': 1,
        'z8RuntimeMode': 'native-sequential-from-z9',
        'z8RequestsEnabled': True,
        'transitionMode': 'maplibre-native-single-source',
        'terrainRuntime': 'maplibre-native-single-source',
        'terrainController': False,
        'geometryGeneralization': GENERALIZATION,
        'horizontalGroundResolutionApproxM': 110.644,
        'physicalGroundMPerPixelAtCenter': RESOLUTION,
        'effectiveGroundMPerInformationPixelAtCenter': RESOLUTION,
    })
    dem.pop('reusedFrom', None)
    return data


def patch_runtime_payloads(dem_bytes: int, dem_sha256: str) -> None:
    source_data = patch_map_data(read_source_parts(), dem_bytes, dem_sha256)
    write_source_parts(source_data)
    core = patch_map_data(parse_wrapped(ROOT / 'assets/map-data-core.js', MARKER), dem_bytes, dem_sha256)
    write_wrapped(ROOT / 'assets/map-data-core.js', MARKER, core)
    for filename, marker in [
        ('assets/map-data-deferred.js', 'window.ALAN_MAP_DEFERRED_DATA = '),
        ('assets/map-data-points.js', 'window.ALAN_MAP_POINT_DATA = '),
    ]:
        path = ROOT / filename
        payload = parse_wrapped(path, marker)
        payload['version'] = VERSION
        write_wrapped(path, marker, payload)


def patch_bootstrap() -> None:
    path = ROOT / 'assets/bootstrap.js'
    text = path.read_text(encoding='utf-8')
    text = replace_required(text, "const RELEASE = '7.3.5';", "const RELEASE = '7.3.6';", 'bootstrap release')
    text = replace_required(text, "    'terrain-reset-config-7.3.5.js',\n", '', 'remove terrain-reset runtime patch')
    path.write_text(text, encoding='utf-8')


def patch_map_page() -> None:
    path = ROOT / 'assets/map-page.js'
    text = path.read_text(encoding='utf-8')
    text = replace_required(text, "const VERSION = '7.3.3';", "const VERSION = '7.3.6';", 'map-page version')
    text = replace_required(text, "  const PREFETCH_NEIGHBORS = Object.freeze([[1,0],[-1,0],[0,1],[0,-1]]);\n", '', 'prefetch neighbors')
    for line in ['    prefetchRuns:0,\n', '    prefetchedTiles:0,\n', '    prefetchErrors:0,\n', '    prefetchEnabled:false,\n']:
        text = replace_required(text, line, '', f'remove {line.strip()}')
    text = regex_replace_required(text, r"  function lonToTileX\(lon, zoom\) \{.*?\n  function isMobileTransportProfile\(\) \{", "  function isMobileTransportProfile() {", 'remove tile coordinate prefetch helpers', re.S)
    text = regex_replace_required(text, r"\n  function canPrefetch\(\) \{.*?\n  function waitForRetry\(delayMs, signal\) \{", "\n  function waitForRetry(delayMs, signal) {", 'remove canPrefetch', re.S)
    text = regex_replace_required(text, r"\n  function scheduleIdle\(callback\) \{.*?\n  function installRenderMetrics\(map\) \{", "\n  function installRenderMetrics(map) {", 'remove manual prefetch runtime', re.S)
    text = text.replace(',prefetch:true', '').replace(',prefetch:false', '')
    text = regex_replace_required(text, r"\n    window\.ALAN_MAP_PREFETCH_PM_TILE = async \(\{archivePath,z,x,y,reason='runtime'\}\) => \{.*?\n    \};\n\n    const prepareSnowSource", "\n    const prepareSnowSource", 'remove ALAN_MAP_PREFETCH_PM_TILE', re.S)
    text = replace_required(text, "    if (map) {\n      installRenderMetrics(map);\n      map.once('idle',() => {\n        scheduleIdle(() => {\n          performanceState.prefetchEnabled = installPrefetch(map,archiveRecords,data);\n        });\n      });\n    }", "    if (map) installRenderMetrics(map);", 'remove startup prefetch scheduling')
    for line in ['        prefetchRuns:performanceState.prefetchRuns,\n', '        prefetchedTiles:performanceState.prefetchedTiles,\n', '        prefetchErrors:performanceState.prefetchErrors,\n', '        prefetchEnabled:performanceState.prefetchEnabled,\n']:
        text = replace_required(text, line, '', f'remove diagnostics {line.strip()}')
    if 'installPrefetch' in text or 'PREFETCH_NEIGHBORS' in text or 'ALAN_MAP_PREFETCH_PM_TILE' in text:
        raise RuntimeError('manual prefetch tokens remain in map-page.js')
    path.write_text(text, encoding='utf-8')


def patch_map_ui() -> None:
    path = ROOT / 'assets/map-ui.js'
    text = path.read_text(encoding='utf-8')
    text = replace_required(text, "const VERSION = '7.3.3';", "const VERSION = '7.3.6';", 'map-ui version')
    text = replace_required(text, "const DEFAULT_STORAGE_KEY = 'alan-map-stage7.3.3-view';", "const DEFAULT_STORAGE_KEY = 'alan-map-stage7.3.6-view';", 'storage key')
    legacy_marker = '  const LEGACY_STORAGE_KEYS = [\n'
    if "'alan-map-stage7.3.5-view'," not in text:
        text = replace_required(text, legacy_marker, legacy_marker + "    'alan-map-stage7.3.5-view',\n    'alan-map-stage7.3.4-view',\n", 'legacy storage migration')
    text = replace_required(text, "const CAMERA_LIMITS = Object.freeze({minZoom: 7.0, maxZoom: 14.3, minPitch: 0, maxPitch: 60});", "const CAMERA_LIMITS = Object.freeze({minZoom: 7.0, maxZoom: 14.3, minPitch: 45, maxPitch: 60});", 'camera limits')
    text = replace_required(text, "!Number.isFinite(pitch) || pitch < CAMERA_LIMITS.minPitch || pitch > CAMERA_LIMITS.maxPitch ||", "!Number.isFinite(pitch) || pitch < 0 || pitch > CAMERA_LIMITS.maxPitch ||", 'persisted pitch acceptance')
    text = replace_required(text, "      pitch,\n      relief,", "      pitch: clamp(pitch, CAMERA_LIMITS.minPitch, CAMERA_LIMITS.maxPitch),\n      relief,", 'persisted pitch clamp')
    text = replace_required(text, "balanced: {mode: 'balanced', pixelRatio: 1.75, maxTileCacheZoomLevels: 5, maxTileCacheSize: 128, maxCanvasSize: 6144, antialias: false, forestPattern: true}", "balanced: {mode: 'balanced', pixelRatio: 1.5, maxTileCacheZoomLevels: 5, maxTileCacheSize: 128, maxCanvasSize: 6144, antialias: false, forestPattern: false}", 'balanced quality')
    marker = '  function taggedFeatureCollection(entries) {\n'
    hillshade_function = """  function hillshadeExaggerationExpression(relief) {\n    const factor = clamp(Number(relief) / 2.8, 0.35, 1.5);\n    const scaled = (value) => clamp(value * factor, 0, 1);\n    return ['interpolate',['linear'],['zoom'],7,scaled(0.80),8,scaled(0.74),9,scaled(0.68),10,scaled(0.62),12,scaled(0.57),14.3,scaled(0.54)];\n  }\n\n"""
    if 'function hillshadeExaggerationExpression' not in text:
        text = replace_required(text, marker, hillshade_function + marker, 'hillshade expression helper')
    text = replace_required(text, "'hillshade-exaggeration':0.62", "'hillshade-exaggeration':hillshadeExaggerationExpression(state.relief)", 'style hillshade expression')
    text = replace_required(text, '      relief: 2.55,', '      relief: 2.8,', 'default relief')
    text = replace_required(text, "if (map.getLayer('terrain-hillshade')) map.setPaintProperty('terrain-hillshade','hillshade-exaggeration',Math.min(.82,.34+numericValue*.12));", "if (map.getLayer('terrain-hillshade')) map.setPaintProperty('terrain-hillshade','hillshade-exaggeration',hillshadeExaggerationExpression(numericValue));", 'runtime hillshade expression')
    text = replace_required(text, "          maxZoom:CAMERA_LIMITS.maxZoom,\n          maxPitch:CAMERA_LIMITS.maxPitch,", "          maxZoom:CAMERA_LIMITS.maxZoom,\n          minPitch:CAMERA_LIMITS.minPitch,\n          maxPitch:CAMERA_LIMITS.maxPitch,", 'MapLibre minPitch')
    if "terrain: {source:'terrain-dem',exaggeration:state.relief}" not in text:
        raise RuntimeError('initial persistent terrain is missing')
    path.write_text(text, encoding='utf-8')


def patch_index() -> None:
    path = ROOT / 'index.html'
    text = path.read_text(encoding='utf-8')
    if '7.3.5' not in text:
        raise RuntimeError('index.html has no 7.3.5 marker')
    text = text.replace('7.3.5', VERSION)
    text = text.replace('Terrain Reset', 'Fast Persistent 3D')
    text = text.replace('native MapLibre terrain reset; one raster-dem source, one hillshade, no custom terrain controller.', 'persistent native MapLibre 3D; Z7-Z10 DEM, overzoom after Z10, no manual tile prefetch.')
    path.write_text(text, encoding='utf-8')


def patch_readme() -> None:
    (ROOT / 'README.md').write_text(f'''# Alan Map {VERSION}\n\n{VERSION} сохраняет визуальную и навигационную архитектуру 7.3.5, но упрощает рельеф и стартовую загрузку.\n\n## Terrain\n\n- один `raster-dem` source `terrain-dem`;\n- один MapLibre `terrain`, активный непосредственно в initial style;\n- физические DEM уровни только Z7, Z8, Z9, Z10;\n- Z11–Z14.3 используют overzoom Z10 и не добавляют новую геометрию;\n- Terrain-RGB 256×256;\n- высоты квантованы с шагом 5 м;\n- уровни строятся последовательно: Copernicus GLO-30 → Z10 → Z9 → Z8 → Z7.\n\n## Постоянный 3D\n\nКамера стартует с pitch 58°, минимальный pitch ограничен 45°, максимальный — 60°. Сохранённые старые состояния с меньшим pitch автоматически поднимаются до 45°. Рельеф по умолчанию 2.8×. Hillshade сильнее на дальнем масштабе и плавно ослабевает к ближнему без JS-переключения terrain.\n\n## Загрузка\n\nPMTiles продолжает работать через HTTP Range, общий LRU cache, NetworkGate и retry. Ручная подкачка соседних DEM/vector tiles удалена: MapLibre запрашивает только реально необходимые tiles. Snow, regional label textures и point objects остаются deferred.\n\nВекторный архив остаётся `data/alan-vector-7.2.pmtiles`, снег — `data/alan-snow-7.3.1.pmtiles`.\n''', encoding='utf-8')


def patch_reports(dem_bytes: int, dem_sha256: str, build_report: dict, validation_report: dict, collar_report: dict) -> None:
    runtime_report = {
        'version': VERSION,
        'baseVersion': BASE_BRANCH_VERSION,
        'demArchivePath': NEW_DEM,
        'demArchiveBytes': dem_bytes,
        'demTileSize': 256,
        'demPhysicalNativeZooms': [7,8,9,10],
        'demOverzoomFrom': 10,
        'heightQuantizationM': 5,
        'terrainInitialStyleEnabled': True,
        'terrainSourceSwitching': False,
        'manualTilePrefetch': False,
        'minPitch': 45,
        'defaultPitch': 58,
        'defaultRelief': 2.8,
        'deferredDataScript': 'assets/map-data-deferred.js',
        'deferredPointsScript': 'assets/map-data-points.js',
        'snowSourceDeferredUntilFirstIdle': True,
    }
    (ROOT / 'data/runtime-loading-report-7.3.6.json').write_text(json.dumps(runtime_report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    lod_report = {
        'version': VERSION,
        'archive': NEW_DEM,
        'bytes': dem_bytes,
        'sha256': dem_sha256,
        'tileSize': 256,
        'heightQuantizationM': 5,
        'physicalNativeZooms': [7,8,9,10],
        'highestNativeZoom': 10,
        'overzoomFrom': 10,
        'lodModel': LOD_MODEL,
        'numericLineage': GENERALIZATION,
        'physicalGroundMPerPixelAtCenter': RESOLUTION,
        'effectiveGroundMPerInformationPixelAtCenter': RESOLUTION,
        'build': build_report,
        'validation': validation_report,
        'edgeCollar': collar_report,
    }
    (ROOT / 'data/dem-lod-report-7.3.6.json').write_text(json.dumps(lod_report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    manifest_path = ROOT / 'data/copernicus-build-manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    manifest['version'] = VERSION
    dem = manifest.setdefault('dem', {})
    dem.update({
        'archive': NEW_DEM,
        'bytes': dem_bytes,
        'sha256': dem_sha256,
        'tile_size': 256,
        'lod_model': LOD_MODEL,
        'native_zoom_range': 'z7-z10',
        'physical_native_zooms': [7,8,9,10],
        'overzoom_from': 10,
        'height_quantization_m': 5,
        'numeric_lineage': GENERALIZATION,
        'physical_ground_m_per_pixel_at_center': RESOLUTION,
        'effective_ground_m_per_information_pixel_at_center': RESOLUTION,
    })
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def patch_tests() -> None:
    runtime = ROOT / 'tests/runtime-contract.mjs'
    text = runtime.read_text(encoding='utf-8').replace('7.3.3', VERSION)
    replacements = [
        ("assert.match(page, /installPrefetch/);", "assert.ok(!page.includes('installPrefetch'));"),
        ("assert.match(page, /prefetchEnabled/);", "assert.ok(!page.includes('prefetchEnabled'));"),
        ("assert.equal(runtimeLoadingReport.version,'7.3.6');\nassert.ok(runtimeLoadingReport.initialDataRawReductionPercent > 85);\nassert.ok(runtimeLoadingReport.initialDataGzipReductionPercent > 80);\nassert.equal(runtimeLoadingReport.objectsFeatureCount,779);\nassert.equal(runtimeLoadingReport.deferredPointFeatureCount,829);\nassert.equal(runtimeLoadingReport.deferredRegionalLabelImageCount,16);", "assert.equal(runtimeLoadingReport.version,'7.3.6');\nassert.equal(runtimeLoadingReport.manualTilePrefetch,false);\nassert.equal(runtimeLoadingReport.terrainInitialStyleEnabled,true);\nassert.equal(runtimeLoadingReport.minPitch,45);"),
        ("assert.equal(data.regionalDem.lodModel, 'physical-z7-z9-z10-three-level-512-overzoom');", f"assert.equal(data.regionalDem.lodModel, '{LOD_MODEL}');\nassert.deepEqual(data.regionalDem.physicalNativeZooms,[7,8,9,10]);\nassert.equal(data.regionalDem.runtimeTerrainSources,1);\nassert.equal(data.regionalDem.terrainController,false);"),
        ("assert.equal(data.regionalDem.heightQuantizationM, 1);", "assert.equal(data.regionalDem.heightQuantizationM, 5);"),
        ("assert.equal(data.regionalDem.tileSize, 512);", "assert.equal(data.regionalDem.tileSize, 256);"),
        ("assert.equal(data.regionalDem.geometryGeneralization, 'hierarchical-area-lowpass-z10-to-z9-z7-shared-no-native-z8');", f"assert.equal(data.regionalDem.geometryGeneralization, '{GENERALIZATION}');"),
        ("assert.deepEqual(data.regionalDem.effectiveGroundMPerInformationPixelAtCenter, {'7':442.574,'8':442.574,'9':221.287,'10':110.644});", "assert.deepEqual(data.regionalDem.effectiveGroundMPerInformationPixelAtCenter, {'7':885.148,'8':442.574,'9':221.287,'10':110.644});"),
        ("assert.ok(fs.statSync(data.regionalDem.archivePath).size < 18247328);", "assert.ok(fs.statSync(data.regionalDem.archivePath).size < 30000000);"),
        ("assert.equal(data.dataVersion, '7.3.1-dem-hierarchical-512-z10.1');", f"assert.equal(data.dataVersion, '{DATA_VERSION}');"),
    ]
    for old, new in replacements:
        if old in text:
            text = text.replace(old, new)
    runtime.write_text(text, encoding='utf-8')

    smoke = ROOT / 'tests/map-smoke.mjs'
    smoke_text = smoke.read_text(encoding='utf-8').replace('7.3.3', VERSION)
    smoke.write_text(smoke_text, encoding='utf-8')

    terrain_test = ROOT / 'tests/terrain-architecture-7.3.6.mjs'
    terrain_test.write_text(r'''import fs from 'node:fs';
import assert from 'node:assert/strict';

const marker='window.ALAN_MAP_DATA = ';
const wrapped=fs.readFileSync('assets/map-data-core.js','utf8').trim();
const data=JSON.parse(wrapped.slice(marker.length,-1));
const ui=fs.readFileSync('assets/map-ui.js','utf8');
const page=fs.readFileSync('assets/map-page.js','utf8');
const bootstrap=fs.readFileSync('assets/bootstrap.js','utf8');

assert.equal(data.version,'7.3.6');
assert.equal(data.regionalDem.archivePath,'data/alan-dem-7.3.6.pmtiles');
assert.deepEqual(data.regionalDem.physicalNativeZooms,[7,8,9,10]);
assert.equal(data.regionalDem.maxzoom,10);
assert.equal(data.regionalDem.overzoomFrom,10);
assert.equal(data.regionalDem.tileSize,256);
assert.equal(data.regionalDem.heightQuantizationM,5);
assert.equal(data.regionalDem.runtimeTerrainSources,1);
assert.equal(data.regionalDem.transitionMode,'maplibre-native-single-source');
assert.equal(data.regionalDem.terrainController,false);
assert.match(ui,/minPitch: 45/);
assert.match(ui,/pitch: 58/);
assert.match(ui,/relief: 2\.8/);
assert.match(ui,/terrain: \{source:'terrain-dem',exaggeration:state\.relief\}/);
assert.match(ui,/hillshadeExaggerationExpression/);
assert.match(ui,/minPitch:CAMERA_LIMITS\.minPitch/);
assert.ok(!page.includes('installPrefetch'));
assert.ok(!page.includes('PREFETCH_NEIGHBORS'));
assert.ok(!page.includes('ALAN_MAP_PREFETCH_PM_TILE'));
assert.match(page,/class RangeLruCache/);
assert.match(page,/class NetworkGate/);
assert.match(page,/class InstrumentedRangeSource/);
assert.ok(!bootstrap.includes('terrain-reset-config-7.3.5.js'));
assert.match(bootstrap,/const RELEASE = '7\.3\.6'/);
console.log('terrain-architecture-7.3.6: ok');
''', encoding='utf-8')


def validate_runtime_references() -> None:
    bootstrap = (ROOT / 'assets/bootstrap.js').read_text(encoding='utf-8')
    ui = (ROOT / 'assets/map-ui.js').read_text(encoding='utf-8')
    page = (ROOT / 'assets/map-page.js').read_text(encoding='utf-8')
    index = (ROOT / 'index.html').read_text(encoding='utf-8')
    if 'terrain-reset-config-7.3.5.js' in bootstrap:
        raise RuntimeError('bootstrap still loads 7.3.5 terrain reset patch')
    if "terrain: {source:'terrain-dem',exaggeration:state.relief}" not in ui:
        raise RuntimeError('persistent initial terrain missing')
    if 'minPitch:CAMERA_LIMITS.minPitch' not in ui or 'minPitch: 45' not in ui:
        raise RuntimeError('minimum pitch contract missing')
    if 'installPrefetch' in page or 'PREFETCH_NEIGHBORS' in page or 'ALAN_MAP_PREFETCH_PM_TILE' in page:
        raise RuntimeError('manual PMTiles prefetch remains')
    if VERSION not in bootstrap or VERSION not in page or VERSION not in index:
        raise RuntimeError('runtime version markers incomplete')
    data = parse_wrapped(ROOT / 'assets/map-data-core.js', MARKER)
    validate_geography(data)
    dem = data['regionalDem']
    expected = {
        'archivePath': NEW_DEM,
        'tileSize': 256,
        'minzoom': 7,
        'maxzoom': 10,
        'highestNativeZoom': 10,
        'overzoomFrom': 10,
        'heightQuantizationM': 5,
        'runtimeTerrainSources': 1,
        'transitionMode': 'maplibre-native-single-source',
        'terrainController': False,
    }
    for key, value in expected.items():
        if dem.get(key) != value:
            raise RuntimeError(f'runtime DEM contract mismatch: {key}={dem.get(key)!r}, expected {value!r}')
    if dem.get('physicalNativeZooms') != [7,8,9,10]:
        raise RuntimeError('runtime DEM native zooms are not z7-z10')


def finalize(dem_path: Path, build_report_path: Path, validation_report_path: Path, collar_report_path: Path) -> None:
    for path in (dem_path, build_report_path, validation_report_path, collar_report_path):
        if not path.exists() or path.stat().st_size <= 0:
            raise RuntimeError(f'missing 7.3.6 build output: {path}')
    build_report = json.loads(build_report_path.read_text(encoding='utf-8'))
    validation_report = json.loads(validation_report_path.read_text(encoding='utf-8'))
    collar_report = json.loads(collar_report_path.read_text(encoding='utf-8'))
    if build_report.get('tile_size') != 256 or build_report.get('physical_native_zooms') != [7,8,9,10]:
        raise RuntimeError('builder contract mismatch')
    if build_report.get('height_quantization_m') != 5.0:
        raise RuntimeError('builder height quantization mismatch')
    if not validation_report.get('valid') or validation_report.get('native_zooms') != [7,8,9,10]:
        raise RuntimeError('DEM validation failed')
    if validation_report.get('tile_size') != 256 or not validation_report.get('no_native_tiles_after_z10'):
        raise RuntimeError('DEM validation did not prove z10 overzoom contract')
    target = ROOT / NEW_DEM
    if dem_path.resolve() != target.resolve():
        shutil.copy2(dem_path, target)
    dem_bytes = target.stat().st_size
    dem_sha256 = sha256(target)

    patch_bootstrap()
    patch_map_page()
    patch_map_ui()
    patch_index()
    patch_runtime_payloads(dem_bytes, dem_sha256)
    patch_readme()
    patch_reports(dem_bytes, dem_sha256, build_report, validation_report, collar_report)
    patch_tests()
    validate_runtime_references()
    print(json.dumps({'version': VERSION, 'demArchive': NEW_DEM, 'demBytes': dem_bytes, 'demSha256': dem_sha256, 'tileSize': 256, 'physicalNativeZooms': [7,8,9,10], 'heightQuantizationM': 5, 'persistent3D': True, 'minPitch': 45, 'manualTilePrefetch': False}, indent=2))


def validate() -> None:
    validate_runtime_references()
    dem_path = ROOT / NEW_DEM
    if not dem_path.exists() or dem_path.stat().st_size <= 0:
        raise RuntimeError('7.3.6 DEM archive missing')
    for path in [ROOT / 'data/dem-lod-report-7.3.6.json', ROOT / 'data/runtime-loading-report-7.3.6.json', ROOT / 'tests/terrain-architecture-7.3.6.mjs']:
        if not path.exists() or path.stat().st_size <= 0:
            raise RuntimeError(f'missing 7.3.6 release file: {path}')
    print(json.dumps({'version': VERSION, 'valid': True, 'demBytes': dem_path.stat().st_size}, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description='Prepare/finalize Alan Map 7.3.6 fast persistent 3D release.')
    subparsers = parser.add_subparsers(dest='command', required=True)
    subparsers.add_parser('prepare')
    finalize_parser = subparsers.add_parser('finalize')
    finalize_parser.add_argument('--dem', type=Path, required=True)
    finalize_parser.add_argument('--build-report', type=Path, required=True)
    finalize_parser.add_argument('--validation-report', type=Path, required=True)
    finalize_parser.add_argument('--collar-report', type=Path, required=True)
    subparsers.add_parser('validate')
    args = parser.parse_args()
    if args.command == 'prepare':
        prepare()
    elif args.command == 'finalize':
        finalize(args.dem, args.build_report, args.validation_report, args.collar_report)
    else:
        validate()


if __name__ == '__main__':
    main()
