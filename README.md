# Alan Map 7.3.7

7.3.6 сохраняет визуальную и навигационную архитектуру 7.3.5, но упрощает рельеф и стартовую загрузку.

## Terrain

- один `raster-dem` source `terrain-dem`;
- один MapLibre `terrain`, активный непосредственно в initial style;
- физические DEM уровни только Z7, Z8, Z9, Z10, Z11;
- Z12–Z14.3 используют overzoom Z11 и не добавляют новую геометрию;
- Terrain-RGB 256×256;
- высоты квантованы с шагом 5 м;
- уровни строятся последовательно: Copernicus GLO-30 → Z11 → Z10 → Z9 → Z8 → Z7.

## Постоянный 3D

Камера стартует с pitch 58°, минимальный pitch ограничен 45°, максимальный — 60°. Сохранённые старые состояния с меньшим pitch автоматически поднимаются до 45°. Рельеф по умолчанию 2.8×. Hillshade сильнее на дальнем масштабе и плавно ослабевает к ближнему без JS-переключения terrain.

## Загрузка

PMTiles продолжает работать через HTTP Range, общий LRU cache, NetworkGate и retry. Ручная подкачка соседних DEM/vector tiles удалена: MapLibre запрашивает только реально необходимые tiles. Snow, regional label textures и point objects остаются deferred.

Векторный архив остаётся `data/alan-vector-7.2.pmtiles`, снег — `data/alan-snow-7.3.1.pmtiles`.

## 7.3.8 — crisp vector snow

- Replaces the runtime raster snow overlay with vector PMTiles polygons derived from the existing Sentinel/WorldCover canonical snow mask.
- Shows snow continuously from z7 through the full z14.3 camera range, overzooming z13 vector tiles above z13.
- Removes linear raster resampling and blurred snow edges.
- Keeps DEM hillshade visible through a translucent snow fill and adds snow-only 200 m elevation contours from z9.5 for readable mountain slopes.
- Removes the three legacy snow PMTiles archives from the release package.
