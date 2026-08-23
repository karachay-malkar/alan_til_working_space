#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, shutil
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
VERSION='7.3.7'; BASE='7.3.6'
OLD_DEM='data/alan-dem-7.3.6.pmtiles'; NEW_DEM='data/alan-dem-7.3.7.pmtiles'
DATA_VERSION='7.3.7-dem-z7-z11-256-5m-sequential.1'
MARKER='window.ALAN_MAP_DATA = '
PARTS=[ROOT/'assets/map-data.part-000.js',ROOT/'assets/map-data.part-001.js']
BOUNDS=[40.51784,42.734095,44.184003,44.534975]
CENTER=[42.350921,43.634535]
RING=[[40.51784,43.41265],[43.731622,42.734095],[44.184003,43.85642],[40.970221,44.534975],[40.51784,43.41265]]
ZOOMS=[7,8,9,10,11]
LOD='single-pyramid-native-z7-z11-overzoom-z11'
GENERAL='sequential-z11-z10-z9-z8-z7-area-average-5m'
RES={'7':885.148,'8':442.574,'9':221.287,'10':110.644,'11':55.322}

def parse(path,marker=MARKER):
    s=path.read_text(encoding='utf-8').strip()
    if not(s.startswith(marker) and s.endswith(';')): raise RuntimeError(f'bad wrapper: {path}')
    return json.loads(s[len(marker):-1])

def write(path,data,marker=MARKER): path.write_text(marker+json.dumps(data,ensure_ascii=False,separators=(',',':'))+';\n',encoding='utf-8')
def ring(d): return d['mapFrame']['features'][0]['geometry']['coordinates'][0]
def geo(d):
    if d.get('bounds')!=BOUNDS or d.get('center')!=CENTER or ring(d)!=RING: raise RuntimeError('geography drift')
def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for c in iter(lambda:f.read(1048576),b''): h.update(c)
    return h.hexdigest()
def req(text,old,new,label):
    if old not in text: raise RuntimeError(f'missing {label}: {old}')
    return text.replace(old,new,1)
def read_parts():
    s=''.join(p.read_text(encoding='utf-8') for p in PARTS).strip()
    if not(s.startswith(MARKER) and s.endswith(';')): raise RuntimeError('bad source parts')
    return json.loads(s[len(MARKER):-1])
def write_parts(data):
    s='\n'+MARKER+json.dumps(data,ensure_ascii=False,separators=(',',':'))+';\n'; m=len(s)//2
    PARTS[0].write_text(s[:m],encoding='utf-8'); PARTS[1].write_text(s[m:],encoding='utf-8')

def patch_data(d,size,digest):
    geo(d)
    d['version']=d['applicationVersion']=d['stage']=VERSION; d['dataVersion']=DATA_VERSION
    rl=d.setdefault('runtimeLoading',{}); rl['version']=VERSION; rl['terrainLoading']='maplibre-native-visible-tiles-only'; rl['manualTilePrefetch']=False
    dem=d['regionalDem']; dem.update({'archivePath':NEW_DEM,'archiveBytes':size,'archiveSha256':digest,'tileSize':256,'minzoom':7,'maxzoom':11,'encoding':'mapbox','heightQuantizationM':5,'lodModel':LOD,'highestNativeZoom':11,'overzoomFrom':11,'physicalNativeZooms':ZOOMS,'runtimeNativeZooms':ZOOMS,'runtimeNetworkLevels':5,'runtimeTerrainSources':1,'transitionMode':'maplibre-native-single-source','terrainRuntime':'maplibre-native-single-source','terrainController':False,'geometryGeneralization':GENERAL,'horizontalGroundResolutionApproxM':55.322,'physicalGroundMPerPixelAtCenter':RES,'effectiveGroundMPerInformationPixelAtCenter':RES})
    return d

