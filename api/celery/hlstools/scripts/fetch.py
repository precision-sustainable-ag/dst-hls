"""
script providing fetching capabilities
for interaction with HLS server
"""
import json

# from functools import lru_cache
import rioxarray
from functools import lru_cache
import pyproj
from pyproj import Proj
from shapely.ops import transform
from shapely.geometry import Polygon
import xarray as xr
import rasterio
import numpy as np
from ..utilities.helpers import with_rio, create_session, index_from_filenames, georeference_raster
from ..utilities.constants import S30BANDS, L30BANDS


class Fetch:
    def __init__(self):
        self._masked_array = None
        self._hls_da = None

    @lru_cache()
    def preprocess_roi(self, roi, target_epsg):
        roi = json.loads(roi)
        field_shape = Polygon(roi["coordinates"][0])
        from_CRS = Proj(Proj('epsg:4326').to_proj4(), preserve_units=True)
        to_CRS = Proj(Proj(f'epsg:{target_epsg}').to_proj4(), preserve_units=True)
        project = pyproj.Transformer.from_proj(from_CRS, to_CRS)
        geom_transformed = transform(project.transform, field_shape)
        return geom_transformed

    @with_rio(create_session())
    def fetch_images(self, dataframe, bands, geom, ids=None, get_rgb=False):
        # epsgs = list(dataframe['epsg'])
        # if epsgs.count(epsgs[0]) != len(epsgs):
        #     print('ERROR, more than one coordinate system found!')
        #     return
        # epsg = epsgs[0]
        if ids is None:
            ids = dataframe.id
        s3_links = []
        epsg_list = []
        for idd in ids:
            df_row = dataframe.loc[dataframe["id"] == idd]
            epsg = list(df_row['epsg'])[0]
            urls = list(df_row['url'])[0]
            for band in bands:
                if 'L30' in idd:
                    band_name = L30BANDS[band]
                else:
                    band_name = S30BANDS[band]
                s3_links.append(urls[band_name])
                epsg_list.append(epsg)
        new_dim = xr.Variable('uid', index_from_filenames(s3_links))
        chunks = dict(band=1, x=256, y=256)
        # roi = self.preprocess_roi(geom, epsg)
        tasks = []
        for link, epsg in zip(s3_links, epsg_list):
            print(link, epsg)
            roi = self.preprocess_roi(geom, epsg)
            print("roi processed")
            task = rioxarray.open_rasterio(link, chunks=chunks).squeeze('band', drop=True)
            print("squeezed")
            task = task.rio.clip([roi])
            print("clipped")
            tasks.append(task)
        self._hls_ts_da = xr.concat(tasks, dim=new_dim)
        # self._hls_ts_da = self._hls_ts_da.rio.clip([roi])
        arr = self._hls_ts_da.to_masked_array()
        self._data_arrays = np.ma.masked_array(arr, mask=(arr == -9999), fill_value=-9999)
        self.bbox = self._hls_ts_da.rio.bounds()
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
    def data_arrays(self):
        return self._data_arrays

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
