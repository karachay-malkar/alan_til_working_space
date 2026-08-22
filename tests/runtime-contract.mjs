import fs from 'node:fs';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const bootstrap = fs.readFileSync('assets/bootstrap.js','utf8');
const coreSource = fs.readFileSync('assets/map-core.js','utf8');
const uiSource = fs.readFileSync('assets/map-ui.js','utf8');
const page = fs.readFileSync('assets/map-page.js','utf8');
const dataSource = fs.readFileSync('assets/map-data.part-000.js','utf8') + fs.readFileSync('assets/map-data.part-001.js','utf8');
const runtimeDataSource = fs.readFileSync('assets/map-data-core.js','utf8');
const deferredDataSource = fs.readFileSync('assets/map-data-deferred.js','utf8');
const deferredPointsSource = fs.readFileSync('assets/map-data-points.js','utf8');
const runtimeLoadingReport = JSON.parse(fs.readFileSync('data/runtime-loading-report-7.3.6.json','utf8'));
const indexSource = fs.readFileSync('index.html','utf8');
const nameReview = JSON.parse(fs.readFileSync('data/settlement-name-review-7.2.4.json','utf8'));

assert.match(uiSource, /const VERSION = '7\.3\.6'/);
assert.ok(!bootstrap.includes('fantasy-relief.js'));
assert.ok(!bootstrap.includes('fantasy-style.js'));
assert.ok(!fs.existsSync('assets/fantasy-relief.js'));
assert.ok(!fs.existsSync('assets/fantasy-style.js'));
assert.match(uiSource, /data\.regionalDem\.encoding \|\| 'terrarium'/);
assert.match(uiSource, /copernicus-landcover/);
assert.match(page, /regionalLandcover\?\.archivePath/);
assert.match(page, /regionalSnow\?\.available/);
assert.match(uiSource, /satellite-snow/);
assert.ok(!uiSource.includes('satellite-snow-permanent'));
assert.ok(!uiSource.includes('satellite-snow-seasonal'));
assert.match(uiSource, /if \(!snowTemplate\) natureLayers\.push/);
assert.ok(!uiSource.includes("sources.snow = {type:'raster'"));
assert.match(uiSource,/ensureSnowSource/);
assert.match(uiSource,/ensureDeferredData/);
assert.match(page,/deferredDataScript/);
assert.match(page,/deferredPointsScript/);
assert.match(page,/loadDeferredPoints/);
assert.match(uiSource,/ensureDeferredPoints/);
assert.match(page,/prepareSnowSource/);

