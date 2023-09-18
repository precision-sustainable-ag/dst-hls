import os
import time
import json
import geopandas
import numpy as np
from time import time
from pyproj import Proj, transform
import requests
import pandas as pd
from scipy.interpolate import interp1d

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
    
    longitude = (bbox[0]+bbox[2])/2
    latitude = (bbox[1]+bbox[3])/2
    weather_query = {
      'lat': latitude,
      'lon': longitude,
      'start': "20" + dates[0].split(":")[0],
      'end': "20" + dates[-1].split(":")[0],
      'output': 'csv',
      'options': ''
    }
    r = requests.get("https://api.precisionsustainableag.org/weather/daily?", params=weather_query)
    weather_parsed = pd.DataFrame([x.split(',') for x in r.text.split('\n')])
    weather_parsed.columns = weather_parsed.iloc[0,:]
    weather_parsed = weather_parsed.iloc[1:,:]
    weather_parsed['Rad'] = (weather_parsed['shortwave_radiation'].astype(float) * float(60*60/1000000)).apply(lambda x: np.round(x, 3))   # convert W/m2 to MJ/m2 day
    weather_parsed['PAR'] = 0.48 * weather_parsed['Rad'].astype(float)
    weather_parsed['Temp_min'] = weather_parsed['min_air_temperature'].astype(float)
    weather_parsed['Temp_max'] = weather_parsed['max_air_temperature'].astype(float)
    weather_parsed['GDD_4.4_day'] = (weather_parsed['Temp_min'] + weather_parsed['Temp_max'])/2 - 4.4
    weather_parsed['Date'] = pd.to_datetime(weather_parsed['date'])
    weather_all = weather_parsed[['Date', 'Rad', 'PAR', 'GDD_4.4_day']]
    
    ### calculating biomass from ndvi red edge
    # biomass_array = np.zeros((nr_images, data.shape[1], data.shape[2]))
    # ndvi_re1_first = 0
    cum_par_gdd_ndvi_re1 = np.zeros(data.shape[1:])
    bare_ground_ndvi =  0.094545911
    ndvi_re1_arr = []
    for i in range(nr_images):
        redEdge = data[3*i+0]
        nir = data[3*i+1]
        cloud = data[3*i+2]
        ndvi_re1 = (nir-redEdge)/(nir+redEdge)
        ndvi_re1_arr.append(ndvi_re1)
    ndvi_re1_arr = np.array(ndvi_re1_arr)
    ndvi_re1_arr = ndvi_re1_arr.reshape(ndvi_re1_arr.shape[0], -1)

    x_vals = [list(weather_all.Date.dt.strftime('%Y-%m-%d')).index("20" + el.split(":")[0])  for el in dates]
    linfit = interp1d(x_vals, ndvi_re1_arr, axis=0)
    interpolated = linfit(list(range(len(weather_all))))
    interpolated[0,:] = bare_ground_ndvi
    interpolated = interpolated - bare_ground_ndvi
    gdd44 = weather_all['GDD_4.4_day']
    gdd44[gdd44<0] = 0
    par_gdd44 = list(weather_all['PAR']*gdd44)
    par_gdd44 = np.repeat(par_gdd44, interpolated.shape[1]).reshape(-1, interpolated.shape[1])
    par_gdd44_ndvi = par_gdd44*interpolated
    cum_par_gdd_ndvi_re1 = np.cumsum(par_gdd44_ndvi, axis=0)
    estimated_biomass_kg_ha = -1246.8 + 3.9025 * cum_par_gdd_ndvi_re1
    estimated_biomass_kg_ha[cum_par_gdd_ndvi_re1 <= 595.064] = 83.1187 + 1.6677 * cum_par_gdd_ndvi_re1[cum_par_gdd_ndvi_re1 <= 595.064]
    estimated_biomass_kg_ha[cum_par_gdd_ndvi_re1==0] = 0

    # v = estimated_biomass_kg_ha.reshape(len(cum_par_gdd_ndvi_re1), data.shape[1], data.shape[2])[:, cloud!=255].mean(1)

    mask_array = mask[0::3, :, :][-1,:,:]
    biomass = estimated_biomass_kg_ha[-1].reshape(data.shape[1:])
    biomass[cloud==255] = 0
    
    print('data.shape: ', data.shape)
    print('biomass shape: ', biomass.shape)
    
    json_dump = json.dumps(
                           {
                            'time_elapsed': f"{round(time_elapsed,1)} seconds",
                            'tile_num': nr_images,
                            'dates': dates,
                            'bbox': bbox,
                            'epsg': epsg,
                            'data_array': biomass,
                            'mask_array': mask_array,
                            },
                           cls=NumpyEncoder
                          )
    return json_dump

