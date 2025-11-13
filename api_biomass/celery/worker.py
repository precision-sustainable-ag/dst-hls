import os
import time
import json
import geopandas
import numpy as np
from pyproj import Proj, Transformer, transform
import requests
import pandas as pd
from scipy.interpolate import interp1d

from hlstools import interface
from hlstools.utilities.helpers import NumpyEncoder
from celery import Celery


celery = Celery(__name__)
celery.conf.broker_url = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379")
celery.conf.result_backend = os.environ.get("CELERY_RESULT_BACKEND", "redis://localhost:6379")


@celery.task(name="create_task", bind=True)
def create_task(self, payload):
    # n = 30
    # for i in range(0, n):
    #     self.update_state(state='PROGRESS', meta={'message': ''})
    #     time.sleep(1)

    # return n
    ##### STATUS UPDATE #####
    self.update_state(state='PENDING', meta={'message': 'started'})
    t0 = time.time()
    task_geometry = json.dumps(payload["geometry"])
    start_date = payload["startDate"]
    end_date = payload["endDate"]
    max_cloud_cover = int(payload["maxCloudCover"])
    date_range=f"{start_date}/{end_date}"
    infc = interface()
    ##### STATUS UPDATE #####
    self.update_state(state='PENDING', meta={'message': 'getting satellite images metadata'})
    nr_images, dates, bbox, epsg, data, mask = infc.ndvi_images(task_geometry, date_range=date_range, max_cloud_cover=max_cloud_cover, update_func=self.update_state)
    print('data shape::::', np.array(data).shape)
    time_elapsed = time.time() - t0
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
      'options': '',
      'email': 'imagery@psa.org',
    }
    r = requests.get("https://developweather.covercrop-data.org/daily?", params=weather_query)
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
    ##### STATUS UPDATE #####
    self.update_state(state='PENDING', meta={'message': f'received weather data'})
    
    ### calculating biomass from ndvi red edge
    # biomass_array = np.zeros((nr_images, data.shape[1], data.shape[2]))
    # ndvi_re1_first = 0
    cum_par_gdd_ndvi_re1 = np.zeros(data.shape[1:])
    bare_ground_ndvi =  0.094545911
    ndvi_re1_arr = []
    cloud_arr = []
    for i in range(nr_images):
        ##### STATUS UPDATE #####
        # self.update_state(state='PENDING', meta={'message': f'getting image #{i+1}/{nr_images}'})
        self.update_state(state='PENDING', meta={'message': f'getting image {i} from {nr_images}'})
        redEdge = data[3*i+0]
        nir = data[3*i+1]
        cloud = data[3*i+2]
        ndvi_re1 = (nir-redEdge)/(nir+redEdge)
        ndvi_re1_arr.append(ndvi_re1)
        cloud_arr.append(cloud)
    ndvi_re1_arr = np.array(ndvi_re1_arr)
    cloud_arr = np.array(cloud_arr)
    ndvi_re1_arr = ndvi_re1_arr.reshape(ndvi_re1_arr.shape[0], -1)

    x_vals = [list(weather_all.Date.dt.strftime('%Y-%m-%d')).index("20" + el.split(":")[0])  for el in dates]
    # print('dates: ', dates)
    # print('x_vals:', x_vals)
    linfit = interp1d(x_vals, ndvi_re1_arr, axis=0)
    interpolated = linfit(list(range(len(weather_all))))
    # print('interpolated:', interpolated)
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

     ##### STATUS UPDATE #####
    self.update_state(state='PENDING', meta={'message': 'generating biomass GeoJSON'})

    # Create GeoJSON from biomass data
    biomass_geojson = create_biomass_geojson_projected(biomass, bbox, epsg[0])

    ##### STATUS UPDATE #####
    self.update_state(state='PENDING', meta={'message': f'biomass data is calculated'})
    json_dump = json.dumps(
                           {
                            'time_elapsed': f"{round(time_elapsed,1)} seconds",
                            'tile_num': nr_images,
                            'dates': dates,
                            'bbox': bbox,
                            'epsg': epsg,
                            'data_array': biomass,
                            'mask_array': mask_array,
                            'par_gdd44_ndvi': par_gdd44_ndvi,
                            'interpolated': interpolated,
                            'par_gdd44': list(weather_all['PAR']*gdd44),
                            'ndvi_re1_arr': ndvi_re1_arr,
                            'cloud': cloud,
                            'cloud_arr': cloud_arr,
                            'biomass_geojson': biomass_geojson,
                            },
                           cls=NumpyEncoder
                          )
    return json_dump

