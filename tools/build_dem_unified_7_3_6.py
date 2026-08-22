#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import sqlite3
from pathlib import Path

import numpy as np
from PIL import Image
import rasterio
from rasterio.features import geometry_mask
from rasterio.transform import from_bounds
from rasterio.warp import Resampling, reproject, transform_geom
from shapely.geometry import Polygon

WEB_MERCATOR_HALF_WORLD = 20037508.342789244
WEB_MERCATOR_PIXEL_M_256 = 156543.03392804097
TILE_SIZE = 256
MIN_ZOOM = 7
MAX_ZOOM = 10
TERRAIN_BASE = -10000.0
TERRAIN_INTERVAL = 0.1
HEIGHT_QUANTIZATION_M = 5.0
INTERNAL_NODATA = -32768.0
CENTER_LAT = 43.634535
LOD_MODEL = 'single-pyramid-native-z7-z10-overzoom-z10'
NUMERIC_LINEAGE = 'sequential-z10-z9-z8-z7-area-average-5m'


def load_frame(path: Path) -> tuple[dict, Polygon]:
    collection = json.loads(path.read_text(encoding='utf-8'))
    geometry = collection['features'][0]['geometry']
    if geometry.get('type') != 'Polygon':
        raise RuntimeError('map frame must be a Polygon')
    polygon = Polygon(geometry['coordinates'][0])
    if not polygon.is_valid or polygon.is_empty:
        raise RuntimeError('invalid map-frame polygon')
    return geometry, polygon


def lon_to_tile_x(lon: float, z: int) -> int:
    count = 2 ** z
    return max(0, min(count - 1, int(math.floor((lon + 180.0) / 360.0 * count))))


def lat_to_tile_y(lat: float, z: int) -> int:
    count = 2 ** z
    clipped = max(-85.05112878, min(85.05112878, lat))
    radians = math.radians(clipped)
    value = (1.0 - math.asinh(math.tan(radians)) / math.pi) / 2.0 * count
    return max(0, min(count - 1, int(math.floor(value))))


def tile_rect_mercator_bounds(z: int, x_min: int, y_min: int, x_max: int, y_max: int) -> tuple[float, float, float, float]:
    count = 2 ** z
    span = (WEB_MERCATOR_HALF_WORLD * 2.0) / count
    west = -WEB_MERCATOR_HALF_WORLD + x_min * span
    east = -WEB_MERCATOR_HALF_WORLD + (x_max + 1) * span
    north = WEB_MERCATOR_HALF_WORLD - y_min * span
    south = WEB_MERCATOR_HALF_WORLD - (y_max + 1) * span
    return west, south, east, north


def quantize(array: np.ndarray) -> np.ndarray:
    output = np.asarray(array, dtype=np.float32).copy()
    valid = np.isfinite(output) & (output != INTERNAL_NODATA)
    output[valid] = np.rint(output[valid] / HEIGHT_QUANTIZATION_M) * HEIGHT_QUANTIZATION_M
    output[~valid] = INTERNAL_NODATA
    return output


def frame_inside_mask(frame_3857: dict, shape: tuple[int, int], transform) -> np.ndarray:
    return geometry_mask([frame_3857], out_shape=shape, transform=transform, invert=True, all_touched=False)


def apply_mask_and_quantize(array: np.ndarray, frame_3857: dict, transform) -> tuple[np.ndarray, np.ndarray]:
    output = quantize(array)
    inside = frame_inside_mask(frame_3857, output.shape, transform)
    valid = np.isfinite(output) & (output != INTERNAL_NODATA) & inside
    output[~valid] = INTERNAL_NODATA
    return output, valid


def warp_source_dem(dem: Path, frame_3857: dict, extent: tuple[float, float, float, float], shape: tuple[int, int]) -> tuple[np.ndarray, object]:
    transform = from_bounds(*extent, shape[1], shape[0])
    destination = np.full(shape, INTERNAL_NODATA, dtype=np.float32)
    with rasterio.open(dem) as source:
        if source.crs is None:
            raise RuntimeError('source DEM has no CRS')
        reproject(
            source=rasterio.band(source, 1),
            destination=destination,
            src_transform=source.transform,
            src_crs=source.crs,
            src_nodata=source.nodata,
            dst_transform=transform,
            dst_crs='EPSG:3857',
            dst_nodata=INTERNAL_NODATA,
            resampling=Resampling.bilinear,
            num_threads=2,
        )
    output, _ = apply_mask_and_quantize(destination, frame_3857, transform)
    return output, transform


