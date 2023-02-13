import os
import time
import json
import geopandas
import numpy as np
from time import time

from hlstools import interface
from hlstools.utilities.helpers import NumpyEncoder
from celery import Celery
geom_path = './ne_w_agfields.geojson'

celery = Celery(__name__)
celery.conf.broker_url = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379")
celery.conf.result_backend = os.environ.get("CELERY_RESULT_BACKEND", "redis://localhost:6379")


@celery.task(name="create_task")
def create_task(payload):
    t0 = time()
    field = geopandas.read_file(geom_path)
    features = json.loads(field.to_json())["features"]
    roi = features[0]["geometry"]
    roi = json.dumps(roi)
    infc = interface()
    arr = infc.ndvi_images(roi, date_range=f"2021-07-01/2021-07-0{payload}")
    print('arr shape:', np.array(arr).shape)
    time_elapsed = time() - t0
    json_dump = json.dumps(
                           {
                            'time_elapsed': f"{round(time_elapsed,1)} seconds",
                            'tile_num': len(arr),
                            'data_array': arr.data,
                            'mask_array': arr.mask,
                            },
                           cls=NumpyEncoder
                          )
    return json_dump
