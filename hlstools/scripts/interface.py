"""
script providing interface capabilities
for categorizing and fetching
images from HLS server
"""
from .catalog import Catalog
from .fetch import Fetch


class Interface:
    def __init__(self):
        self.cat = None

    def ndvi_images(self, geometry, date_range="2021-05-01/2021-08-02"):
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
        self.colls = self.cat.search_tiles(geometry,
                                           date_range=date_range
                                           )
        colls_df = self.cat.to_pandas()
        print(len(self.colls))
        bands = ['blue', 'green', 'red', 'nir', 'cloud']
        fch = Fetch()
        fch.fetch_images(colls_df, bands, geometry, get_rgb=False)
        arr = fch.data_arrays
        return arr
