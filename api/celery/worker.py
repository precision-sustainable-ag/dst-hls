import os
import time
import json
import geopandas
import numpy as np
from time import time
from pyproj import Proj, transform

from hlstools import interface
from hlstools.utilities.helpers import NumpyEncoder
from celery import Celery

celery = Celery(__name__)
celery.conf.broker_url = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379")
celery.conf.result_backend = os.environ.get("CELERY_RESULT_BACKEND", "redis://localhost:6379")


@celery.task(name="create_task")
def create_task(payload):
    t0 = time()
    task_geometry = json.dumps(payload["geometry"])
    start_date = payload["startDate"]
    end_date = payload["endDate"]
    max_cloud_cover = int(payload["maxCloudCover"])
    date_range=f"{start_date}/{end_date}"
    infc = interface()
    nr_images, dates, bbox, epsg, data, mask = infc.ndvi_images(task_geometry, date_range=date_range, max_cloud_cover=max_cloud_cover)
    print('data shape:', np.array(data).shape)
    time_elapsed = time() - t0
    if len(epsg)>0:
        inProj = Proj(f'epsg:{epsg[0]}')
        outProj = Proj('epsg:4326')
        x1,y2,x2,y1 = bbox
        yy1, xx1 = transform(inProj,outProj,x1,y1)
        yy2, xx2 = transform(inProj,outProj,x2,y2)
        bbox = [xx1,yy1,xx2,yy2]
        
    json_dump = json.dumps(
                           {
                            'time_elapsed': f"{round(time_elapsed,1)} seconds",
                            'tile_num': nr_images,
                            'dates': dates,
                            'bbox': bbox,
                            'epsg': epsg,
                            'data_array': data,
                            'mask_array': mask,
                            },
                           cls=NumpyEncoder
                          )
    return json_dump