def prepare():
    d=parse(ROOT/'assets/map-data-core.js'); geo(d)
    if d.get('version')!=BASE or d['regionalDem'].get('physicalNativeZooms')!=[7,8,9,10]: raise RuntimeError('base is not validated 7.3.6')
    b=ROOT/'build'; b.mkdir(exist_ok=True)
    (b/'map-frame.geojson').write_text(json.dumps(d['mapFrame'],separators=(',',':'))+'\n')
    (b/'rectangular-bounds.json').write_text(json.dumps({'bounds':BOUNDS})+'\n')
    (b/'map-data-7.3.7-dem-config.js').write_text(MARKER+json.dumps({'center':CENTER,'regionalDem':{'minzoom':7,'maxzoom':11,'tileSize':256}},separators=(',',':'))+';\n')
    print(json.dumps({'version':VERSION,'baseVersion':BASE,'physicalNativeZooms':ZOOMS,'highestNativeZoom':11},indent=2))

def patch_versions():
    p=ROOT/'assets/bootstrap.js'; s=p.read_text(); p.write_text(req(s,"const RELEASE = '7.3.6';","const RELEASE = '7.3.7';",'bootstrap'),encoding='utf-8')
    p=ROOT/'assets/map-page.js'; s=p.read_text(); p.write_text(req(s,"const VERSION = '7.3.6';","const VERSION = '7.3.7';",'map-page'),encoding='utf-8')
    p=ROOT/'assets/map-ui.js'; s=p.read_text(); s=req(s,"const VERSION = '7.3.6';","const VERSION = '7.3.7';",'map-ui'); s=req(s,"const DEFAULT_STORAGE_KEY = 'alan-map-stage7.3.6-view';","const DEFAULT_STORAGE_KEY = 'alan-map-stage7.3.7-view';",'storage');
    if "'alan-map-stage7.3.6-view'," not in s: s=s.replace('  const LEGACY_STORAGE_KEYS = [\n',"  const LEGACY_STORAGE_KEYS = [\n    'alan-map-stage7.3.6-view',\n",1)
    p.write_text(s,encoding='utf-8')
    p=ROOT/'index.html'; s=p.read_text();
    if '7.3.6' not in s: raise RuntimeError('index version marker missing')
    p.write_text(s.replace('7.3.6',VERSION),encoding='utf-8')
    p=ROOT/'README.md'; s=p.read_text(); p.write_text(s.replace('# Alan Map 7.3.6','# Alan Map 7.3.7',1).replace('Z7, Z8, Z9, Z10;','Z7, Z8, Z9, Z10, Z11;').replace('Z11–Z14.3 используют overzoom Z10','Z12–Z14.3 используют overzoom Z11').replace('Copernicus GLO-30 → Z10 → Z9 → Z8 → Z7','Copernicus GLO-30 → Z11 → Z10 → Z9 → Z8 → Z7'),encoding='utf-8')