def resample_numeric_level(source: np.ndarray, src_transform, frame_3857: dict, extent: tuple[float, float, float, float], shape: tuple[int, int]) -> tuple[np.ndarray, object]:
    dst_transform = from_bounds(*extent, shape[1], shape[0])
    destination = np.full(shape, INTERNAL_NODATA, dtype=np.float32)
    reproject(
        source=source,
        destination=destination,
        src_transform=src_transform,
        src_crs='EPSG:3857',
        src_nodata=INTERNAL_NODATA,
        dst_transform=dst_transform,
        dst_crs='EPSG:3857',
        dst_nodata=INTERNAL_NODATA,
        resampling=Resampling.average,
        num_threads=2,
    )
    output, _ = apply_mask_and_quantize(destination, frame_3857, dst_transform)
    return output, dst_transform


def encode_mapbox_rgb(elevation: np.ndarray, valid: np.ndarray) -> np.ndarray:
    encoded = np.zeros(elevation.shape, dtype=np.int64)
    if np.any(valid):
        values = np.rint((elevation[valid].astype(np.float64) - TERRAIN_BASE) / TERRAIN_INTERVAL)
        encoded[valid] = np.clip(values, 0, 16777215).astype(np.int64)
    rgb = np.zeros((*elevation.shape, 3), dtype=np.uint8)
    rgb[:, :, 0] = ((encoded >> 16) & 255).astype(np.uint8)
    rgb[:, :, 1] = ((encoded >> 8) & 255).astype(np.uint8)
    rgb[:, :, 2] = (encoded & 255).astype(np.uint8)
    return rgb


def encode_tile(elevation: np.ndarray, valid: np.ndarray) -> tuple[np.ndarray, str]:
    rgb = encode_mapbox_rgb(elevation, valid)
    if np.all(valid):
        return rgb, 'RGB'
    rgba = np.zeros((*elevation.shape, 4), dtype=np.uint8)
    rgba[:, :, :3] = rgb
    rgba[:, :, 3] = np.where(valid, 255, 0).astype(np.uint8)
    return rgba, 'RGBA'


def png_bytes(array: np.ndarray, mode: str) -> bytes:
    output = io.BytesIO()
    Image.fromarray(array, mode=mode).save(output, format='PNG', compress_level=9, optimize=True)
    return output.getvalue()


def initialize_mbtiles(connection: sqlite3.Connection, polygon: Polygon) -> None:
    connection.executescript('''
        PRAGMA journal_mode=OFF;
        PRAGMA synchronous=OFF;
        PRAGMA temp_store=MEMORY;
        CREATE TABLE metadata (name text, value text);
        CREATE TABLE tiles (zoom_level integer, tile_column integer, tile_row integer, tile_data blob);
        CREATE UNIQUE INDEX tile_index ON tiles (zoom_level, tile_column, tile_row);
    ''')
    west, south, east, north = polygon.bounds
    metadata = {
        'name': 'Alan DEM 7.3.6 sequential Z7-Z10 256',
        'type': 'baselayer',
        'version': '7.3.6',
        'description': 'Copernicus DEM GLO-30, 5 m quantized, sequential numeric Z10→Z9→Z8→Z7, 256px Terrain-RGB tiles',
        'format': 'png',
        'minzoom': str(MIN_ZOOM),
        'maxzoom': str(MAX_ZOOM),
        'bounds': f'{west:.6f},{south:.6f},{east:.6f},{north:.6f}',
        'center': f'{polygon.centroid.x:.6f},{polygon.centroid.y:.6f},{MIN_ZOOM}',
        'alan_tile_size': str(TILE_SIZE),
        'alan_lod_model': LOD_MODEL,
        'alan_numeric_lineage': NUMERIC_LINEAGE,
        'alan_height_quantization_m': str(int(HEIGHT_QUANTIZATION_M)),
        'alan_highest_native_zoom': str(MAX_ZOOM),
        'alan_overzoom_from': str(MAX_ZOOM),
    }
    connection.executemany('INSERT INTO metadata (name,value) VALUES (?,?)', metadata.items())


def sha256_array(array: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(array).tobytes()).hexdigest()


def ground_resolution_summary(center_lat: float) -> dict[str, float]:
    base = WEB_MERCATOR_PIXEL_M_256 * math.cos(math.radians(center_lat))
    return {str(z): round(base / (2 ** z), 3) for z in range(MIN_ZOOM, MAX_ZOOM + 1)}


