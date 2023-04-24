"""
script providing interface capabilities
for categorizing and fetching
images from HLS server
"""
import pandas as pd
from datetime import timedelta, datetime
import numpy as np
from .catalog import Catalog
from .fetch import Fetch



class Interface:
    def __init__(self):
        self.cat = None

    def ndvi_images(self, geometry, date_range="2021-05-01/2021-08-02", max_cloud_cover=10):
        """
        fetches an ndvi image provided for a certain date and geometry

        Arguments:
            geometry {json} -- heometry to clip image with

        Keyword Arguments:
            date_range {str} -- datetime range with format:
            (default: {"2021-05-01/2021-08-02"})

        Returns:
            numpy array -- an array containing all bands of
            available images in a flatten shape
        """
        self.cat = Catalog()
        start_date = date_range.split('/')[0]
        end_date = date_range.split('/')[1]
        bins = list(pd.date_range(start=start_date, end=end_date, freq='6M').astype(str))
        bins = bins + [end_date]
        res = ['/'.join(x) for x in zip(bins[: -1], bins[1: ])]
        df = pd.DataFrame()
        for dates in res:
            colls = self.cat.search_tiles(geometry, date_range=dates)
            colls_df = self.cat.to_pandas()
            df = pd.concat([df, colls_df])
        df = df.loc[df['cloud_cover'] < max_cloud_cover]
        df = df.drop_duplicates(subset=['id'], keep='first')
        df['datetime'] = pd.to_datetime(df['datetime'])
        df['timedelta'] = df['datetime'].diff().dt.total_seconds()
        ## remove timestamps too close, in this case less than a week
        df = df.loc[~(df['timedelta']<7*24*60)]
        df.reset_index(drop=True, inplace=True)
        if df.shape[0]<1:
            return 0, [], [], [], np.array([]), np.array([])
        bands = ['re1', 'nir', 'cloud']
        fch = Fetch()
        print("IN INTERFACE ....")
        fch.fetch_images(df, bands, geometry, get_rgb=False)
        arr = fch.data_arrays
        nr_images = int(len(arr)/len(bands))
        dates = [datetime.strftime(t, '%y-%m-%d:%H-%M-%S') for t in df.datetime]
        bbox = fch.bbox
        epsg = [t for t in df.epsg]
        return nr_images, dates, bbox, epsg, arr.data, arr.mask
