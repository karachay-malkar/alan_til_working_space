#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = '7.3.8'
BASE_VERSION = '7.3.7'
NEW_SNOW_ARCHIVE = 'data/alan-snow-vector-7.3.8.pmtiles'
NEW_SNOW_REPORT = 'data/snow-vector-report-7.3.8.json'
OLD_SNOW_ARCHIVES = [
    'data/alan-snow-7.3.1.pmtiles',
    'data/alan-snow-permanent-7.2.5.pmtiles',
    'data/alan-snow-seasonal-7.2.5.pmtiles',
]


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f'{label}: expected one match, found {count}')
    return text.replace(old, new, 1)


def parse_wrapped_json(path: Path, marker: str) -> dict:
    source = path.read_text(encoding='utf-8')
    start = source.index(marker) + len(marker)
    payload = source[start:].strip()
    if payload.endswith(';'):
        payload = payload[:-1]
    return json.loads(payload)


def write_wrapped_json(path: Path, marker: str, data: dict) -> None:
    path.write_text(marker + json.dumps(data, ensure_ascii=False, separators=(',', ':')) + ';\n', encoding='utf-8')


def patch_versions() -> None:
    bootstrap = ROOT / 'assets/bootstrap.js'
    text = bootstrap.read_text(encoding='utf-8')
    text = replace_once(text, "const RELEASE = '7.3.7';", "const RELEASE = '7.3.8';", 'bootstrap version')
    bootstrap.write_text(text, encoding='utf-8')

    page = ROOT / 'assets/map-page.js'
    text = page.read_text(encoding='utf-8')
    text = replace_once(text, "const VERSION = '7.3.7';", "const VERSION = '7.3.8';", 'map-page version')
    page.write_text(text, encoding='utf-8')

    ui = ROOT / 'assets/map-ui.js'
    text = ui.read_text(encoding='utf-8')
    text = replace_once(text, "const VERSION = '7.3.7';", "const VERSION = '7.3.8';", 'map-ui version')
    text = replace_once(text, "const DEFAULT_STORAGE_KEY = 'alan-map-stage7.3.7-view';", "const DEFAULT_STORAGE_KEY = 'alan-map-stage7.3.8-view';", 'map-ui storage')
    legacy_anchor = "  const LEGACY_STORAGE_KEYS = [\n"
    if legacy_anchor not in text:
        raise RuntimeError('map-ui legacy key anchor missing')
    text = text.replace(legacy_anchor, legacy_anchor + "    'alan-map-stage7.3.7-view',\n", 1)
    ui.write_text(text, encoding='utf-8')

    index = ROOT / 'index.html'
    text = index.read_text(encoding='utf-8')
    text = text.replace('Alan Map 7.3.7 · Fast Persistent 3D', 'Alan Map 7.3.8 · Vector Snow Relief')
    text = text.replace('?v=7.3.7', '?v=7.3.8')
    text = text.replace('Alan Map 7.3.7:', 'Alan Map 7.3.8:')
    index.write_text(text, encoding='utf-8')

    for filename, marker in [
        ('assets/map-data-deferred.js', 'window.ALAN_MAP_DEFERRED_DATA = '),
        ('assets/map-data-points.js', 'window.ALAN_MAP_POINT_DATA = '),
    ]:
        path = ROOT / filename
        data = parse_wrapped_json(path, marker)
        data['version'] = VERSION
        write_wrapped_json(path, marker, data)


