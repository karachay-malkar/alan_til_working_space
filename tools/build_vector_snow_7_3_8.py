#!/usr/bin/env python3
from __future__ import annotations

import argparse
import io
import json
import math
import sqlite3
from pathlib import Path

import geopandas as gpd
import numpy as np
from PIL import Image
from affine import Affine
from rasterio.features import shapes
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon, shape
from shapely.ops import unary_union

HALF = 20037508.342789244
WORLD = HALF * 2
TILE_SIZE = 256
SNOW_ZOOM = 12
DEM_ZOOM = 11
ALPHA_THRESHOLD = 128
MIN_SNOW_AREA_M2 = 2500.0
MIN_HOLE_AREA_M2 = 1800.0
SIMPLIFY_M = 10.0
CONTOUR_INTERVAL_M = 200


def xyz_y(z: int, tms_y: int) -> int:
    return (1 << z) - 1 - int(tms_y)


def tile_rows(path: Path, zoom: int):
    connection = sqlite3.connect(path)
    try:
        return list(connection.execute(
            'select tile_column,tile_row,tile_data from tiles where zoom_level=? order by tile_column,tile_row',
            (zoom,),
        ))
    finally:
        connection.close()


def mosaic_transform(zoom: int, min_x: int, min_y: int) -> Affine:
    tile_span = WORLD / (1 << zoom)
    pixel_span = tile_span / TILE_SIZE
    west = -HALF + min_x * tile_span
    north = HALF - min_y * tile_span
    return Affine(pixel_span, 0, west, 0, -pixel_span, north)


def load_alpha_mosaic(path: Path, zoom: int) -> tuple[np.ndarray, Affine]:
    rows = tile_rows(path, zoom)
    if not rows:
        raise RuntimeError(f'No raster snow tiles at z{zoom}: {path}')
    xs = [int(row[0]) for row in rows]
    ys = [xyz_y(zoom, row[1]) for row in rows]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    mosaic = np.zeros(((max_y - min_y + 1) * TILE_SIZE, (max_x - min_x + 1) * TILE_SIZE), dtype=np.uint8)
    for tile_x, tile_row, tile_data in rows:
        tile_y = xyz_y(zoom, tile_row)
        image = np.asarray(Image.open(io.BytesIO(tile_data)).convert('RGBA'), dtype=np.uint8)
        r0 = (tile_y - min_y) * TILE_SIZE
        c0 = (int(tile_x) - min_x) * TILE_SIZE
        np.maximum(mosaic[r0:r0 + TILE_SIZE, c0:c0 + TILE_SIZE], image[:, :, 3], out=mosaic[r0:r0 + TILE_SIZE, c0:c0 + TILE_SIZE])
    return mosaic, mosaic_transform(zoom, min_x, min_y)


def clean_polygon(polygon: Polygon) -> Polygon | None:
    if polygon.is_empty or polygon.area < MIN_SNOW_AREA_M2:
        return None
    holes = []
    for ring in polygon.interiors:
        candidate = Polygon(ring)
        if candidate.area >= MIN_HOLE_AREA_M2:
            holes.append(ring.coords[:])
    cleaned = Polygon(polygon.exterior.coords[:], holes)
    cleaned = cleaned.simplify(SIMPLIFY_M, preserve_topology=True)
    if cleaned.is_empty or cleaned.area < MIN_SNOW_AREA_M2:
        return None
    return cleaned


def explode_polygons(geometry):
    if geometry is None or geometry.is_empty:
        return []
    if isinstance(geometry, Polygon):
        return [geometry]
    if isinstance(geometry, MultiPolygon):
        return list(geometry.geoms)
    if isinstance(geometry, GeometryCollection):
        result = []
        for child in geometry.geoms:
            result.extend(explode_polygons(child))
        return result
    return []


def polygonize_snow(alpha: np.ndarray, transform: Affine) -> list[Polygon]:
    mask = alpha >= ALPHA_THRESHOLD
    if not mask.any():
        raise RuntimeError('Binary snow mask is empty')
    raw = []
    raster = mask.astype(np.uint8)
    for geometry, value in shapes(raster, mask=mask, transform=transform, connectivity=8):
        if int(value) != 1:
            continue
        polygon = shape(geometry)
        if not polygon.is_empty and polygon.area >= MIN_SNOW_AREA_M2:
            raw.append(polygon)
    if not raw:
        raise RuntimeError('Polygonization produced no snow features')
    merged = unary_union(raw)
    result = []
    for polygon in explode_polygons(merged):
        cleaned = clean_polygon(polygon)
        if cleaned is not None:
            result.append(cleaned)
    if not result:
        raise RuntimeError('Snow cleanup removed every feature')
    return result


def load_dem_mosaic(path: Path, zoom: int) -> tuple[np.ndarray, np.ndarray, Affine]:
    rows = tile_rows(path, zoom)
    if not rows:
        raise RuntimeError(f'No DEM tiles at z{zoom}: {path}')
    xs = [int(row[0]) for row in rows]
    ys = [xyz_y(zoom, row[1]) for row in rows]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    height = np.full(((max_y - min_y + 1) * TILE_SIZE, (max_x - min_x + 1) * TILE_SIZE), np.nan, dtype=np.float32)
    valid = np.zeros(height.shape, dtype=bool)
    for tile_x, tile_row, tile_data in rows:
        tile_y = xyz_y(zoom, tile_row)
        image = np.asarray(Image.open(io.BytesIO(tile_data)).convert('RGBA'), dtype=np.uint8)
        rgb = image[:, :, :3].astype(np.uint32)
        decoded = -10000.0 + (rgb[:, :, 0] * 65536 + rgb[:, :, 1] * 256 + rgb[:, :, 2]) * 0.1
        tile_valid = image[:, :, 3] > 0
        r0 = (tile_y - min_y) * TILE_SIZE
        c0 = (int(tile_x) - min_x) * TILE_SIZE
        target = height[r0:r0 + TILE_SIZE, c0:c0 + TILE_SIZE]
        target_valid = valid[r0:r0 + TILE_SIZE, c0:c0 + TILE_SIZE]
        target[tile_valid] = decoded[tile_valid]
        target_valid[tile_valid] = True
    return height, valid, mosaic_transform(zoom, min_x, min_y)