def build_from_dem(dem: Path, output: Path, frame: Path) -> dict:
    frame_geometry, polygon = load_frame(frame)
    frame_3857 = transform_geom('EPSG:4326', 'EPSG:3857', frame_geometry, precision=15)
    west, south, east, north = polygon.bounds

    x_min_7 = lon_to_tile_x(west, MIN_ZOOM)
    x_max_7 = lon_to_tile_x(east, MIN_ZOOM)
    y_min_7 = lat_to_tile_y(north, MIN_ZOOM)
    y_max_7 = lat_to_tile_y(south, MIN_ZOOM)
    extent = tile_rect_mercator_bounds(MIN_ZOOM, x_min_7, y_min_7, x_max_7, y_max_7)
    z7_tiles_x = x_max_7 - x_min_7 + 1
    z7_tiles_y = y_max_7 - y_min_7 + 1

    z10_shape = (
        z7_tiles_y * (2 ** (MAX_ZOOM - MIN_ZOOM)) * TILE_SIZE,
        z7_tiles_x * (2 ** (MAX_ZOOM - MIN_ZOOM)) * TILE_SIZE,
    )
    levels: dict[int, tuple[np.ndarray, object]] = {}
    levels[10] = warp_source_dem(dem, frame_3857, extent, z10_shape)
    for target_zoom in (9, 8, 7):
        source_zoom = target_zoom + 1
        source_array, source_transform = levels[source_zoom]
        levels[target_zoom] = resample_numeric_level(
            source_array,
            source_transform,
            frame_3857,
            extent,
            (source_array.shape[0] // 2, source_array.shape[1] // 2),
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    output.unlink(missing_ok=True)
    connection = sqlite3.connect(output)
    initialize_mbtiles(connection, polygon)

    totals = {
        'candidate_tiles': 0,
        'tiles_written': 0,
        'outside_tiles_skipped': 0,
        'partial_tiles_masked': 0,
        'interior_tiles': 0,
        'rgb_tiles': 0,
        'rgba_tiles': 0,
        'transparent_pixels': 0,
        'valid_pixels': 0,
        'encoded_png_bytes': 0,
    }
    per_zoom: dict[str, dict[str, int]] = {}

    for z in range(MIN_ZOOM, MAX_ZOOM + 1):
        level, transform = levels[z]
        valid_global = np.isfinite(level) & (level != INTERNAL_NODATA) & frame_inside_mask(frame_3857, level.shape, transform)
        level = level.copy()
        level[~valid_global] = INTERNAL_NODATA

        scale = 2 ** (z - MIN_ZOOM)
        x_min = x_min_7 * scale
        y_min = y_min_7 * scale
        tiles_x = z7_tiles_x * scale
        tiles_y = z7_tiles_y * scale
        expected_shape = (tiles_y * TILE_SIZE, tiles_x * TILE_SIZE)
        if level.shape != expected_shape:
            raise RuntimeError(f'z{z}: numeric grid shape {level.shape} != expected {expected_shape}')

        zoom_stats = {'tiles_written': 0, 'outside_tiles_skipped': 0, 'partial_tiles_masked': 0, 'rgb_tiles': 0, 'rgba_tiles': 0, 'png_bytes': 0}
        for local_y in range(tiles_y):
            for local_x in range(tiles_x):
                totals['candidate_tiles'] += 1
                x = x_min + local_x
                y = y_min + local_y
                row = slice(local_y * TILE_SIZE, (local_y + 1) * TILE_SIZE)
                col = slice(local_x * TILE_SIZE, (local_x + 1) * TILE_SIZE)
                tile_valid = valid_global[row, col]
                if not np.any(tile_valid):
                    totals['outside_tiles_skipped'] += 1
                    zoom_stats['outside_tiles_skipped'] += 1
                    continue
                tile_elevation = level[row, col]
                if np.all(tile_valid):
                    totals['interior_tiles'] += 1
                else:
                    totals['partial_tiles_masked'] += 1
                    zoom_stats['partial_tiles_masked'] += 1
                totals['transparent_pixels'] += int(np.count_nonzero(~tile_valid))
                totals['valid_pixels'] += int(np.count_nonzero(tile_valid))
                image, mode = encode_tile(tile_elevation, tile_valid)
                payload = png_bytes(image, mode)
                totals['encoded_png_bytes'] += len(payload)
                zoom_stats['png_bytes'] += len(payload)
                if mode == 'RGB':
                    totals['rgb_tiles'] += 1
                    zoom_stats['rgb_tiles'] += 1
                else:
                    totals['rgba_tiles'] += 1
                    zoom_stats['rgba_tiles'] += 1
                tile_row_tms = (1 << z) - 1 - y
                connection.execute('INSERT INTO tiles (zoom_level,tile_column,tile_row,tile_data) VALUES (?,?,?,?)', (z, x, tile_row_tms, sqlite3.Binary(payload)))
                totals['tiles_written'] += 1
                zoom_stats['tiles_written'] += 1
        connection.commit()
        per_zoom[str(z)] = zoom_stats
    connection.close()

    resolutions = ground_resolution_summary(CENTER_LAT)
    return {
        'version': '7.3.6',
        'tile_size': TILE_SIZE,
        'minzoom': MIN_ZOOM,
        'maxzoom': MAX_ZOOM,
        'highest_native_zoom': MAX_ZOOM,
        'overzoom_from': MAX_ZOOM,
        'height_quantization_m': HEIGHT_QUANTIZATION_M,
        'encoding': 'mapbox',
        'lod_model': LOD_MODEL,
        'physical_native_zooms': [7, 8, 9, 10],
        'numeric_lineage': NUMERIC_LINEAGE,
        'numeric_level_lineage': {
            '10': 'source-dem-to-web-mercator-bilinear-then-5m-quantization',
            '9': 'area-average-downsample-of-z10-then-5m-quantization',
            '8': 'area-average-downsample-of-z9-then-5m-quantization',
            '7': 'area-average-downsample-of-z8-then-5m-quantization',
        },
        'physical_ground_m_per_pixel_at_center': resolutions,
        'effective_ground_m_per_information_pixel_at_center': resolutions,
        'numeric_level_sha256': {str(z): sha256_array(levels[z][0]) for z in range(MIN_ZOOM, MAX_ZOOM + 1)},
        'extent_3857': [round(value, 3) for value in extent],
        'z7_tile_rect': {'x_min': x_min_7, 'x_max': x_max_7, 'y_min': y_min_7, 'y_max': y_max_7},
        'per_zoom': per_zoom,
        **totals,
    }


def validate_mbtiles(path: Path) -> dict:
    connection = sqlite3.connect(path)
    metadata = dict(connection.execute('SELECT name,value FROM metadata'))
    rows = connection.execute('SELECT zoom_level,tile_column,tile_row,tile_data FROM tiles ORDER BY zoom_level,tile_column,tile_row').fetchall()
    connection.close()
    if not rows:
        raise RuntimeError('MBTiles contains no DEM tiles')
    zooms = sorted({int(row[0]) for row in rows})
    if zooms != [7, 8, 9, 10]:
        raise RuntimeError(f'unexpected native zooms: {zooms}')
    if metadata.get('alan_tile_size') != '256':
        raise RuntimeError(f"unexpected metadata tile size: {metadata.get('alan_tile_size')}")
    if metadata.get('alan_lod_model') != LOD_MODEL:
        raise RuntimeError(f"unexpected LOD model: {metadata.get('alan_lod_model')}")
    if metadata.get('alan_numeric_lineage') != NUMERIC_LINEAGE:
        raise RuntimeError(f"unexpected numeric lineage: {metadata.get('alan_numeric_lineage')}")
    if metadata.get('alan_height_quantization_m') != '5':
        raise RuntimeError(f"unexpected height quantization: {metadata.get('alan_height_quantization_m')}")
    counts = {str(z): 0 for z in zooms}
    modes = {str(z): set() for z in zooms}
    for zoom, _, _, payload in rows:
        image = Image.open(io.BytesIO(payload))
        if image.size != (TILE_SIZE, TILE_SIZE):
            raise RuntimeError(f'z{zoom}: encoded tile size is {image.size}, expected 256x256')
        if image.mode not in ('RGB', 'RGBA'):
            raise RuntimeError(f'z{zoom}: unexpected PNG mode {image.mode}')
        counts[str(zoom)] += 1
        modes[str(zoom)].add(image.mode)
    return {
        'valid': True,
        'native_zooms': zooms,
        'tile_size': TILE_SIZE,
        'tile_counts': counts,
        'png_modes': {key: sorted(value) for key, value in modes.items()},
        'lod_model': metadata['alan_lod_model'],
        'numeric_lineage': metadata['alan_numeric_lineage'],
        'height_quantization_m': int(metadata['alan_height_quantization_m']),
        'no_native_tiles_after_z10': max(zooms) == 10,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description='Build Alan Map 7.3.6 sequential Z7-Z10 256px DEM pyramid.')
    parser.add_argument('input_mbtiles', nargs='?', type=Path)
    parser.add_argument('--build-from-dem', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--frame', type=Path, required=True)
    parser.add_argument('--validate', action='store_true')
    args = parser.parse_args()
    if args.build_from_dem:
        if not args.output:
            parser.error('--output is required with --build-from-dem')
        print(json.dumps(build_from_dem(args.build_from_dem, args.output, args.frame), ensure_ascii=False, indent=2))
        return
    if args.validate:
        if not args.input_mbtiles:
            parser.error('input_mbtiles is required with --validate')
        print(json.dumps(validate_mbtiles(args.input_mbtiles), ensure_ascii=False, indent=2))
        return
    parser.error('choose --build-from-dem or --validate')


if __name__ == '__main__':
    main()
