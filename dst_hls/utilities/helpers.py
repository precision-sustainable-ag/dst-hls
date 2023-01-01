"""
collection of helper functions to facilitate functionalities
"""
import os
import json
from pathlib import Path
import geopandas
import rasterio as rio
from rasterio.session import AWSSession
from functools import lru_cache, wraps
import cachetools.func
from decouple import config
import requests
import boto3
import string
from pyproj import CRS
from datetime import datetime
from contextlib import contextmanager  
from rasterio import Affine, MemoryFile


def url_to_s3(url):
    return "s3://" + url.split(".gov/")[1]


def get_project_root():
    """
    gives the root project of current package
    Returns:
        Path -- path of root directory of the package
    """
    return Path(__file__).parent.parent.parent


def read_roi_from_file(fpath):
    """
    reads an roi geometry form geojson
    Arguments:
        fpath {string} -- file path of roi file
    Returns:
        json -- json representation of the roi geometry
    """
    field = geopandas.read_file(fpath)
    roi = json.loads(field.to_json())["features"][0]["geometry"]
    roi = json.dumps(roi)
    return roi


def with_rio(session):
    """
    decorator to wrap the rasterio operation code and
    provide the environment contect for GDAL and AWS Session

    Args:
        session (rasterio.session.AWSSession): an aws session
            costumized for rasterio
    """

    def wrap(func):
        def wrapped_f(*args, **kwargs):
            rio_env = rio.Env(
                AWSSession(session),
                GDAL_DISABLE_READDIR_ON_OPEN="TRUE",
                GDAL_HTTP_COOKIEFILE=os.path.expanduser("~/cookies.txt"),
                GDAL_HTTP_COOKIEJAR=os.path.expanduser("~/cookies.txt"),
            )
            rio_env.__enter__()
            func(*args, **kwargs)
            rio_env.__exit__()

        return wrapped_f

    return wrap


# ttl caching for time based control on the refresh rate
@cachetools.func.ttl_cache(maxsize=9999, ttl=1 * 60)
def get_temp_creds(ttl_hash=None):
    """
    function for getting a temp credential
    from USGS server every hour

    Args:
        ttl_hash (hash, optional): a ttl hash container to
        keep tabs on how long time passed since last
        retrieval. Defaults to None.

    Returns:
        json: credentials in json format
    """
    del ttl_hash
    temp_creds_url = config("TEMP_CRED_URL", cast=str)
    return requests.get(temp_creds_url).json()


@lru_cache(maxsize=2)  # keeping the cache size small for mem leak
def create_session():
    """
    generates an S3 AWS session from
    temp credentials given by USGS server

    Returns:
        AWSSession: an aws session instance
    """
    creds = get_temp_creds()
    session = boto3.Session(
        aws_access_key_id=creds["accessKeyId"],
        aws_secret_access_key=creds["secretAccessKey"],
        aws_session_token=creds["sessionToken"],
        region_name="us-west-2",
    )
    return session


def hash_dict(func):
    """
    Transform mutable dictionnary Into immutable
    Useful to be compatible with cache
    """

    class HDict(dict):
        def __hash__(self):
            return hash(frozenset(self.items()))

    @wraps(func)
    def wrapped(*args, **kwargs):
        args = tuple([HDict(arg) if isinstance(arg, dict) else arg for arg in args])
        kwargs = {k: HDict(v) if isinstance(v, dict) else v for k, v in kwargs.items()}
        return func(*args, **kwargs)

    return wrapped


def mgrs_to_epsg(mgrs):
    zone = mgrs[:2]
    mgrs_dir = string.ascii_uppercase.index(mgrs[2])
    utm_dir = "south" if mgrs_dir < 12 else "north"
    crs = CRS.from_string(f"+proj=utm +zone={zone} +{utm_dir}")
    return crs.to_authority()[1]


def epsg_from_id(id_str):
    mgrs_str = id_str.split(".")[2]  # 'T14SPG'
    return mgrs_to_epsg(mgrs_str[1:])  # T is unnecessary


def index_from_filenames(file_links):
    '''
    Helper function to create a unique DatetimeIndex + band name
    '''
    return [
        # f.split('.')[-2] + datetime.strptime(f.split('.')[-5], '%Y%jT%H%M%S')
        f.split('.')[-2] + '_' + f.split('.')[-5]
        for f in file_links
        ]


@contextmanager
def georeference_raster(data, transform):
    """
    use context manager so DatasetReader and
    MemoryFile get cleaned up automatically

    Arguments:
        data {_type_} -- _description_
        transform {_type_} -- _description_

    Yields:
        _type_ -- _description_
    """
    with MemoryFile() as memfile:
        with memfile.open(
            driver='GTiff',
            height=1000,
            width=1000,
            count=3,
            dtype='uint8',
            transform=transform,
        ) as dataset:  # Open as DatasetWriter
            dataset.write(data)
            del data

        with memfile.open() as dataset:  # Reopen as DatasetReader
            yield dataset  # Note yield not return
