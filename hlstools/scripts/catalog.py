"""
script provindg catalog information and
interaction with the HLS data server
"""
import json
import numpy as np
from functools import lru_cache
from decouple import config
from pystac_client import Client
from shapely.geometry import Polygon
import pandas as pd
from ..utilities.auth import setup_netrc, authenticate
from ..utilities.helpers import read_roi_from_file, url_to_s3, epsg_from_id


class Catalog:
    """
    internal wrapper class for interacting with USGS's HLS-CMR-STAC
    """

    def __init__(self, provider="LPCLOUD"):
        self.collections = ["HLSL30.v2.0", "HLSS30.v2.0"]
        self.provider_name = provider
        self.stac_url = config("STAC_URL", default=False, cast=str)
        setup_netrc()
        authenticate()

    @lru_cache(maxsize=2)
    def _fetch_providers(self):
        """
        fetches list of providers - heavy func, hence caching is used
        Returns:
            list -- list of providers
        """
        provider_cat = Client.open(self.stac_url)
        providers = [p for p in provider_cat.get_children()]
        return providers

    @property
    def providers(self):
        """
        fetches stac list of providers from the server
        Returns:
            list -- list of providers
        """
        return self._fetch_providers()

    def read_roi(self, fpath):
        """
        reads geojson file
        Arguments:
            fpath {string} -- path to the roi geojson file
        Returns:
            json -- geometry of roi file in json format
        """
        geom = read_roi_from_file(fpath)
        return geom

    @lru_cache(maxsize=20)
    def connect_to_provider(self, provider=None):
        if not provider:
            provider = self.provider_name
        self.connection = Client.open(f"{self.stac_url}/{provider}/")

    @lru_cache(maxsize=20)
    def search_tiles(self,
                     roi,
                     collections=None,
                     date_range="2021-05-01/2021-08-01"
                     ):
        """
        given a datetime range, an ROI geometry and a list of collection names,
            this function retrieves all available data collections
        Arguments:
            roi {geojson} -- a region of interest in
                geojson or shapely format
        Keyword Arguments:
            collections {list} -- list of data collections
                from provider (default: {None})
            date_range {str} -- range of date times
                format: 2017-01-01T00:00:00Z/2017-12-31T23:59:59Z
                (default: {"2021-05-01/2021-08-01"})
        Returns:
            list -- list of available collections found
        """
        self.connect_to_provider()
        if not collections:
            collections = self.collections
        results = self.connection.search(
            collections=collections,
            max_items=None,
            intersects=roi,
            datetime=date_range,
            limit=250,
        )
        all_items = results.get_all_items()
        geom = json.loads(roi)
        source = Polygon(geom["coordinates"][0])
        all_items_containing = []
        for item in all_items:
            target = Polygon(item.geometry["coordinates"][0])
            if source.within(target):
                all_items_containing.append(item)
        self.all_items = tuple(all_items_containing)
        return self.all_items

    def to_pandas(self):
        d = []
        for col in self.all_items:
            cloud_cover = col.properties["eo:cloud_cover"]
            datetime = col.datetime
            geometry = col.geometry
            id_val = col.id
            epsg = epsg_from_id(id_val)
            links = {}
            for k, v in col.assets.items():
                url = url_to_s3(v.href)
                links[k] = url
            d.append(
                [
                    id_val,
                    col,
                    cloud_cover,
                    datetime,
                    epsg,
                    links,
                    geometry,
                ]
            )
        d = np.array(d)
        columns = [
            "id",
            "item",
            "cloud_cover",
            "datetime",
            "epsg",
            "url",
            "geometry",
        ]
        df = pd.DataFrame(data=d, columns=columns)
        df["datetime"] = pd.to_datetime(df["datetime"])
        df = df.sort_values(by=["datetime"], ascending=True)
        df = df.reset_index(drop=True)
        return df

    @lru_cache(maxsize=20)
    def ndvi_bands_links(self, items, max_cloud_cover=100, s3_links=False):
        """
        retrieves ndvi band urls for found collection of images
        Arguments:
            items {tuple} -- collection of images found for
                a time range and location
        Keyword Arguments:
            max_cloud_cover {int} -- max allowed cloud cover
                in each tile (default: {100})
            s3_links {bool} -- if returned links should
                start with s3:// (default: {False})
        Returns:
            list -- list of links to all ndvi bands
        """
        links = []
        for i in list(items):
            if i.properties["eo:cloud_cover"] <= max_cloud_cover:
                if i.collection_id == "HLSS30.v2.0":
                    bands = S30BANDS
                elif i.collection_id == "HLSL30.v2.0":
                    bands = L30BANDS
                for a in i.assets:
                    if any(b == a for b in bands):
                        links.append(i.assets[a].href)
        if s3_links:
            links = ["s3://" + lnk.split(".gov/")[1] for lnk in links]
        return links
