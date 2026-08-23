import fs from 'node:fs';
import assert from 'node:assert/strict';

// Release contract for the 7.3.8 snow rebuild.
const ui = fs.readFileSync('assets/map-ui.js','utf8');
const page = fs.readFileSync('assets/map-page.js','utf8');
const core = fs.readFileSync('assets/map-data-core.js','utf8');
const marker = 'window.ALAN_MAP_DATA = ';
let payload = core.slice(core.indexOf(marker) + marker.length).trim();
if (payload.endsWith(';')) payload = payload.slice(0,-1);
const data = JSON.parse(payload);

assert.equal(data.version,'7.3.8');
assert.equal(data.applicationVersion,'7.3.8');
assert.equal(data.regionalSnow.version,'7.3.8');
assert.equal(data.regionalSnow.kind,'vector-snow-polygons');
assert.equal(data.regionalSnow.archivePath,'data/alan-snow-vector-7.3.8.pmtiles');
assert.equal(data.regionalSnow.minzoom,7);
assert.equal(data.regionalSnow.maxzoom,13);
assert.equal(data.regionalSnow.displayMaxzoom,14.3);
assert.equal(data.regionalSnow.sourceLayer,'snow');
assert.equal(data.regionalSnow.contourSourceLayer,'snow_contour');
assert.equal(data.regionalSnow.contourMinzoom,9.5);
assert.equal(data.regionalSnow.contourIntervalM,200);
assert.equal(data.regionalSnow.binaryAlphaThreshold,128);
assert.equal(data.runtimeLoading.snowSourceDeferredUntilFirstIdle,true);
assert.equal(data.runtimeLoading.snowRendering,'vector-fill-z7-z14.3-plus-dem-visible-through-alpha-plus-vector-200m-contours');

const snowStart = ui.indexOf('async function ensureSnowSource');
const snowEnd = ui.indexOf('function forestPatternImage');
assert.ok(snowStart >= 0 && snowEnd > snowStart);
const snowRuntime = ui.slice(snowStart,snowEnd);
assert.match(snowRuntime,/type:'vector'/);
assert.match(snowRuntime,/id:'vector-snow-fill'/);
assert.match(snowRuntime,/id:'snow-relief-contours'/);
assert.match(snowRuntime,/'source-layer':String\(data\.regionalSnow\.sourceLayer/);
assert.match(snowRuntime,/'source-layer':String\(data\.regionalSnow\.contourSourceLayer/);
assert.match(snowRuntime,/minzoom:Number\(data\.regionalSnow\.minzoom\)/);
assert.match(snowRuntime,/'fill-opacity':\['interpolate'/);
assert.match(snowRuntime,/\['zoom'\],7,0\.68/);
assert.match(snowRuntime,/'fill-antialias':true/);
assert.doesNotMatch(snowRuntime,/maxzoom:Number\(data\.regionalSnow\.displayMaxzoom/);
assert.doesNotMatch(snowRuntime,/type:'raster'/);
assert.doesNotMatch(snowRuntime,/raster-resampling|raster-opacity|raster-fade-duration/);
assert.match(ui,/id:'terrain-hillshade'/);
assert.ok(ui.indexOf("id:'terrain-hillshade'") < ui.indexOf("id:'ridge-lines'"));
assert.match(page,/prepareSnowSource/);

for (const legacy of [
  'data/alan-snow-7.3.1.pmtiles',
  'data/alan-snow-permanent-7.2.5.pmtiles',
  'data/alan-snow-seasonal-7.2.5.pmtiles',
]) {
  assert.equal(fs.existsSync(legacy),false,`legacy snow archive should be removed: ${legacy}`);
}
assert.equal(fs.existsSync(data.regionalSnow.archivePath),true);
assert.equal(fs.existsSync(data.regionalSnow.vectorReportPath),true);

const report = JSON.parse(fs.readFileSync(data.regionalSnow.vectorReportPath,'utf8'));
assert.equal(report.version,'7.3.8');
assert.equal(report.alpha_threshold,128);
assert.equal(report.contour_interval_m,200);
assert.ok(report.snow_feature_count > 0);
assert.ok(report.snow_contour_feature_count > 0);
assert.ok(report.snow_area_km2_mercator > 0);

console.log(JSON.stringify({
  version:data.version,
  snowArchive:data.regionalSnow.archivePath,
  snowMinzoom:data.regionalSnow.minzoom,
  snowArchiveMaxzoom:data.regionalSnow.maxzoom,
  snowDisplayMaxzoom:data.regionalSnow.displayMaxzoom,
  snowFeatures:report.snow_feature_count,
  snowContours:report.snow_contour_feature_count,
  snowAreaKm2:report.snow_area_km2_mercator,
},null,2));