def patch_snow_runtime() -> None:
    path = ROOT / 'assets/map-ui.js'
    text = path.read_text(encoding='utf-8')
    old = """        map.addSource('snow',{
          type:'raster',
          url:snowTemplate,
          tileSize:Number(data.regionalSnow.tileSize || 256),
          minzoom:Number(data.regionalSnow.minzoom),
          maxzoom:Number(data.regionalSnow.maxzoom),
          bounds:data.regionalSnow.bounds,
          attribution:data.regionalSnow.attribution
        });
        map.addLayer({
          id:'satellite-snow',
          type:'raster',
          source:'snow',
          minzoom:Number(data.regionalSnow.minzoom),
          paint:{'raster-opacity':0.92,'raster-fade-duration':0,'raster-resampling':'linear'}
        },map.getLayer('ridge-lines') ? 'ridge-lines' : undefined);"""
    new = """        map.addSource('snow',{
          type:'vector',
          url:snowTemplate,
          minzoom:Number(data.regionalSnow.minzoom),
          maxzoom:Number(data.regionalSnow.maxzoom),
          bounds:data.regionalSnow.bounds,
          attribution:data.regionalSnow.attribution
        });
        const snowBeforeId = map.getLayer('ridge-lines') ? 'ridge-lines' : undefined;
        map.addLayer({
          id:'vector-snow-fill',
          type:'fill',
          source:'snow',
          'source-layer':String(data.regionalSnow.sourceLayer || 'snow'),
          minzoom:Number(data.regionalSnow.minzoom),
          paint:{
            'fill-color':'#f8f7f1',
            'fill-opacity':['interpolate',['linear'],['zoom'],7,0.68,10,0.72,12,0.76,14.3,0.78],
            'fill-outline-color':'rgba(202,216,217,0.72)',
            'fill-antialias':true
          }
        },snowBeforeId);
        map.addLayer({
          id:'snow-relief-contours',
          type:'line',
          source:'snow',
          'source-layer':String(data.regionalSnow.contourSourceLayer || 'snow_contour'),
          minzoom:Number(data.regionalSnow.contourMinzoom || 9.5),
          layout:{'line-cap':'round','line-join':'round'},
          paint:{
            'line-color':'rgba(83,102,108,0.34)',
            'line-width':['interpolate',['linear'],['zoom'],9.5,0.28,12,0.48,14.3,0.66],
            'line-opacity':['interpolate',['linear'],['zoom'],9.5,0.20,11,0.30,14.3,0.38]
          }
        },snowBeforeId);"""
    if old not in text:
        raise RuntimeError('current raster snow runtime block not found')
    text = text.replace(old, new, 1)
    if "type:'raster',\n          url:snowTemplate" in text or "raster-resampling':'linear'" in text[text.find('ensureSnowSource'):text.find('function forestPatternImage')]:
        raise RuntimeError('legacy raster snow runtime remains')
    path.write_text(text, encoding='utf-8')


def patch_runtime_data() -> None:
    path = ROOT / 'assets/map-data-core.js'
    data = parse_wrapped_json(path, 'window.ALAN_MAP_DATA = ')
    data['version'] = VERSION
    data['stage'] = VERSION
    data['applicationVersion'] = VERSION
    data['dataVersion'] = '7.3.8-vector-snow-relief.1'
    runtime = data.setdefault('runtimeLoading', {})
    runtime['version'] = VERSION
    runtime['snowSourceDeferredUntilFirstIdle'] = True
    runtime['snowRendering'] = 'vector-fill-z7-z14.3-plus-dem-visible-through-alpha-plus-vector-200m-contours'

    previous = data.get('regionalSnow') or {}
    data['regionalSnow'] = {
        'available': True,
        'version': VERSION,
        'bounds': previous.get('bounds', data.get('bounds')),
        'source': previous.get('source', 'ESA WorldCover 2021 v200 + Sentinel-2 L2A late-summer NDSI consensus'),
        'method': previous.get('method', 'worldcover-class-70-plus-multiyear-late-summer-ndsi'),
        'years': previous.get('years', [2020, 2021, 2023, 2024, 2025]),
        'lateSummerWindow': previous.get('lateSummerWindow', '08-15/09-30'),
        'ndsiThreshold': previous.get('ndsiThreshold', 0.4),
        'permanentConsensus': previous.get('permanentConsensus', 0.6),
        'seasonalConsensusMin': previous.get('seasonalConsensusMin', 0.25),
        'attribution': previous.get('attribution'),
        'streamingMode': 'http-range',
        'tileContainer': 'PMTiles',
        'archivePath': NEW_SNOW_ARCHIVE,
        'minzoom': 7,
        'maxzoom': 13,
        'displayMaxzoom': 14.3,
        'kind': 'vector-snow-polygons',
        'sourceLayer': 'snow',
        'contourSourceLayer': 'snow_contour',
        'contourMinzoom': 9.5,
        'contourIntervalM': 200,
        'displayStrategy': 'crisp-vector-fill-z7-z13-overzoom-to-z14.3-with-relief-through-transparency-and-snow-only-contours',
        'displayNotes': 'Canonical Sentinel-derived snow mask is thresholded to crisp vector polygons. Snow is visible from z7 through the full camera range to z14.3; z13 vector tiles overzoom above z13. Existing DEM hillshade remains visible through the translucent fill; 200 m DEM contours are clipped to snow and appear only from z9.5. No raster blur or raster resampling is used.',
        'sourceMaskVersion': '7.3.1',
        'sourceMaskReport': 'data/snow-canonical-report-7.3.1.json',
        'vectorReportPath': NEW_SNOW_REPORT,
        'binaryAlphaThreshold': 128,
        'minimumPolygonAreaM2': 2500,
        'simplifyM': 10,
    }
    write_wrapped_json(path, 'window.ALAN_MAP_DATA = ', data)


