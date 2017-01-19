from __future__ import absolute_import, division, print_function

try:
    from urlparse import parse_qs
except ImportError:
    from urllib.parse import parse_qs

# travis can only get earlier version of rasterio which doesn't have MemoryFile, so
# - tell pylint to ingnore inport error
# - catch ImportError so pytest doctest don't fall over
try:
    from rasterio.io import MemoryFile  # pylint: disable=import-error
except ImportError:
    MemoryFile = None
from affine import Affine

import datacube


def application(environ, start_response):
    dc = datacube.Datacube()

    args = {key.lower(): (val[0] if len(val) == 1 else val) for key, val in parse_qs(environ['QUERY_STRING']).items()}

    if args.get('request') == 'GetMap':
        return get_map(dc, args, start_response)

    if args.get('request') == 'GetCapabilities':
        return get_capabilities(args, start_response)

    data = b"""<!DOCTYPE html>
<html>
<head>
	<title>Map</title>
	<meta charset="utf-8" />
	<meta name="viewport" content="width=device-width, initial-scale=1.0">
	<link rel="shortcut icon" type="image/x-icon" href="docs/images/favicon.ico" />
	<link rel="stylesheet" href="https://unpkg.com/leaflet@1.0.2/dist/leaflet.css" />
	<script src="https://unpkg.com/leaflet@1.0.2/dist/leaflet.js"></script>
</head>
<body>

<div id="mapid" style="width: 1200px; height: 800px;"></div>
<script>
	var mymap = L.map('mapid').setView([-35.28, 149.12], 12);

	L.tileLayer.wms(
        "http://localhost:8000/?",
        {
            minZoom: 6,
            maxZoom: 19,
            layers: "ls8_nbar_albers",
            format: 'image/png',
            transparent: true,
            attribution: "Teh Cube"
        }
    ).addTo(mymap);
</script>
</body>
</html>
"""

    start_response("200 OK", [
        ("Content-Type", "text/html"),
        ("Content-Length", str(len(data)))
    ])
    return iter([data])


def _set_resampling(m, resampling):
    mc = m.copy()
    mc['resampling'] = resampling
    return mc


def _write_png(data, bands):
    width = data[data.crs.dimensions[1]].size
    height = data[data.crs.dimensions[0]].size

    with MemoryFile() as memfile:
        with memfile.open(driver='PNG',
                          width=width,
                          height=height,
                          count=len(bands),
                          affine=Affine.identity(),
                          nodata=0,
                          dtype='uint8') as thing:
            for idx, band in enumerate(bands, start=1):
                scaled = (data[band].values[0, ::-1] / 12.0).astype('uint8')
                thing.write_band(idx, scaled)
        return memfile.read()


def _get_geobox(args):
    width = int(args['width'])
    height = int(args['height'])
    minx, miny, maxx, maxy = map(float, args['bbox'].split(','))
    crs = datacube.model.CRS(args['srs'])

    affine = Affine.translation(minx, miny) * Affine.scale((maxx - minx) / width, (maxy - miny) / height)
    return datacube.model.GeoBox(width, height, affine, crs)


def _load_data(dc, geobox, product, bands):
    prod = dc.index.products.get_by_name(product)

    measurements = [_set_resampling(m, 'cubic') for name, m in prod.measurements.items() if name in bands]

    datasets = dc.find_datasets(product=product, geopolygon=geobox.extent, time=('2015-01-01', '2015-02-01'))
    sources = dc.group_datasets(datasets, datacube.api.query.query_group_by('solar_day'))

    with datacube.set_options(reproject_threads=1):
        return dc.load_data(sources[0:1], geobox, measurements)


def get_map(dc, args, start_response):
    geobox = _get_geobox(args)

    product = 'ls8_nbar_albers'
    bands = ('red', 'green', 'blue')

    data = _load_data(dc, geobox, product, bands)

    body = _write_png(data, bands)
    start_response("200 OK", [
        ("Content-Type", "image/png"),
        ("Content-Length", str(len(body)))
    ])
    return iter([body])


def get_capabilities(args, start_response):
    pass