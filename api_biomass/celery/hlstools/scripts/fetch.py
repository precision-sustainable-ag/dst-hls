"""
script providing fetching capabilities
for interaction with HLS server
"""
import os
import json
import time
import numpy as np
from datetime import datetime
# from functools import lru_cache
import rioxarray
from functools import lru_cache
import pyproj
from decouple import config
import requests
import boto3
import string
from pyproj import Proj
from shapely.ops import transform
from shapely.geometry import Polygon
import xarray as xr
import rasterio
import rasterio as rio
from rasterio.session import AWSSession
from ..utilities.helpers import with_rio, create_session, index_from_filenames, georeference_raster
from ..utilities.constants import S30BANDS, L30BANDS


class Fetch:
    def __init__(self):
        self._masked_array = None
        self._hls_da = None

    # @lru_cache()
    def preprocess_roi(self, roi, target_epsg):
        roi = json.loads(roi)
        field_shape = Polygon(roi["coordinates"][0])
        from_CRS = Proj(Proj('epsg:4326').to_proj4(), preserve_units=True)
        to_CRS = Proj(Proj(f'epsg:{target_epsg}').to_proj4(), preserve_units=True)
        project = pyproj.Transformer.from_proj(from_CRS, to_CRS)
        geom_transformed = transform(project.transform, field_shape)
        return geom_transformed

    # @with_rio(create_session())
    def fetch_images(self, dataframe, bands, geom, ids=None, get_rgb=False, update_func=None):
        temp_aws_s3_token = '/home/.aws_s3_session.json'
        temp_creds_url = config("TEMP_CRED_URL", cast=str)
        ##### STATE UPDATE #####
        if update_func: update_func(state='PENDING', meta={'message': f'generate new token'})
        if os.path.exists(temp_aws_s3_token):
            print(f"s3 token exists")
            with open(temp_aws_s3_token) as f:
                creds = json.load(f)
                exp_dt = datetime.strptime(creds['expiration'], '%Y-%m-%d %H:%M:%S%z').replace(tzinfo=None)
                dt = (exp_dt-datetime.utcnow()).total_seconds()/3600
                print(f"current s3 creds: ", creds)
                print(f"current s3 curr time: ", datetime.utcnow())
                print(f"current s3 expire time: ", exp_dt)
                print(f"current s3 expire delta: ", dt)
                if dt < 0.1:
                    print("refreshing s3 token ...")
                    creds = requests.get(temp_creds_url).json()
                    print('new creds: ', creds)
                    with open(temp_aws_s3_token, 'w', encoding='utf-8') as f:
                        print("writing new s3 token file !")
                        json.dump(creds, f, ensure_ascii=False, indent=4)
        else:
            print("s3 token file not exist !")
            creds = requests.get(temp_creds_url).json()
            print('creds', creds)
            with open(temp_aws_s3_token, 'w', encoding='utf-8') as f:
                print("writing new s3 token file !")
                json.dump(creds, f, ensure_ascii=False, indent=4)
            
        print("creds: ", creds)
        ##### STATE UPDATE #####
        if update_func: update_func(state='PENDING', meta={'message': f'establishing connection with HLS server'})
        session = boto3.Session(
            aws_access_key_id=creds["accessKeyId"],
            aws_secret_access_key=creds["secretAccessKey"],
            aws_session_token=creds["sessionToken"],
            region_name="us-west-2",
        )
        
        rio_env = rio.Env(
            AWSSession(session),
            # GDAL_DISABLE_READDIR_ON_OPEN="TRUE",
            GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
            CPL_VSIL_CURL_ALLOWED_EXTENSIONS="TIF",
            GDAL_HTTP_COOKIEFILE=os.path.expanduser("/home/cookies.txt"),
            GDAL_HTTP_COOKIEJAR=os.path.expanduser("/home/cookies.txt"),
        )
        ###################
        rio_env.__enter__()
        ####################
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
        ##### STATE UPDATE #####
        if update_func: update_func(state='PENDING', meta={'message': f'found {int(len(s3_links)/3)} images'})
        time.sleep(0.1)
        new_dim = xr.Variable('uid', index_from_filenames(s3_links))
        chunks = dict(band=1, x=256, y=256)
        # roi = self.preprocess_roi(geom, epsg)
        tasks = []
        kk = 1
        for link, epsg in zip(s3_links, epsg_list):
            ##### STATE UPDATE #####
            if update_func and kk%3==0: update_func(state='PENDING', meta={'message': f'fetching image #{int(kk/3)}/{int(len(s3_links)/3)}'})
            # print(link, epsg)
            roi = self.preprocess_roi(geom, epsg)
            # print(link)
            task = rioxarray.open_rasterio(link, chunks=chunks).squeeze('band', drop=True)
            # print("squeezed")
            task = task.rio.clip([roi])
            print("clipped")
            tasks.append(task)
            kk+=1
            
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
        ###################
        rio_env.__exit__()
        ###################
    @property
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