def patch_runtime_report() -> None:
    source = ROOT / 'data/runtime-loading-report-7.3.7.json'
    target = ROOT / 'data/runtime-loading-report-7.3.8.json'
    report = json.loads(source.read_text(encoding='utf-8'))
    report['version'] = VERSION
    report['baseVersion'] = BASE_VERSION
    report['snowSourceDeferredUntilFirstIdle'] = True
    report['snowRuntimeType'] = 'vector'
    report['snowArchivePath'] = NEW_SNOW_ARCHIVE
    report['snowMinzoom'] = 7
    report['snowArchiveMaxzoom'] = 13
    report['snowDisplayMaxzoom'] = 14.3
    report['snowReliefContoursM'] = 200
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def patch_runtime_contract() -> None:
    path = ROOT / 'tests/runtime-contract.mjs'
    text = path.read_text(encoding='utf-8')
    text = text.replace("runtime-loading-report-7.3.7.json", "runtime-loading-report-7.3.8.json")
    replacements = {
        "/const VERSION = '7\\.3\\.7'/": "/const VERSION = '7\\.3\\.8'/",
        "/bootstrap\\.js\\?v=7\\.3\\.7/": "/bootstrap\\.js\\?v=7\\.3\\.8/",
        "assert.equal(runtimeData.version,'7.3.7');": "assert.equal(runtimeData.version,'7.3.8');",
        "assert.equal(runtimeData.applicationVersion,'7.3.7');": "assert.equal(runtimeData.applicationVersion,'7.3.8');",
        "assert.equal(runtimeData.stage,'7.3.7');": "assert.equal(runtimeData.stage,'7.3.8');",
        "assert.equal(runtimeData.runtimeLoading?.version,'7.3.7');": "assert.equal(runtimeData.runtimeLoading?.version,'7.3.8');",
        "assert.equal(deferredData.version,'7.3.7');": "assert.equal(deferredData.version,'7.3.8');",
        "assert.equal(runtimeLoadingReport.version,'7.3.7');": "assert.equal(runtimeLoadingReport.version,'7.3.8');",
        "assert.equal(deferredPoints.version,'7.3.7');": "assert.equal(deferredPoints.version,'7.3.8');",
    }
    for old, new in replacements.items():
        if old not in text:
            raise RuntimeError(f'runtime-contract version anchor missing: {old}')
        text = text.replace(old, new, 1)
    text = text.replace("assert.match(uiSource, /satellite-snow/);", "assert.match(uiSource, /vector-snow-fill/);\nassert.match(uiSource, /snow-relief-contours/);")
    old_assert = "assert.ok(!uiSource.includes(\"sources.snow = {type:'raster'\"));"
    if old_assert in text:
        text = text.replace(old_assert, "assert.ok(!uiSource.includes(\"type:'raster',\\n          url:snowTemplate\"));\nassert.match(uiSource, /type:'vector',\\n          url:snowTemplate/);", 1)

    runtime_snow_anchor = "assert.equal(runtimeData.runtimeLoading?.snowSourceDeferredUntilFirstIdle,true);"
    runtime_snow_contract = """assert.equal(runtimeData.runtimeLoading?.snowSourceDeferredUntilFirstIdle,true);
assert.equal(runtimeData.regionalSnow?.version,'7.3.8');
assert.equal(runtimeData.regionalSnow?.archivePath,'data/alan-snow-vector-7.3.8.pmtiles');
assert.equal(runtimeData.regionalSnow?.minzoom,7);
assert.equal(runtimeData.regionalSnow?.maxzoom,13);
assert.equal(runtimeData.regionalSnow?.displayMaxzoom,14.3);
assert.equal(runtimeData.regionalSnow?.kind,'vector-snow-polygons');
assert.equal(runtimeData.regionalSnow?.sourceLayer,'snow');
assert.equal(runtimeData.regionalSnow?.contourSourceLayer,'snow_contour');
assert.equal(runtimeData.regionalSnow?.contourMinzoom,9.5);
assert.equal(runtimeData.regionalSnow?.contourIntervalM,200);"""
    if runtime_snow_anchor not in text:
        raise RuntimeError('runtime-contract runtime snow anchor missing')
    text = text.replace(runtime_snow_anchor, runtime_snow_contract, 1)

    legacy_archive_assert = "  assert.ok(fs.existsSync(data.regionalSnow.archivePath));"
    if legacy_archive_assert not in text:
        raise RuntimeError('runtime-contract legacy snow archive assertion missing')
    text = text.replace(legacy_archive_assert, "  assert.equal(fs.existsSync(data.regionalSnow.archivePath), false);", 1)
    path.write_text(text, encoding='utf-8')


def update_docs() -> None:
    readme = ROOT / 'README.md'
    text = readme.read_text(encoding='utf-8')
    header = "\n## 7.3.8 — crisp vector snow\n\n- Replaces the runtime raster snow overlay with vector PMTiles polygons derived from the existing Sentinel/WorldCover canonical snow mask.\n- Shows snow continuously from z7 through the full z14.3 camera range, overzooming z13 vector tiles above z13.\n- Removes linear raster resampling and blurred snow edges.\n- Keeps DEM hillshade visible through a translucent snow fill and adds snow-only 200 m elevation contours from z9.5 for readable mountain slopes.\n- Removes the three legacy snow PMTiles archives from the release package.\n"
    if '## 7.3.8 — crisp vector snow' not in text:
        text = text.rstrip() + '\n' + header
    readme.write_text(text, encoding='utf-8')