def save_dem_tif(path: Path, height: np.ndarray, valid: np.ndarray, transform: Affine) -> None:
    import rasterio
    path.parent.mkdir(parents=True, exist_ok=True)
    values = np.where(valid, height, -9999.0).astype(np.float32)
    with rasterio.open(
        path,
        'w',
        driver='GTiff',
        height=values.shape[0],
        width=values.shape[1],
        count=1,
        dtype='float32',
        crs='EPSG:3857',
        transform=transform,
        nodata=-9999.0,
        compress='DEFLATE',
        tiled=True,
        blockxsize=256,
        blockysize=256,
    ) as dataset:
        dataset.write(values, 1)


def clip_contours(contours_path: Path, snow_union, output_path: Path) -> int:
    contours = gpd.read_file(contours_path)
    if contours.empty:
        raise RuntimeError('gdal_contour produced no contour lines')
    if contours.crs is None:
        contours = contours.set_crs('EPSG:3857')
    contours = contours.to_crs('EPSG:3857')
    contours = contours[contours['elev'].between(1000, 6000)].copy()
    contours['geometry'] = contours.geometry.intersection(snow_union)
    contours = contours[~contours.geometry.is_empty].copy()
    contours = contours[contours.geometry.length >= 120].copy()
    if output_path.exists():
        output_path.unlink()
    contours[['elev', 'geometry']].to_file(output_path, layer='snow_contour', driver='GPKG')
    return len(contours)


def write_snow_layer(polygons: list[Polygon], gpkg_path: Path) -> None:
    frame = gpd.GeoDataFrame(
        {
            'kind': ['snow'] * len(polygons),
            'geometry': polygons,
        },
        crs='EPSG:3857',
    )
    if gpkg_path.exists():
        gpkg_path.unlink()
    frame.to_file(gpkg_path, layer='snow', driver='GPKG')


def append_contours(source_gpkg: Path, contours_gpkg: Path) -> None:
    contours = gpd.read_file(contours_gpkg, layer='snow_contour')
    contours.to_file(source_gpkg, layer='snow_contour', driver='GPKG', mode='a')


def vertex_count(polygons: list[Polygon]) -> int:
    total = 0
    for polygon in polygons:
        total += len(polygon.exterior.coords)
        total += sum(len(ring.coords) for ring in polygon.interiors)
    return total


def main() -> None:
    parser = argparse.ArgumentParser(description='Build crisp vector snow geometry and snow-only contour lines for Alan Map 7.3.8.')
    parser.add_argument('--snow-mbtiles', required=True, type=Path)
    parser.add_argument('--dem-mbtiles', required=True, type=Path)
    parser.add_argument('--output-gpkg', required=True, type=Path)
    parser.add_argument('--work-dir', required=True, type=Path)
    parser.add_argument('--report', required=True, type=Path)
    args = parser.parse_args()

    args.work_dir.mkdir(parents=True, exist_ok=True)
    args.output_gpkg.parent.mkdir(parents=True, exist_ok=True)

    alpha, snow_transform = load_alpha_mosaic(args.snow_mbtiles, SNOW_ZOOM)
    polygons = polygonize_snow(alpha, snow_transform)
    snow_union = unary_union(polygons)
    write_snow_layer(polygons, args.output_gpkg)

    height, valid, dem_transform = load_dem_mosaic(args.dem_mbtiles, DEM_ZOOM)
    dem_tif = args.work_dir / 'dem-z11.tif'
    save_dem_tif(dem_tif, height, valid, dem_transform)

    contour_raw = args.work_dir / 'contours-raw.gpkg'
    contour_clipped = args.work_dir / 'contours-snow.gpkg'
    import subprocess
    subprocess.run([
        'gdal_contour', '-q', '-i', str(CONTOUR_INTERVAL_M), '-a', 'elev',
        str(dem_tif), str(contour_raw), '-f', 'GPKG', '-nln', 'contours'
    ], check=True)
    contour_count = clip_contours(contour_raw, snow_union, contour_clipped)
    append_contours(args.output_gpkg, contour_clipped)

    pixel_area = abs(snow_transform.a * snow_transform.e)
    binary_pixels = int((alpha >= ALPHA_THRESHOLD).sum())
    report = {
        'version': '7.3.8',
        'strategy': 'vector-polygons-from-canonical-sentinel-mask-with-snow-contours',
        'source_mask_version': '7.3.1',
        'source_mask_zoom': SNOW_ZOOM,
        'alpha_threshold': ALPHA_THRESHOLD,
        'minimum_polygon_area_m2': MIN_SNOW_AREA_M2,
        'minimum_hole_area_m2': MIN_HOLE_AREA_M2,
        'simplify_m': SIMPLIFY_M,
        'snow_feature_count': len(polygons),
        'snow_vertex_count': vertex_count(polygons),
        'snow_binary_pixels': binary_pixels,
        'snow_area_km2_mercator': float(sum(p.area for p in polygons) / 1_000_000),
        'source_binary_area_km2_mercator': float(binary_pixels * pixel_area / 1_000_000),
        'contour_interval_m': CONTOUR_INTERVAL_M,
        'snow_contour_feature_count': contour_count,
        'dem_zoom_for_contours': DEM_ZOOM,
        'output_gpkg': str(args.output_gpkg),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