assert.ok(!page.includes('ShardedPmtilesSource'));
assert.ok(!page.includes('ShardLruCache'));
assert.ok(!page.includes('shards-manifest.json'));
assert.match(page, /class RangeLruCache/);
assert.match(page, /class NetworkGate/);
assert.match(page, /class InstrumentedRangeSource/);
assert.match(page, /VECTOR_FULL_FILE_FALLBACK_MAX_BYTES/);
assert.match(page, /canUseVectorFullFileFallback/);
assert.match(page, /allowFullFileFallback:vectorFullFileFallbackAllowed/);
assert.match(page, /mode:'adaptive-http-range'/);
assert.match(page, /ALAN_MAP_PERFORMANCE_DIAGNOSTICS/);
assert.ok(!page.includes('installPrefetch'));
assert.match(page, /RANGE_RETRY_DELAYS_MS/);
assert.match(page, /navigator\.maxTouchPoints/);
assert.ok(!page.includes('prefetchEnabled'));
assert.match(indexSource, /bootstrap\.js\?v=7\.3\.6/);
assert.ok(!indexSource.includes('map-presentation-r2.js?v='));
assert.ok(!indexSource.includes('map-presentation.js?v='));
assert.match(bootstrap,/map-presentation-r2\.js/);
assert.match(bootstrap,/map-granite-frame\.js/);
assert.match(bootstrap,/maplibre\.js/);
assert.match(bootstrap,/map-data-core\.js/);
assert.ok(!bootstrap.includes('eval('));
assert.ok(!bootstrap.includes('executeParts'));
assert.ok(!uiSource.includes('updateParchmentOverlay'));
assert.ok(!uiSource.includes("map.on('render',updateParchmentOverlay)"));
assert.ok(!uiSource.includes('if (moving) setVisibility'));
assert.ok(!uiSource.includes('qualityProfile.forestPattern && !moving'));
assert.match(uiSource, /balanced: \{mode: 'balanced'.*?maxTileCacheZoomLevels: 5, maxTileCacheSize: 128/s);
assert.match(uiSource, /high: \{mode: 'high'.*?maxTileCacheZoomLevels: 6, maxTileCacheSize: 192/s);

// Presentation contract: three visual scales only.
const ui = require('../assets/map-ui.js');
const presentation = ui.__test.objectPresentation;
assert.equal(ui.__test.visibilityZoom.DISTANT, 7);
assert.equal(ui.__test.visibilityZoom.CLOSE, 10);
assert.equal(ui.__test.visibilityZoom.DETAIL, 12);
assert.equal(presentation.currentSettlements.minZoom, 10);
assert.equal(presentation.fiveThousanders.minZoom, 10);
assert.equal(presentation.historicSettlements.minZoom, 12);
assert.equal(presentation.historicObjects.minZoom, 12);
assert.equal(presentation.mountainObjects.minZoom, 12);
assert.equal(presentation.passes.minZoom, 12);
assert.equal(presentation.waterObjects.minZoom, 12);
assert.equal(presentation.naturalObjects.minZoom, 12);
assert.equal(presentation.modernObjects.minZoom, 12);

// Point sizes are screen-space constants at every zoom.
assert.deepEqual(ui.__test.pointStyle.large, {diameter:10, radius:4, strokeWidth:1});
assert.deepEqual(ui.__test.pointStyle.small, {diameter:7, radius:2.5, strokeWidth:1});
const fixedPointPaint = ui.__test.pointPaint('large','#000','#fff');
assert.equal(fixedPointPaint['circle-radius'], 4);
assert.equal(fixedPointPaint['circle-stroke-width'], 1);
assert.equal(fixedPointPaint['circle-pitch-scale'], 'viewport');
assert.equal(fixedPointPaint['circle-pitch-alignment'], 'viewport');

// Only five-thousanders from the OSM peak source are rendered, starting at z10.
assert.match(uiSource, /id:'osm-peak-points'.*?minzoom:OBJECT_PRESENTATION\.fiveThousanders\.minZoom.*?\['==',\['get','peak_level'\],1\]/s);
assert.match(uiSource, /id:'osm-peak-labels'.*?minzoom:OBJECT_PRESENTATION\.fiveThousanders\.minZoom.*?\['==',\['get','peak_level'\],1\]/s);
assert.ok(!uiSource.includes("'circle-radius':['match',['get','peak_level']"));

// Regional names are fixed world objects 10000 m above the map plane.
const regional = require('../assets/map-core.js');
assert.equal(regional.config.altitudeM, 10000);
assert.equal(regional.config.minZoom, 7);
assert.equal(regional.config.maxZoom, 10);
assert.equal(regional.config.mapPlaneAligned, true);
assert.equal(regional.config.billboard, false);
assert.equal(regional.config.fixedGroundScale, true);
assert.equal(regional.config.fixedScreenScale, false);
assert.equal(regional.config.sizingModel, 'fixed-world-shared-chegem-font-scale');
assert.equal(regional.config.sharedSizeReferenceId, 'region_chegem');
assert.match(coreSource, /attribute vec3 a_position/);
assert.ok(!coreSource.includes('u_viewport'));
assert.ok(!coreSource.includes('constant-css-pixel-height'));

const mockMapLibre = {
  MercatorCoordinate: {
    fromLngLat({lng,lat}, altitude) {
      return {
        x:lng / 360,
        y:lat / 180,
        z:altitude / 1_000_000,
        meterInMercatorCoordinateUnits:() => 1 / 40_000_000
      };
    }
  }
};
const quad = regional.__test.buildLabelQuad({
  line:[[42,43],[42.2,43.1]],
  midpoint:[42.1,43.05],
  imageWidth:400,
  imageHeight:100,
  worldScale:0.6,
  uv:{left:0,right:1,top:1,bottom:0}
}, mockMapLibre, 10000);
assert.equal(quad.length, 30);
const zValues = Array.from({length:6}, (_,index) => quad[index * 5 + 2]);
assert.ok(zValues.every(value => Math.abs(value - 0.01) < 1e-6));
assert.notEqual(quad[0], quad[5]);
assert.notEqual(quad[1], quad[6]);

const equalSizeLabels = [
  {
    id:'region_chegem',
    line:[[42,43],[42.2,43.1]],
    midpoint:[42.1,43.05],
    imageWidth:400,
    imageHeight:72,
    worldScale:0.533334
  },
  {
    id:'region_basxan',
    line:[[41,43],[43,44]],
    midpoint:[42,43.5],
    imageWidth:650,
    imageHeight:100,
    worldScale:0.533334
  }
];
const sharedMetersPerPixel = regional.__test.resolveSharedLabelMetersPerPixel(equalSizeLabels,mockMapLibre,10000);
assert.ok(sharedMetersPerPixel > 0);
const labelQuads = equalSizeLabels.map(label => regional.__test.buildLabelQuad(label,mockMapLibre,10000,sharedMetersPerPixel));
const quadHeight = value => Math.hypot(value[25] - value[0],value[26] - value[1]);
const quadPixelScales = labelQuads.map((value,index) => quadHeight(value) / equalSizeLabels[index].imageHeight);
assert.ok(Math.abs(quadPixelScales[0] - quadPixelScales[1]) < 1e-8);

const marker = 'window.ALAN_MAP_DATA = ';
let payload = dataSource.slice(dataSource.indexOf(marker) + marker.length).trim();
if (payload.endsWith(';')) payload = payload.slice(0,-1);
const data = JSON.parse(payload);
const parseWrappedPayload = (source, wrapper) => {
  let value = source.slice(source.indexOf(wrapper) + wrapper.length).trim();
  if (value.endsWith(';')) value = value.slice(0,-1);
  return JSON.parse(value);
};
const runtimeData = parseWrappedPayload(runtimeDataSource,'window.ALAN_MAP_DATA = ');
const deferredData = parseWrappedPayload(deferredDataSource,'window.ALAN_MAP_DEFERRED_DATA = ');
const deferredPoints = parseWrappedPayload(deferredPointsSource,'window.ALAN_MAP_POINT_DATA = ');
assert.equal(runtimeData.version,'7.3.6');
assert.equal(runtimeData.applicationVersion,'7.3.6');
assert.equal(runtimeData.stage,'7.3.6');
assert.equal(runtimeData.runtimeLoading?.version,'7.3.6');
assert.equal(runtimeData.runtimeLoading?.maplibreBundle,'assets/maplibre.js');
assert.equal(runtimeData.runtimeLoading?.coreDataScript,'assets/map-data-core.js');
assert.equal(runtimeData.runtimeLoading?.deferredDataScript,'assets/map-data-deferred.js');
assert.equal(runtimeData.runtimeLoading?.deferredPointsScript,'assets/map-data-points.js');
assert.deepEqual(runtimeData.runtimeLoading?.deferredKeys,['regionalLabelImages']);
assert.deepEqual(runtimeData.runtimeLoading?.deferredPointKeys,['objects','modernObjects','passes','peaks','highPeaks']);
assert.equal(runtimeData.runtimeLoading?.snowSourceDeferredUntilFirstIdle,true);
assert.equal(Object.keys(runtimeData.regionalLabelImages || {}).length,0);
assert.equal(deferredData.version,'7.3.6');
assert.equal(Object.keys(deferredData.regionalLabelImages || {}).length,16);
assert.equal(runtimeLoadingReport.version,'7.3.6');
assert.equal(runtimeLoadingReport.manualTilePrefetch,false);
assert.equal(runtimeLoadingReport.terrainInitialStyleEnabled,true);
assert.equal(runtimeLoadingReport.minPitch,45);
assert.equal((runtimeData.objects?.features || []).length,0);
assert.equal((runtimeData.modernObjects?.features || []).length,0);
assert.equal((runtimeData.passes?.features || []).length,0);
assert.equal((runtimeData.peaks?.features || []).length,0);
assert.equal((runtimeData.highPeaks?.features || []).length,0);
assert.equal(deferredPoints.version,'7.3.6');
const deferredActiveSettlements=(deferredPoints.objects?.features || []).filter(feature =>
  feature.properties?.object_type === 'settlement' && feature.properties?.object_subtype !== 'historic_settlement'
);
assert.equal(deferredActiveSettlements.length,532);
assert.ok(deferredActiveSettlements.every(feature => !('source_catalog' in (feature.properties || {}))));
assert.ok(deferredActiveSettlements.every(feature => 'description_ru' in (feature.properties || {})));
assert.match(uiSource,/pointsSource\?\.setData/);
assert.match(uiSource,/deferredPointsLoadZoom/);
assert.equal(data.version, '7.3.6');
assert.equal(data.applicationVersion, '7.3.6');
assert.equal(data.stage, '7.3.6');
assert.equal(data.regionalDem.source, 'Copernicus DEM GLO-30');
assert.equal(data.regionalDem.encoding, 'mapbox');

assert.equal(data.regionalDem.streamingMode, 'http-range');
assert.equal(data.regionalDem.lodModel, 'single-pyramid-native-z7-z10-overzoom-z10');
assert.deepEqual(data.regionalDem.physicalNativeZooms,[7,8,9,10]);
assert.equal(data.regionalDem.runtimeTerrainSources,1);
assert.equal(data.regionalDem.terrainController,false);
assert.equal(data.regionalDem.heightQuantizationM, 5);
assert.equal(data.regionalDem.archivePath, 'data/alan-dem-7.3.6.pmtiles');
assert.equal(data.regionalDem.maxzoom, 10);
assert.equal(data.regionalDem.tileSize, 256);
assert.equal(data.regionalDem.highestNativeZoom, 10);
assert.equal(data.regionalDem.overzoomFrom, 10);
assert.equal(data.regionalDem.geometryGeneralization, 'sequential-z10-z9-z8-z7-area-average-5m');
assert.deepEqual(data.regionalDem.effectiveGroundMPerInformationPixelAtCenter, {'7':885.148,'8':442.574,'9':221.287,'10':110.644});
assert.equal(ui.__test.demEdgeCollarM,4500);
assert.equal(ui.__test.demEdgeSafeMaxM,1000);
assert.equal(ui.__test.demEdgeInnerBandM,900);
assert.equal(ui.__test.demEdgeOuterSkirtM,3200);
assert.equal(ui.__test.demTechnicalBaseM,-10000);
const expandedDemBounds=ui.__test.expandedDemBounds(data.regionalDem.bounds);
assert.ok(expandedDemBounds[0] < data.regionalDem.bounds[0]);
assert.ok(expandedDemBounds[1] < data.regionalDem.bounds[1]);
assert.ok(expandedDemBounds[2] > data.regionalDem.bounds[2]);
assert.ok(expandedDemBounds[3] > data.regionalDem.bounds[3]);
assert.match(uiSource,/terrain-dem'.*?bounds:expandedDemBounds\(data\.regionalDem\.bounds\)/s);
assert.equal(data.regionalVector.streamingMode, 'http-range');
assert.equal(data.regionalVector.archivePath, 'data/alan-vector-7.2.pmtiles');
assert.ok(!fs.existsSync('data/shards-manifest.json'));
assert.ok(!fs.existsSync('data/shards'));
assert.ok(fs.existsSync(data.regionalDem.archivePath));
assert.ok(fs.existsSync(data.regionalVector.archivePath));
assert.ok(fs.statSync(data.regionalDem.archivePath).size < 30000000);
assert.equal(fs.statSync(data.regionalVector.archivePath).size, 16913027);
const ring = data.mapFrame.features[0].geometry.coordinates[0];
const expectedRing = [
  [40.51784,43.41265],
  [43.731622,42.734095],
  [44.184003,43.85642],
  [40.970221,44.534975],
  [40.51784,43.41265]
];
assert.deepEqual(ring, expectedRing);
const xs = ring.slice(0,-1).map(p => p[0]);
const ys = ring.slice(0,-1).map(p => p[1]);
assert.deepEqual(data.bounds, [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)]);
assert.deepEqual(data.bounds, [40.51784,42.734095,44.184003,44.534975]);
assert.deepEqual(data.center, [42.350921,43.634535]);
assert.deepEqual(data.focus.features[0].geometry.coordinates[0], expectedRing);
assert.equal(data.frameMask.features[0].geometry.coordinates.length, 2);
assert.deepEqual(data.frameMask.features[0].geometry.coordinates[1], [...expectedRing].reverse());
const runtimeSources = ui.__test.buildRuntimeSourceData(data);
assert.ok(runtimeSources.polygons.features.some(feature => feature.properties?.alan_source === 'frameMask'));
assert.match(uiSource, /id:'frame-mask'.*?sourceFilter\('frameMask'\)/s);
assert.ok(!uiSource.includes('osm-river-halo'));
assert.equal(ui.__test.regionalLabelAltitudeM, 10000);
assert.equal(ui.__test.regionalLabelNarsanaScale, 0.533334);
const regionalScales = new Set((data.regionalLabels?.features || []).map(feature => Number(feature.properties?.display_icon_scale)));
assert.deepEqual([...regionalScales], [0.533334]);
assert.equal(data.regionalLabels.features.length,16);
assert.equal(data.regionalLabelCatalog?.version,'7.2.4');
assert.equal(data.regionalLabelCatalog?.uniform_scale,0.533334);
assert.deepEqual(data.regionalLabelCatalog?.added_regions,[
  'region_gitche_qarachay',
  'region_cogetey',
  'region_zelenchuk'
]);
const preparedRegionalLabels = data.regionalLabels.features.map(feature => {
  const properties=feature.properties || {};
  const line=regional.__test.resolveLine(feature);
  const dimensions=regional.__test.pngDimensions(data.regionalLabelImages[properties.icon_id]);
  return {
    id:String(properties.label_id),
    line,
    midpoint:regional.__test.lineMidpoint(line),
    imageWidth:dimensions.width,
    imageHeight:dimensions.height,
    worldScale:Number(properties.display_icon_scale)
  };
});
const actualSharedMetersPerPixel=regional.__test.resolveSharedLabelMetersPerPixel(preparedRegionalLabels,mockMapLibre,10000);
const actualMetersPerPixel=preparedRegionalLabels.map(label => {
  const value=regional.__test.buildLabelQuad(label,mockMapLibre,10000,actualSharedMetersPerPixel);
  return quadHeight(value) * 40_000_000 / label.imageHeight;
});
assert.equal(preparedRegionalLabels.find(label => label.id==='region_chegem')?.id,'region_chegem');
assert.ok(Math.max(...actualMetersPerPixel)-Math.min(...actualMetersPerPixel) < .02);
assert.equal(data.settlementCatalog?.version,'7.2.4');
assert.equal(data.settlementCatalog?.active_settlements,532);
assert.equal(data.settlementCatalog?.name_review_required,0);
assert.equal(data.settlementCatalog?.name_review_revision,'7.2.4-r2');
assert.equal(data.settlementCatalog?.active_status_review_required,3);
assert.equal(nameReview.version,'7.2.4');
assert.equal(nameReview.revision,'7.2.4-r2');
assert.equal(nameReview.summary?.settlements,532);
assert.equal(nameReview.summary?.completed,532);
assert.equal(nameReview.summary?.former_provisional,446);
assert.equal(nameReview.summary?.linked_entity_audits,439);
assert.equal(nameReview.summary?.independent_reference_audits,7);
assert.equal(nameReview.summary?.active_status_review_required,3);
assert.equal(new Set(nameReview.settlements.map(record=>record.osm_id)).size,532);
assert.ok(nameReview.settlements.every(record=>record.name_review_status==='completed'));
assert.ok(nameReview.settlements.every(record=>record.name_review_required===0));
assert.ok(nameReview.settlements.every(record=>Array.isArray(record.name_references)&&record.name_references.length>0));
const activeSettlements=(data.objects?.features || []).filter(feature =>
  feature.properties?.object_type === 'settlement' && feature.properties?.object_subtype !== 'historic_settlement'
);
assert.equal(activeSettlements.length,532);
assert.ok(activeSettlements.every(feature => feature.properties?.active === 1));
assert.ok(activeSettlements.every(feature => feature.properties?.source_catalog === 'osm-overpass-2026-08-15'));
assert.ok(activeSettlements.every(feature => !/[А-Яа-яЁё]/.test(feature.properties?.name_alan_latin || '')));
assert.ok(activeSettlements.every(feature => feature.properties?.name_review_status === 'completed'));
assert.ok(activeSettlements.every(feature => feature.properties?.name_review_required === 0));
assert.ok(activeSettlements.every(feature => feature.properties?.ethnographic_profile_status === 'pending'));
assert.ok(!(data.boundaries?.features || []).some(feature => feature.properties?.boundary_id === 'karachay_balkaria_historical_ethnographic_divide'));
assert.ok(!(data.boundaries?.features || []).some(feature => feature.properties?.boundary_type === 'historical_ethnographic'));
assert.equal(runtimeSources.presentation.beamCount, 0);
assert.ok(!runtimeSources.polygons.features.some(feature => feature.properties?.alan_source === 'settlementBeamHalo'));
assert.ok(!runtimeSources.polygons.features.some(feature => feature.properties?.alan_source === 'settlementBeamCore'));
assert.deepEqual(ui.__test.parchmentCorner.corner, [44.184003,43.85642]);
assert.deepEqual(ui.__test.parchmentCorner.edgeA, [43.959202,43.298704]);
assert.deepEqual(ui.__test.parchmentCorner.edgeC, [42.946104,44.117789]);
assert.deepEqual(ui.__test.parchmentCompass, [43.82900045,43.71487991]);
const parchment = ui.__test.parchmentCornerCollections(data);
assert.deepEqual(parchment.tornEdge[0], parchment.anchors.edgeC);
assert.deepEqual(parchment.tornEdge.at(-1), parchment.anchors.edgeA);
assert.equal(parchment.ornament.features.length,0);
assert.equal(parchment.layout.maskGeometry,'fixed-7.2');
assert.equal(parchment.layout.compassIndependent,true);
assert.deepEqual(parchment.compassCoordinates,parchment.layout.compass);
assert.ok(!uiSource.includes("id:'settlement-beam-halo'"));
assert.ok(!uiSource.includes("id:'settlement-beam-core'"));

if (data.regionalSnow?.available) {
  assert.equal(data.regionalSnow.version, '7.3.1');
  assert.equal(data.dataVersion, '7.3.6-dem-z7-z10-256-5m-sequential.1');
  assert.equal(data.regionalSnow.method, 'worldcover-class-70-plus-multiyear-late-summer-ndsi');
  assert.deepEqual(data.regionalSnow.bounds, data.bounds);
  assert.equal(data.regionalSnow.archivePath, 'data/alan-snow-7.3.1.pmtiles');
  assert.equal(data.regionalSnow.minzoom, 8);
  assert.equal(data.regionalSnow.maxzoom, 12);
  assert.equal(data.regionalSnow.archiveMinzoom, 8);
  assert.equal(data.regionalSnow.archiveMaxzoom, 13);
  assert.equal(data.regionalSnow.runtimeMaxzoomReason, 'canonical-z12-overzoom-preserves-snow-footprint');
  assert.equal(data.regionalSnow.displayStrategy, 'canonical-unified-z12-with-multiscale-restoration');
  assert.equal(data.regionalSnow.canonicalDetailZoom, 12);
  assert.equal(data.regionalSnow.sourceArchives.permanent, 'data/alan-snow-permanent-7.2.5.pmtiles');
  assert.equal(data.regionalSnow.sourceArchives.seasonal, 'data/alan-snow-seasonal-7.2.5.pmtiles');
  assert.ok(!('snowGapPermanent' in data));
  assert.ok(!('snowGapSeasonal' in data));
  assert.ok(fs.existsSync(data.regionalSnow.archivePath));
  assert.ok(fs.existsSync(data.regionalSnow.canonicalReportPath));
}

if (data.regionalLandcover?.available) {
  assert.equal(data.regionalLandcover.source, 'Copernicus CLMS LCM-10');
  assert.ok(data.regionalLandcover.archivePath.includes('landcover-7.0.25.pmtiles'));
}

if (fs.existsSync('data/dem-edge-collar-report.json')) {
  const collar = JSON.parse(fs.readFileSync('data/dem-edge-collar-report.json','utf8'));
  assert.equal(collar.version,'7.3.1-r1');
  assert.equal(collar.tile_size,512);
  assert.equal(collar.mode,'hidden-tapered-dem-edge-collar');
  assert.equal(collar.collar_m,4500);
  assert.equal(collar.inner_taper_m,900);
  assert.equal(collar.outer_skirt_m,3200);
  assert.equal(collar.safe_max_elevation_m,1000);
  assert.equal(collar.technical_base_m,-10000);
  assert.equal(collar.rendered_safe_max_m,2550);
  assert.equal(collar.frame_clearance_m,1450);
  assert.equal(collar.terrain_base_drop_removed_near_map_frame,true);
  assert.equal(collar.terrain_above_frame_prevented,true);
  assert.ok(collar.changed_tiles > 0);
  assert.ok(collar.new_tiles > 0);
  assert.ok(collar.collar_pixels > 0);
  assert.ok(collar.inside_capped_pixels > 0);
  assert.ok(collar.outer_descent_pixels > 0);
  assert.ok(collar.per_zoom.every(item => item.maximum_written_height_m <= 1000));
}

console.log('runtime-contract: ok');