def patch_tests():
    p=ROOT/'tests/runtime-contract.mjs'; s=p.read_text(); s=s.replace('7.3.6','7.3.7').replace(r'7\.3\.6',r'7\.3\.7').replace('single-pyramid-native-z7-z10-overzoom-z10',LOD).replace('[7,8,9,10]','[7,8,9,10,11]').replace("assert.equal(data.regionalDem.maxzoom, 10);","assert.equal(data.regionalDem.maxzoom, 11);").replace("assert.equal(data.regionalDem.highestNativeZoom, 10);","assert.equal(data.regionalDem.highestNativeZoom, 11);").replace("assert.equal(data.regionalDem.overzoomFrom, 10);","assert.equal(data.regionalDem.overzoomFrom, 11);").replace('sequential-z10-z9-z8-z7-area-average-5m',GENERAL).replace("{'7':885.148,'8':442.574,'9':221.287,'10':110.644}","{'7':885.148,'8':442.574,'9':221.287,'10':110.644,'11':55.322}").replace('size < 30000000','size < 45000000').replace('7.3.7-dem-z7-z10-256-5m-sequential.1',DATA_VERSION)
    p.write_text(s,encoding='utf-8')
    p=ROOT/'tests/map-smoke.mjs'; s=p.read_text().replace('7.3.6','7.3.7').replace(r'7\.3\.6',r'7\.3\.7'); marker="  assert.ok(diagnostics.transport.archives.reduce((sum,item) => sum + item.networkBytes,0) > 0);\n"
    probe="""\n  await page.evaluate(() => window.ALAN_MAP_INSTANCE.map.jumpTo({center:[42.445874,43.349602],zoom:11.2,bearing:180,pitch:58}));\n  await page.waitForFunction(() => window.ALAN_MAP_INSTANCE?.map?.isSourceLoaded?.('terrain-dem') === true,undefined,{timeout:60000});\n  await page.waitForTimeout(900);\n  const terrainProbe=await page.evaluate(()=>{const map=window.ALAN_MAP_INSTANCE.map;const samples=[];const c=[42.445874,43.349602];for(const dx of [-.055,-.0275,0,.0275,.055])for(const dy of [-.045,-.0225,0,.0225,.045]){const e=map.queryTerrainElevation?.([c[0]+dx,c[1]+dy]);if(Number.isFinite(e))samples.push(e);}return{terrain:map.getTerrain?.(),pitch:map.getPitch(),zoom:map.getZoom(),finiteSamples:samples.length,reliefRange:samples.length?Math.max(...samples)-Math.min(...samples):null};});\n  assert.equal(terrainProbe.terrain?.source,'terrain-dem');\n  assert.ok(terrainProbe.pitch>=45);\n  assert.ok(terrainProbe.zoom>=11);\n  assert.ok(terrainProbe.finiteSamples>=9);\n  assert.ok(terrainProbe.reliefRange>350);\n"""
    if marker not in s: raise RuntimeError('smoke marker missing')
    p.write_text(s.replace(marker,marker+probe,1),encoding='utf-8')
    (ROOT/'tests/terrain-architecture-7.3.7.mjs').write_text("""import fs from 'node:fs';\nimport assert from 'node:assert/strict';\nconst m='window.ALAN_MAP_DATA = ';const w=fs.readFileSync('assets/map-data-core.js','utf8').trim();const d=JSON.parse(w.slice(m.length,-1));const ui=fs.readFileSync('assets/map-ui.js','utf8');const page=fs.readFileSync('assets/map-page.js','utf8');const boot=fs.readFileSync('assets/bootstrap.js','utf8');\nassert.equal(d.version,'7.3.7');assert.equal(d.regionalDem.archivePath,'data/alan-dem-7.3.7.pmtiles');assert.deepEqual(d.regionalDem.physicalNativeZooms,[7,8,9,10,11]);assert.equal(d.regionalDem.maxzoom,11);assert.equal(d.regionalDem.overzoomFrom,11);assert.equal(d.regionalDem.runtimeTerrainSources,1);assert.equal(d.regionalDem.terrainController,false);assert.equal(d.regionalDem.horizontalGroundResolutionApproxM,55.322);assert.match(ui,/minPitch: 45/);assert.match(ui,/pitch: 58/);assert.match(ui,/relief: 2\\.8/);assert.match(ui,/terrain: \\{source:'terrain-dem',exaggeration:state\\.relief\\}/);assert.ok(!page.includes('installPrefetch'));assert.match(page,/class RangeLruCache/);assert.match(page,/class NetworkGate/);assert.match(boot,/const RELEASE = '7\\.3\\.7'/);console.log('terrain-architecture-7.3.7: ok');\n""",encoding='utf-8')

def reports(size,digest,build,validation,collar):
    runtime={'version':VERSION,'baseVersion':BASE,'demArchivePath':NEW_DEM,'demArchiveBytes':size,'demTileSize':256,'demPhysicalNativeZooms':ZOOMS,'demOverzoomFrom':11,'heightQuantizationM':5,'terrainInitialStyleEnabled':True,'terrainSourceSwitching':False,'manualTilePrefetch':False,'minPitch':45,'defaultPitch':58,'defaultRelief':2.8,'terrainElevationBrowserProbe':True,'snowSourceDeferredUntilFirstIdle':True}
    (ROOT/'data/runtime-loading-report-7.3.7.json').write_text(json.dumps(runtime,indent=2)+'\n')
    lod={'version':VERSION,'archive':NEW_DEM,'bytes':size,'sha256':digest,'tileSize':256,'heightQuantizationM':5,'physicalNativeZooms':ZOOMS,'highestNativeZoom':11,'overzoomFrom':11,'lodModel':LOD,'numericLineage':GENERAL,'physicalGroundMPerPixelAtCenter':RES,'effectiveGroundMPerInformationPixelAtCenter':RES,'build':build,'validation':validation,'edgeCollar':collar}
    (ROOT/'data/dem-lod-report-7.3.7.json').write_text(json.dumps(lod,indent=2)+'\n')