def create_biomass_geojson_projected(biomass_data, bbox, epsg_code=None):
    """
    Robust conversion of biomass array + bbox (in WGS84) to GeoJSON polygons.

    Args:
        biomass_data: 2D numpy array (height, width)
        bbox: iterable with 4 values in any order, expected lon/lat pairs in WGS84.
              Will be normalized to [lon_min, lat_min, lon_max, lat_max].
        epsg_code: original/projected CRS EPSG (e.g. 32617 or "EPSG:32617").
                   We will convert bbox from WGS84 -> projected CRS for accurate cell sizing.

    Returns:
        GeoJSON FeatureCollection dict
    """
    features = []

    biomass_data = np.array(biomass_data)

    # flatten and filter zeros
    flattened_biomass = biomass_data.flatten()
    non_zero_biomass = flattened_biomass[flattened_biomass != 0]

    if len(non_zero_biomass) == 0:
        return {
            "type": "FeatureCollection",
            "features": []
        }

    biomass_max = float(np.max(non_zero_biomass))
    biomass_min = float(np.min(non_zero_biomass))
    value_range = biomass_max - biomass_min

    # Grid dimensions
    h, w = biomass_data.shape  # Note: shape is (height, width)

    lon_a, lat_a, lon_b, lat_b = bbox[0], bbox[1], bbox[2], bbox[3]
    lon_min = min(lon_a, lon_b)
    lon_max = max(lon_a, lon_b)
    lat_min = min(lat_a, lat_b)
    lat_max = max(lat_a, lat_b)

    # If an epsg_code is provided, transform the WGS84 bbox into that projected CRS
    if epsg_code:
        # normalize epsg string
        if isinstance(epsg_code, int):
            proj_spec = f"EPSG:{epsg_code}"
        else:
            proj_spec = str(epsg_code)
            if not proj_spec.upper().startswith("EPSG:"):
                proj_spec = f"EPSG:{proj_spec}"

        # transformer: WGS84 -> projected CRS (to compute projected cell sizes)
        to_proj = Transformer.from_crs("EPSG:4326", proj_spec, always_xy=True)
        # inverse transformer: projected CRS -> WGS84 (for polygon corners)
        from_proj = Transformer.from_crs(proj_spec, "EPSG:4326", always_xy=True)

        # transform bbox to projected CRS (returns minx, miny, maxx, maxy)
        proj_minx, proj_miny, proj_maxx, proj_maxy = to_proj.transform_bounds(
            lon_min, lat_min, lon_max, lat_max
        )

        # protect against degenerate transforms
        if proj_maxx == proj_minx or proj_maxy == proj_miny:
            raise ValueError(f"Transformed projected bbox is degenerate: {(proj_minx, proj_miny, proj_maxx, proj_maxy)}")

        dX = (proj_maxx - proj_minx) / w
        dY = (proj_maxy - proj_miny) / h

        for i in range(w):
            for j in range(h):
                biomass_val = float(biomass_data[j, i])

                # Skip invalid or zero values
                if biomass_val == 0 or biomass_val == -9999:
                    continue

                # compute cell corners in projected CRS
                x0 = proj_minx + i * dX       # left
                x1 = x0 + dX                  # right
                y1 = proj_maxy - j * dY       # top
                y0 = y1 - dY                  # bottom

                # convert back to WGS84 (always_xy=True => x=lon, y=lat)
                bl_lon, bl_lat = from_proj.transform(x0, y0)
                br_lon, br_lat = from_proj.transform(x1, y0)
                tr_lon, tr_lat = from_proj.transform(x1, y1)
                tl_lon, tl_lat = from_proj.transform(x0, y1)

                polygon_coords = [[
                    [bl_lon, bl_lat],
                    [br_lon, br_lat],
                    [tr_lon, tr_lat],
                    [tl_lon, tl_lat],
                    [bl_lon, bl_lat]
                ]]

                normalized_val = (biomass_val - biomass_min) / value_range if value_range > 0 else 0

                features.append({
                    "type": "Feature",
                    "geometry": {"type": "Polygon", "coordinates": polygon_coords},
                    "properties": {
                        "value": biomass_val,
                        "normalized_value": normalized_val
                    }
                })

    else:
        # fallback: operate in Web Mercator if no epsg provided
        web_mercator = Proj("EPSG:3857")
        wgs84 = Proj("EPSG:4326")

        merc_x_min, merc_y_min = web_mercator(lon_min, lat_min)
        merc_x_max, merc_y_max = web_mercator(lon_max, lat_max)

        dX = (merc_x_max - merc_x_min) / w
        dY = (merc_y_max - merc_y_min) / h

        # inverse conversion convenience
        for i in range(w):
            for j in range(h):
                biomass_val = float(biomass_data[j, i])
                if biomass_val == 0 or biomass_val == -9999:
                    continue

                merc_x0 = merc_x_min + i * dX
                merc_x1 = merc_x0 + dX
                merc_y1 = merc_y_max - j * dY
                merc_y0 = merc_y1 - dY

                bl_lon, bl_lat = web_mercator(merc_x0, merc_y0, inverse=True)
                br_lon, br_lat = web_mercator(merc_x1, merc_y0, inverse=True)
                tr_lon, tr_lat = web_mercator(merc_x1, merc_y1, inverse=True)
                tl_lon, tl_lat = web_mercator(merc_x0, merc_y1, inverse=True)

                polygon_coords = [[
                    [bl_lon, bl_lat],
                    [br_lon, br_lat],
                    [tr_lon, tr_lat],
                    [tl_lon, tl_lat],
                    [bl_lon, bl_lat]
                ]]

                normalized_val = (biomass_val - biomass_min) / value_range if value_range > 0 else 0

                features.append({
                    "type": "Feature",
                    "geometry": {"type": "Polygon", "coordinates": polygon_coords},
                    "properties": {
                        "value": biomass_val,
                        "normalized_value": normalized_val
                    }
                })

    return {
        "type": "FeatureCollection",
        "features": features,
        "properties": {
            "biomass_min": biomass_min,
            "biomass_max": biomass_max,
            "value_range": value_range
        }
    }