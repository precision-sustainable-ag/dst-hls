"""
script providing fetching capabilities
for interaction with HLS server
"""
import json

# from functools import lru_cache
import rioxarray
import pyproj
from pyproj import Proj
from shapely.ops import transform
from shapely.geometry import Polygon
import xarray as xr
import rasterio
import numpy as np
from ..utilities.helpers import with_rio, create_session, index_from_filenames, georeference_raster


class Fetch:
    def __init__(self):
        self._masked_array = None
        self._hls_da = None

    def preprocess_roi(self, roi, target_epsg):
        roi = json.loads(roi)
        field_shape = Polygon(roi["coordinates"][0])
        from_CRS = Proj(Proj('epsg:4326').to_proj4(), preserve_units=True)
        to_CRS = Proj(Proj(f'epsg:{target_epsg}').to_proj4(), preserve_units=True)
        project = pyproj.Transformer.from_proj(from_CRS, to_CRS)
        geom_transformed = transform(project.transform, field_shape)
        return geom_transformed

    @with_rio(create_session())
    def fetch_images(self, dataframe, ids, bands, geom, get_rgb=False):
        epsgs = list(dataframe['epsg'])
        if epsgs.count(epsgs[0]) != len(epsgs):
            print('ERROR, more than one coordinate system found!')
            return
        epsg = epsgs[0]
        s3_links = []
        for idd in ids:
            urls = list(dataframe.loc[dataframe["id"] == idd]['url'])[0]
            for band in bands:
                s3_links.append(urls[band])
        new_dim = xr.Variable('uid', index_from_filenames(s3_links))
        chunks = dict(band=1, x=256, y=256)
        roi = self.preprocess_roi(geom, epsg)
        tasks = []
        for link in s3_links:
            task = rioxarray.open_rasterio(link, chunks=chunks).squeeze('band', drop=True).rio.clip([roi])
            tasks.append(task)
        self._hls_ts_da = xr.concat(tasks, dim=new_dim)
        arr = self._hls_ts_da.to_masked_array()
        self._masked_arrays = np.ma.masked_array(arr, mask=(arr == -9999), fill_value=-9999)
        if get_rgb:
            hls_da = rioxarray.open_rasterio(link, chunks=True)
            rgb_arrays = []
            for ix, row in dataframe.iterrows():
                jpg_url = row['url']['browse']
                hls_jpg = rioxarray.open_rasterio(jpg_url, chuncks=True)
                rgb = hls_jpg.values
                bbox = hls_da.rio.bounds()
                transform = rasterio.transform.from_bounds(*bbox, width=1000, height=1000)
                with georeference_raster(rgb, transform) as resampled:
                    rgb_cropped, out_transform = rasterio.mask.mask(resampled, [roi], crop=True)
                    # rgb_cropped_meta = resampled.meta
                    rgb_arrays.append(rgb_cropped)
            self._rgb_arrays = rgb_arrays

    @property
    # @lru_cache(maxsize=10)
    def masked_arrays(self):
        return self._masked_arrays

    @property
    # @lru_cache(maxsize=10)
    def rgb_arrays(self):
        return self._rgb_arrays

    @property
    # @lru_cache(maxsize=10)
    def data_array(self):
        return self._hls_da

    @property
    # @lru_cache(maxsize=10)
    def data_array_clipped(self):
        return self._hls_da_clipped

    def write_to_file(self, raster_path):
        self._hls_da_clip.rio.to_raster(raster_path=raster_path, driver="COG")