def validate_runtime():
    d=parse(ROOT/'assets/map-data-core.js'); geo(d); dem=d['regionalDem']
    if d.get('version')!=VERSION or dem.get('physicalNativeZooms')!=ZOOMS or dem.get('maxzoom')!=11 or dem.get('overzoomFrom')!=11 or dem.get('runtimeTerrainSources')!=1 or dem.get('terrainController') is not False: raise RuntimeError('runtime DEM contract mismatch')
    ui=(ROOT/'assets/map-ui.js').read_text(); page=(ROOT/'assets/map-page.js').read_text(); boot=(ROOT/'assets/bootstrap.js').read_text()
    if "terrain: {source:'terrain-dem',exaggeration:state.relief}" not in ui or 'minPitch: 45' not in ui or 'installPrefetch' in page or "const RELEASE = '7.3.7'" not in boot: raise RuntimeError('persistent 3D runtime contract mismatch')

def finalize(dem_path,build_path,validation_path,collar_path):
    build=json.loads(build_path.read_text()); validation=json.loads(validation_path.read_text()); collar=json.loads(collar_path.read_text())
    if build.get('physical_native_zooms')!=ZOOMS or build.get('tile_size')!=256 or build.get('height_quantization_m')!=5.0: raise RuntimeError('builder contract mismatch')
    if not validation.get('valid') or validation.get('native_zooms')!=ZOOMS or not validation.get('no_native_tiles_after_z11'): raise RuntimeError('DEM validation mismatch')
    target=ROOT/NEW_DEM; shutil.copy2(dem_path,target) if dem_path.resolve()!=target.resolve() else None; size=target.stat().st_size; digest=sha(target)
    patch_versions(); write_parts(patch_data(read_parts(),size,digest)); write(ROOT/'assets/map-data-core.js',patch_data(parse(ROOT/'assets/map-data-core.js'),size,digest))
    for name,marker in [('assets/map-data-deferred.js','window.ALAN_MAP_DEFERRED_DATA = '),('assets/map-data-points.js','window.ALAN_MAP_POINT_DATA = ')]:
        p=ROOT/name; x=parse(p,marker); x['version']=VERSION; write(p,x,marker)
    reports(size,digest,build,validation,collar); patch_tests(); validate_runtime(); print(json.dumps({'version':VERSION,'demBytes':size,'demSha256':digest,'physicalNativeZooms':ZOOMS,'persistent3D':True},indent=2))

def validate():
    validate_runtime(); p=ROOT/NEW_DEM
    if not p.exists(): raise RuntimeError('DEM missing')
    for q in [ROOT/'data/dem-lod-report-7.3.7.json',ROOT/'data/runtime-loading-report-7.3.7.json',ROOT/'tests/terrain-architecture-7.3.7.mjs']:
        if not q.exists(): raise RuntimeError(f'missing {q}')
    print(json.dumps({'version':VERSION,'valid':True,'demBytes':p.stat().st_size},indent=2))

def main():
    ap=argparse.ArgumentParser(); sp=ap.add_subparsers(dest='cmd',required=True); sp.add_parser('prepare'); f=sp.add_parser('finalize'); f.add_argument('--dem',type=Path,required=True); f.add_argument('--build-report',type=Path,required=True); f.add_argument('--validation-report',type=Path,required=True); f.add_argument('--collar-report',type=Path,required=True); sp.add_parser('validate'); a=ap.parse_args()
    if a.cmd=='prepare': prepare()
    elif a.cmd=='finalize': finalize(a.dem,a.build_report,a.validation_report,a.collar_report)
    else: validate()
if __name__=='__main__': main()