def finalize(new_archive: Path, report: Path) -> None:
    if not new_archive.exists() or new_archive.stat().st_size <= 0:
        raise RuntimeError(f'New vector snow archive missing: {new_archive}')
    target_archive = ROOT / NEW_SNOW_ARCHIVE
    target_report = ROOT / NEW_SNOW_REPORT
    target_archive.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(new_archive, target_archive)
    shutil.copy2(report, target_report)

    patch_versions()
    patch_snow_runtime()
    patch_runtime_data()
    patch_runtime_report()
    patch_runtime_contract()
    update_docs()

    for relative in OLD_SNOW_ARCHIVES:
        path = ROOT / relative
        if path.exists():
            path.unlink()


def validate() -> None:
    required = [
        ROOT / NEW_SNOW_ARCHIVE,
        ROOT / NEW_SNOW_REPORT,
        ROOT / 'data/alan-dem-7.3.7.pmtiles',
        ROOT / 'data/alan-vector-7.2.pmtiles',
    ]
    for path in required:
        if not path.exists() or path.stat().st_size <= 0:
            raise RuntimeError(f'Required file missing: {path}')
    for relative in OLD_SNOW_ARCHIVES:
        if (ROOT / relative).exists():
            raise RuntimeError(f'Legacy snow archive still exists: {relative}')

    ui = (ROOT / 'assets/map-ui.js').read_text(encoding='utf-8')
    page = (ROOT / 'assets/map-page.js').read_text(encoding='utf-8')
    index = (ROOT / 'index.html').read_text(encoding='utf-8')
    if "const VERSION = '7.3.8';" not in ui or "const VERSION = '7.3.8';" not in page:
        raise RuntimeError('Runtime version was not bumped')
    if 'vector-snow-fill' not in ui or 'snow-relief-contours' not in ui:
        raise RuntimeError('Vector snow layers are missing')
    snow_runtime = ui[ui.index('async function ensureSnowSource'):ui.index('function forestPatternImage')]
    if "type:'raster'" in snow_runtime or 'raster-resampling' in snow_runtime or 'raster-opacity' in snow_runtime:
        raise RuntimeError('Raster snow runtime remains')
    if "type:'vector'" not in snow_runtime or "'source-layer':String(data.regionalSnow.sourceLayer" not in snow_runtime:
        raise RuntimeError('Vector snow source contract missing')
    if '?v=7.3.8' not in index:
        raise RuntimeError('index cache version was not bumped')

    data = parse_wrapped_json(ROOT / 'assets/map-data-core.js', 'window.ALAN_MAP_DATA = ')
    snow = data.get('regionalSnow') or {}
    if snow.get('archivePath') != NEW_SNOW_ARCHIVE or snow.get('kind') != 'vector-snow-polygons':
        raise RuntimeError(f'Unexpected snow metadata: {snow}')
    if snow.get('sourceLayer') != 'snow' or snow.get('contourSourceLayer') != 'snow_contour':
        raise RuntimeError('Snow source layers are incorrect')
    if snow.get('minzoom') != 7 or snow.get('maxzoom') != 13 or snow.get('displayMaxzoom') != 14.3:
        raise RuntimeError(f'Unexpected snow zoom contract: {snow.get("minzoom")}/{snow.get("maxzoom")}/{snow.get("displayMaxzoom")}')
    if data.get('version') != VERSION or data.get('applicationVersion') != VERSION:
        raise RuntimeError('Runtime data version is incorrect')

    print(json.dumps({
        'version': VERSION,
        'snowArchive': NEW_SNOW_ARCHIVE,
        'snowArchiveBytes': (ROOT / NEW_SNOW_ARCHIVE).stat().st_size,
        'snowMinzoom': snow.get('minzoom'),
        'snowArchiveMaxzoom': snow.get('maxzoom'),
        'snowDisplayMaxzoom': snow.get('displayMaxzoom'),
        'legacySnowArchivesRemoved': OLD_SNOW_ARCHIVES,
        'snowLayer': 'vector-snow-fill',
        'snowContours': 'snow-relief-contours',
    }, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='command', required=True)
    finish = sub.add_parser('finalize')
    finish.add_argument('--archive', required=True, type=Path)
    finish.add_argument('--report', required=True, type=Path)
    sub.add_parser('validate')
    args = parser.parse_args()
    if args.command == 'finalize':
        finalize(args.archive, args.report)
        validate()
    else:
        validate()


if __name__ == '__main__':
    main()