import json
import numpy as np
import math
import random
import re
from typing import Union, List, Dict, Any
from typing_extensions import Self
from fastapi import FastAPI, Depends, Query
from fastapi.exceptions import HTTPException
from fastapi.responses import RedirectResponse, Response, JSONResponse
from pydantic import BaseModel, Field, validator, ValidationError, model_validator
from typing import List, Optional, Literal
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
# from .constants import species, plant_groups
from .utilities.helpers import create_biomass_geojson, get_center
import httpx
import asyncio
import shapely
from shapely.geometry import shape, box, Point
from shapely.ops import transform, unary_union
from shapely.validation import make_valid
from pyproj import Transformer
import tempfile
import zipfile
from pathlib import Path
import geopandas as gpd
import io
from datetime import datetime
import uuid
from collections import defaultdict

description = """
Plants Factors API for Ncalc DST tool. 🌱 🌿 🍀
"""

app = FastAPI(
    title="Plants Factors API - CC-NCALC",
    description=description,
    version="0.0.1",
    terms_of_service="For more information about Precision Sustainable Agriculture projects, please visit https://precisionsustainableag.org/",
    contact={
        "name": "Precision Sustainable Agriculture",
        "url": "https://precisionsustainableag.org/",
    },
)

origins = ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Gzip responses for clients that send Accept-Encoding: gzip (browsers do automatically).
# GeoJSON compresses ~10x; level 5 is much faster than the default 9 for nearly the same size.
app.add_middleware(GZipMiddleware, minimum_size=1000, compresslevel=5)

with open('app/assets/summarized_lookup_table_new.json') as fp:
    group_lut = json.loads(fp.read())

with open('app/assets/species_group_map.json') as fp:
    species_group_map = json.load(fp)

def build_species_lookup_table(group_lut, species_group_map):
    species_lut = {}

    for group, species_list in species_group_map.items():
        group_stages = group_lut.get(group, {})

        for species in species_list:
            species_lut.setdefault(species, {})

            for stage, values in group_stages.items():
                species_lut[species][stage] = {
                    "mean_carb": values.get("mean_carb", 0),
                    "mean_holocellulose": values.get("mean_holocellulose", 0),
                    "mean_lignin": values.get("mean_lignin", 0),
                    "mean_n": values.get("mean_n", 0),
                }

    return species_lut

plant_growth_lut = build_species_lookup_table(group_lut, species_group_map)
    
# species_lower = {}
# for key, val in species.items():
#     species_lower[key.lower()] = [v.lower() for v in val]


class PlantFactors(BaseModel):
    plant_species: Optional[str] = Field (Query(..., description="Input a species name"))
    growth_stage: Optional[str] = Field (Query(..., description="Type in plant's growth stage"))
    @model_validator(mode='after')
    def check_growth_stage(self) -> 'PlantFactors':
        if not self.plant_species in plant_growth_lut.keys():
             raise HTTPException(status_code=422, detail='Wrong choice of plant species')
         
        if not self.growth_stage in plant_growth_lut[self.plant_species]:
             raise HTTPException(status_code=422, detail='Wrong plant growing stage was entered')
        return self


@app.get("/")
async def docs_redirect():
    return RedirectResponse(url='/docs')


@app.get("/health")
def read_root():
    return {"health": "ok"}


@app.get("/species")
def read_species():
    return sorted(list(plant_growth_lut.keys()))

@app.get("/species/{group}")
def read_species_group(group):
    return sorted(list(species_group_map.get(group, [])))


@app.get("/plantgroups")
def read_plantgroups():
    return sorted(list(species_group_map.keys()))


@app.get("/plantgrowthstages")
def read_plantgrowthstages():
    growth_stages = {}
    for plant in plant_growth_lut.keys():
        growth_stages[plant] = sorted(list(plant_growth_lut[plant].keys()))
    return growth_stages


@app.get("/allplantfactors")
def read_plantfactors():
    return plant_growth_lut


@app.get("/plantfactors")
def read_plantfactors(factors: PlantFactors = Depends()):
    return plant_growth_lut[factors.plant_species][factors.growth_stage]

async def calculate_nitrogen_pm3d(biomass_geojson, species, growth_stage, start, end):
    species_lookup_values = {}
    for index, s in enumerate(species):
        if not group_lut.get(s).get(growth_stage[index]):
            species_lookup_values[s] = group_lut.get(s).get("Unknown growth stage")
        else:
            species_lookup_values[s] = group_lut.get(s).get(growth_stage[index])

    features = biomass_geojson["features"]

    # Pre-compute weighted properties for all features upfront
    query_params_list = []
    for feature in features:
        lon, lat = get_center(feature)
        biomass = float(feature["properties"]["biomass_average"])
        species_data = feature["properties"].get("species_biomass_average", {})

        if species_data and biomass > 0:
            total_biomass = sum(species_data.values())
            weighted_n, weighted_carb, weighted_cell, weighted_lign = 0, 0, 0, 0

            for species_name, species_biomass in species_data.items():
                weight = species_biomass / total_biomass
                species_props = species_lookup_values.get(species_name, {})
                weighted_n += weight * species_props.get("mean_n", 2.726053687272728)
                weighted_carb += weight * species_props.get("mean_carb", 56.03424242424243)
                weighted_cell += weight * species_props.get("mean_holocellulose", 28.401123736363637)
                weighted_lign += weight * species_props.get("mean_lignin", 5.989393939393938)
        else:
            weighted_n = weighted_carb = weighted_cell = weighted_lign = 0

        query_params_list.append({
            "lat": lat,
            "lon": lon,
            "biomass": biomass,
            "start": start,
            "end": end,
            "n": weighted_n,
            "carb": weighted_carb,
            "cell": weighted_cell,
            "lign": weighted_lign,
            "summary": True,
        })

    # Fire all requests concurrently
    MAX_RETRIES = 3
    RETRY_DELAY = 2
    semaphore = asyncio.Semaphore(15)
    async def fetch_single(client, params):
        print(params)
        async with semaphore:
            for attempt in range(MAX_RETRIES):
                try:
                    response = await client.get("https://developapi.covercrop-ncalc.org/surface", params=params)
                except httpx.RequestError as e:
                    print(f"Request error {type(e).__name__}: {repr(e)} (attempt {attempt + 1})")
                    if attempt < MAX_RETRIES - 1:
                        await asyncio.sleep(RETRY_DELAY)
                        continue
                    return 0

                if response.status_code == 200:
                    try:
                        data = response.json()
                    except Exception as e:
                        print(f"JSON decode error: {e}")
                        return 0

                    if isinstance(data, dict) and "error" in data:
                        print(f"Error from API: {data['error']} (attempt {attempt + 1})")
                        if data['error'] == 'No SSURGO data found':
                            return 0  # No retries needed here
                        if attempt < MAX_RETRIES - 1:
                            await asyncio.sleep(RETRY_DELAY)
                            continue
                        return 0

                    elif isinstance(data, dict):
                        try:
                            if "surface" in data and data["surface"]:
                                return data["surface"][0].get("MinNfromFOM", 0) or 0
                        except (KeyError, IndexError, TypeError):
                            print("Missing MinNfromFOM for feature")
                        return 0
                else:
                    print(f"Error: {response.status_code}, {response.text}")
                    return 0
            return 0

    async with httpx.AsyncClient(timeout=30.0) as client:
        results = await asyncio.gather(
            *[fetch_single(client, params) for params in query_params_list]
        )

    # Assign results back and compute averages
    total_weighted_n, number_weighted_n = 0, 0
    total_n_credit, number_n_credit = 0, 0

    for feature, min_n, params in zip(features, results, query_params_list, strict=True):
        feature["properties"]["MinNfromFOM"] = min_n

        if min_n >= 0:
            area = feature["properties"].get("area_acres", 0)
            total_n_credit += min_n * area
            number_n_credit += area

        if params["n"] > 0:
            total_weighted_n += params["n"]
            number_weighted_n += 1

    average_weighted_n = total_weighted_n / number_weighted_n if number_weighted_n > 0 else 0
    average_n_credit = total_n_credit / number_n_credit if number_n_credit > 0 else 0

    return biomass_geojson, average_weighted_n, average_n_credit

class Feature(BaseModel):
    type: str
    geometry: Dict[str, Any]
    properties: Dict[str, Any]

class FeatureCollection(BaseModel):
    type: str
    features: List[Feature]

class BiomassPayload(BaseModel):
    data_array: List[List[float]] = [[1,2], [3,4]]
    bbox: List[float] = [0,0,0,0]
    species: Union[str, List[str]] = ""
    growth_stage: Union[str, List[str]] = ""
    start: str = ""
    end: str = ""
    mode: str = "satellite",
    field_geometry: Dict[str, Any]
    has_fixed_rate: bool = False
    target_n: float = 0.0
    feature_collection: FeatureCollection = FeatureCollection(type="FeatureCollection", features=[])
    property_key: str = ""
    multiplier: float = 1.0
    grid_size: float = 1.0

@app.post("/nitrogen")
async def read_nitrogen(biomass_payload: BiomassPayload):

    data_array = np.array(biomass_payload.data_array)
    bbox = biomass_payload.bbox
    species = biomass_payload.species
    growth_stage = biomass_payload.growth_stage
    start = biomass_payload.start
    end = biomass_payload.end
    mode = biomass_payload.mode
    field_geometry = biomass_payload.field_geometry
    has_fixed_rate = biomass_payload.has_fixed_rate
    target_n = biomass_payload.target_n
    input_features = biomass_payload.feature_collection.features
    property_key = biomass_payload.property_key
    multiplier = biomass_payload.multiplier
    grid_size = biomass_payload.grid_size

    biomass_geojson = create_biomass_geojson(data_array, bbox, grid_size)

    if mode == 'satellite' or mode == 'sampled':

        combined_geom = shape(field_geometry)
        # centroid = combined_geom.centroid
        # lon, lat = centroid.x, centroid.y

        if not has_fixed_rate:
            all_features = [] # Stores {geometry, properties} for each input feature
            # Parse GeoJSON features into shapely geometry objects
            for feature in input_features:
                geom_data = feature.geometry
                geom = shape(geom_data)
                all_features.append({
                    'geometry': geom,
                    'properties': feature.properties
                })

        project = Transformer.from_crs("EPSG:4326", "EPSG:6933", always_xy=True).transform

        intersecting_features = []

        # This loop calculates target nitrogen for each grid cell
        for feature in biomass_geojson["features"]:
            grid_cell = shape(feature["geometry"])
            cell_intersection = grid_cell.intersection(combined_geom)

            if cell_intersection.is_empty:
                continue

            weighted_average = 0

            if has_fixed_rate:
                # Skip spatial intersection logic and use the fixed value provided
                weighted_average = target_n
            else:
            # Check intersection with each feature and calculate area-weighted average
                feature_intersections = []
                total_intersect_area = 0
                weighted_property_sum = 0

                for feat_idx, feat in enumerate(all_features):
                    feat_geom = feat['geometry']
                    poly_intersection = cell_intersection.intersection(feat_geom)

                    if not poly_intersection.is_empty:
                        poly_intersection_area = transform(project, poly_intersection).area
                        property_value = feat['properties'].get(property_key, 0)

                        feature_intersections.append({
                            "feature_id": feat_idx,
                            "intersection_area_m2": poly_intersection_area,
                            "intersection_area_acres": poly_intersection_area / 4046.86,
                            "percentage_of_grid": (poly_intersection_area / cell_intersection.area) * 100,
                            "property_value": property_value,
                        })

                        total_intersect_area += poly_intersection_area
                        weighted_property_sum += property_value * poly_intersection_area

                weighted_average = weighted_property_sum / total_intersect_area if total_intersect_area > 0 else 0

            cell_intersection_m = transform(project, cell_intersection)
            area_m2 = cell_intersection_m.area
            area_acres = area_m2 / 4046.86

            feature["geometry"] = cell_intersection.__geo_interface__
            feature["properties"]["target_n"] = weighted_average
            feature["properties"]["area_acres"] = area_acres

            intersecting_features.append(feature)

        biomass_geojson["features"] = intersecting_features

        if not plant_growth_lut.get(species).get(growth_stage):
            species_lookup_values = plant_growth_lut.get(species).get("Unknown growth stage")
        else:
            species_lookup_values = plant_growth_lut.get(species).get(growth_stage)

        lats, lons, biomasses, n_targets = [], [], [], []

        for feature in biomass_geojson["features"]:
            lon, lat = get_center(feature)
            biomass = feature["properties"]["biomass_average"]
            n_target = feature["properties"]["target_n"] * multiplier

            lats.append(lat)
            lons.append(lon)
            biomasses.append(biomass)
            n_targets.append(n_target)

        batch_size = 10
        MAX_RETRIES = 3
        RETRY_DELAY = 2

        async with httpx.AsyncClient(timeout=30.0) as client:
            for i in range(0, len(lats), batch_size):
                query_params = {
                    "lat": [round(v, 5) for v in lats[i:i+batch_size]],
                    "lon": [round(v, 5) for v in lons[i:i+batch_size]],
                    "biomass": biomasses[i:i+batch_size],
                    "start": start,
                    "end": end,
                    "n": species_lookup_values["mean_n"],
                    "carb": species_lookup_values["mean_carb"],
                    "cell": species_lookup_values["mean_holocellulose"],
                    "lign": species_lookup_values["mean_lignin"],
                    "summary": True,
                }
                # print(query_params)
                for attempt in range(MAX_RETRIES):
                    try:
                        response = await client.get("https://developapi.covercrop-ncalc.org/surface", params=query_params)
                    except httpx.RequestError as e:
                        print(f"Request error {type(e).__name__}: {repr(e)} (attempt {attempt + 1})")
                        if attempt < MAX_RETRIES - 1:
                            await asyncio.sleep(RETRY_DELAY)
                            continue
                        else:
                            # Set 0 for the whole batch after final failure
                            for j in range(batch_size):
                                feature_index = i + j
                                if feature_index < len(biomass_geojson["features"]):
                                    biomass_geojson["features"][feature_index]["properties"]["MinNfromFOM"] = 0
                                    biomass_geojson["features"][feature_index]["properties"]["ReqN"] = 0
                            break

                    if response.status_code == 200:
                        try:
                            data = response.json()
                        except Exception as e:
                            print(f"JSON decode error: {e}")
                            data = {}

                        if isinstance(data, dict) and "error" in data:
                            print(f"Error from API: {data['error']} (attempt {attempt + 1})")
                            if data['error'] == 'No SSURGO data found':
                                attempt = MAX_RETRIES # No retries needed here
                            if attempt < MAX_RETRIES - 1:
                                await asyncio.sleep(RETRY_DELAY)
                                continue
                            else:
                                for j in range(batch_size):
                                    feature_index = i + j
                                    if feature_index < len(biomass_geojson["features"]):
                                        biomass_geojson["features"][feature_index]["properties"]["MinNfromFOM"] = 0
                                        biomass_geojson["features"][feature_index]["properties"]["ReqN"] = 0
                                break

                        elif isinstance(data, list):
                            for j, entry in enumerate(data):
                                feature_index = i + j
                                min_n = 0

                                try:
                                    min_n = entry["results"]["surface"][0].get("MinNfromFOM", 0) or 0
                                except (KeyError, IndexError, TypeError):
                                    print(f"Missing MinNfromFOM for feature {feature_index}")
                                if i < len(biomass_geojson["features"]):
                                    biomass_geojson["features"][feature_index]["properties"]["MinNfromFOM"] = min_n
                                    biomass_geojson["features"][feature_index]["properties"]["ReqN"] = (n_targets[feature_index] - min_n) / multiplier
                            break

                        elif isinstance(data, dict):
                            min_n = 0

                            try:
                                if "surface" in data and data["surface"]:
                                    min_n = data["surface"][0].get("MinNfromFOM", 0) or 0
                            except (KeyError, IndexError, TypeError):
                                print(f"Missing MinNfromFOM for feature {i}")
                            if i < len(biomass_geojson["features"]):
                                biomass_geojson["features"][i]["properties"]["MinNfromFOM"] = min_n
                                biomass_geojson["features"][i]["properties"]["ReqN"] = (n_targets[i] - min_n) / multiplier

                        else:
                            print(f"Unexpected response structure: {data}")
                            if attempt < MAX_RETRIES - 1:
                                await asyncio.sleep(RETRY_DELAY)
                                continue
                            else:
                                for j in range(batch_size):
                                    feature_index = i + j
                                    if feature_index < len(biomass_geojson["features"]):
                                        biomass_geojson["features"][feature_index]["properties"]["MinNfromFOM"] = 0
                                        biomass_geojson["features"][feature_index]["properties"]["ReqN"] = 0
                            break

                    else:
                        print(f"Error: {response.status_code}, {response.text}")

    return { "geojson_data" : biomass_geojson }

class GeoJSONGeometry(BaseModel):
    type: str
    coordinates: Any

class GeneratePointsPayload(BaseModel):
    geometry: GeoJSONGeometry
    count: int = 100

@app.post("/generate-points")
def generate_random_points(payload: GeneratePointsPayload):
    geometry = payload.geometry.model_dump()
    count = payload.count

    points = []
    geom = shape(geometry)
    minx, miny, maxx, maxy = geom.bounds

    while len(points) < count:
        random_pt = Point(random.uniform(minx, maxx), random.uniform(miny, maxy))

        if geom.contains(random_pt):
            points.append({
                "camera_id": len(points) + 1,
                "lon": random_pt.x,
                "lat": random_pt.y,
                "species": {
                    "winter_cereals": round(random.uniform(100, 150), 6),
                    "crimson_clover": round(random.uniform(40, 60), 6)
                },
                "biomass_percentile_per_species": {
                    "winter_cereals": round(random.random(), 4),
                    "crimson_clover": round(random.random(), 4)
                }
            })

    return {"points": points}

class GeneratePointsNewPayload(BaseModel):
    boundary_id: str
    model_name: str
    model_version: str
    geometry: GeoJSONGeometry
    count: int = 100

@app.post("/generate-points-new")
def generate_random_points_new(payload: GeneratePointsNewPayload):
    try:
        geometry = payload.geometry.model_dump()
        boundary_id = payload.boundary_id
        model_name = payload.model_name
        model_version = payload.model_version
        count = payload.count

        points = []
        geom = shape(geometry)
        minx, miny, maxx, maxy = geom.bounds

        while len(points) < count:
            random_pt = Point(random.uniform(minx, maxx), random.uniform(miny, maxy))

            if geom.contains(random_pt):
                index = len(points) + 1
                img_name = f"IMG_{boundary_id[:5]}_{index:03d}_{uuid.uuid4().hex[:8]}.jpg"
                points.append({
                    "job_name": f"Simulated_{boundary_id}",
                    "boundary_id": boundary_id,
                    "model_name": model_name,
                    "model_version": model_version,
                    "camera": "Sony",
                    "image_type": "RGB",
                    "image_name": img_name,
                    "inference_score": round(random.uniform(0.85, 0.99), 4),
                    "gps_location": [random_pt.x, random_pt.y],
                    "output": {
                        "winter_cereals_biomass": round(random.uniform(100, 150), 6),
                        "winter_pea_biomass": round(random.uniform(40, 60), 6),
                    },
                    "created_at": datetime.utcnow().isoformat()
                })

        return {"points": points}

    except Exception as e:
        print(f"Geometry processing error: {str(e)}")

GROWTH_STAGE_ORDER = [
    "Unknown growth stage",
    "Not jointed",
    "Jointed",
    "Booting",
    "Heading",
    "Vegetative",
    "Flowering"
]

def get_stage_priority(stage):
    try:
        return GROWTH_STAGE_ORDER.index(stage)
    except ValueError:
        return -1

def resolve_group_growth_stages(species_list, growth_stage):
    """
    returns group_list mapped from species_list and their respective growth stages
    if multiple species from one group exist, only one group is returned with the most advanced growth stage
    """
    group_to_best_stage = {}

    for s, current_stage in zip(species_list, growth_stage, strict=True):
        group_name = next((g for g, members in species_group_map.items() if s in members), s)
        
        if group_name not in group_to_best_stage:
            group_to_best_stage[group_name] = current_stage
        else:
            # If multiple species from the same group, use the most advanced growth stage
            existing_stage = group_to_best_stage[group_name]
            if get_stage_priority(current_stage) > get_stage_priority(existing_stage):
                group_to_best_stage[group_name] = current_stage

    species_list_new = list(group_to_best_stage.keys())
    growth_stage_list_new = list(group_to_best_stage.values())

    return species_list_new, growth_stage_list_new

class PointModel(BaseModel):
    lon: float
    lat: float
    species: Dict[str, float]

class GenerateGridRequest(BaseModel):
    points: List[PointModel]
    field_geometry: Dict[str, Any]
    feature_collection: FeatureCollection = FeatureCollection(type="FeatureCollection", features=[])
    species: Union[str, List[str]] = ""
    growth_stage: Union[str, List[str]] = ""
    start: str = ""
    end: str = ""
    property_key: str = ""
    multiplier: float = 1.0
    has_fixed_rate: bool = False
    target_n: float = 0.0
    no_prescription: bool = False # Used for RCPP-Report-Only fields where we want nitrogen credit calculation but not prescription generation
    input_mode: str = ""

@app.post("/prescription")
async def prescription(payload: GenerateGridRequest, format: str = Query("geojson", pattern="^(geojson|shapefile)$")):
    points = [p.dict() for p in payload.points]
    field_geometry = payload.field_geometry
    input_features = payload.feature_collection.features
    species_list = payload.species
    growth_stage = payload.growth_stage
    start = payload.start
    end = payload.end
    property_key = payload.property_key
    multiplier = payload.multiplier
    has_fixed_rate = payload.has_fixed_rate
    target_n = payload.target_n
    no_prescription = payload.no_prescription
    input_mode = payload.input_mode

    species_list_new, growth_stage_list_new = resolve_group_growth_stages(species_list, growth_stage)

    combined_geom = shape(field_geometry)
    centroid = combined_geom.centroid
    lon, lat = centroid.x, centroid.y

    utm_zone = int((lon + 180) / 6) + 1
    hemisphere = 'north' if lat >= 0 else 'south'

    utm_crs = f"+proj=utm +zone={utm_zone} +{hemisphere} +datum=WGS84"
    # print(f"Using UTM Zone {utm_zone}{hemisphere[0].upper()}")

    # EPSG:4326/WGS84 - standard lat/lon coordinates
    # UTM - meter based coordinates for calculating area
    to_projected = Transformer.from_crs("EPSG:4326", utm_crs, always_xy=True)
    from_projected = Transformer.from_crs(utm_crs, "EPSG:4326", always_xy=True)

    # Project into meters
    combined_geom_m = transform(to_projected.transform, combined_geom)

    if not has_fixed_rate:
        all_features_m = [] # Stores {geometry, properties} for each input feature in meters
        # Parse GeoJSON features into shapely geometry objects and project into meters
        for feature in input_features:
            geom_data = feature.geometry
            geom = shape(geom_data)
            geom_m = transform(to_projected.transform, geom)

            # Only consider area that intersects with the field_geometry
            clipped_geom_m = geom_m.intersection(combined_geom_m)
            if clipped_geom_m.is_empty:
                continue

            all_features_m.append({
                'geometry': clipped_geom_m,
                'properties': feature.properties
            })

        # Redefine field geomtery to union of clipped input features
        # If input_features are a subset or field_geometry, combined_geom_m shrinks to their union;
        # If input_features are a superset, it's already clipped to field boundary via all_features_m.
        valid_input_area_m = unary_union([f['geometry'] for f in all_features_m]) if all_features_m else None
        if valid_input_area_m is not None:
            combined_geom_m = valid_input_area_m

    side = 63.615 # 63.615^2 m^2 = 1 acre
    minx, miny, maxx, maxy = combined_geom_m.bounds # min_lon, min_lat, max_lon, max_lat

    # Calculate number of grid cells required
    row_count = math.ceil((maxy - miny) / side)
    col_count = math.ceil((maxx - minx) / side)

    # Initialize matrices to store aggregate biomass totals and sample counts per cell
    biomass_sum = np.zeros((row_count, col_count))
    biomass_count = np.zeros((row_count, col_count), dtype=int)

    # Dictionaries to track biomass data per cover crop species
    species_biomass_sum = {}
    species_biomass_count = {}
    species_all = set()

    # Calculate biomass sums and counts for each grid cell
    lons = np.array([p['lon'] for p in points])
    lats = np.array([p['lat'] for p in points])

    # Batch transform all coordinates
    xs, ys = to_projected.transform(lons, lats)

    # Vectorized grid index computation
    col_indices = np.floor((xs - minx) / side).astype(int)
    row_indices = np.floor((ys - miny) / side).astype(int)

    # Handle edge cases where point falls exactly on the max boundary
    col_indices = np.clip(col_indices, 0, col_count - 1)
    row_indices = np.clip(row_indices, 0, row_count - 1)

    # Check if the points fall within the boundary and create a boolean mask for it
    prepared_geom = combined_geom_m.buffer(0.01)
    inside_mask = shapely.contains(prepared_geom, shapely.points(xs, ys))

    all_species = set(k for p in points for k in p['species'].keys())

    # Initiliaze species-wise array
    for species in all_species:
        species_biomass_sum[species] = np.zeros((row_count, col_count))
        species_biomass_count[species] = np.zeros((row_count, col_count), dtype=int)

    # Calculate biomass sums and counts for each grid cell
    for i, point in enumerate(points):

        if not inside_mask[i]:
            continue

        row_index, col_index = row_indices[i], col_indices[i]
        added = False
        for species, biomass_value in point['species'].items():
            if not np.isfinite(biomass_value) or biomass_value < 0:
                continue

            # conversion: g/0.5m^2 (camera output) to kg/ha (/surface API input)
            biomass_value *= 20

            biomass_sum[row_index, col_index] += biomass_value
            species_biomass_sum[species][row_index, col_index] += biomass_value
            species_biomass_count[species][row_index, col_index] += 1

            if not added:
                biomass_count[row_index, col_index] += 1
                added = True
            species_all.add(species)

    # average biomass grid for all species combined
    with np.errstate(invalid='ignore', divide='ignore'):
        biomass_average = biomass_sum / biomass_count
    biomass_average[np.isnan(biomass_average)] = 0

    # average biomass grids for individual species
    species_biomass_average = {}
    for species in species_all:
        with np.errstate(invalid='ignore', divide='ignore'):
            avg = species_biomass_sum[species] / biomass_count
        avg[np.isnan(avg)] = 0
        species_biomass_average[species] = avg.tolist()

    # Calculate field-level stats
    total_field_biomass = np.sum(biomass_sum)
    total_sample_count = np.sum(biomass_count)
    avg_field_biomass = total_field_biomass / total_sample_count if total_sample_count > 0 else 0

    field_weighted_n, field_weighted_carb, field_weighted_cell, field_weighted_lign = 0, 0, 0, 0

    if total_field_biomass > 0:
        for species in species_all:
            species_total_biomass = np.sum(species_biomass_sum[species])
            field_species_weight = species_total_biomass / total_field_biomass

            try:
                species_index = species_list_new.index(species)
                current_growth_stage = growth_stage_list_new[species_index]
            except (ValueError, IndexError):
                current_growth_stage = "Unknown growth stage"

            s_props = group_lut.get(species, {}).get(current_growth_stage, {}) or group_lut.get(species, {}).get("Unknown growth stage", {})

            field_weighted_n += field_species_weight * s_props.get("mean_n",  2.726053687272728)
            field_weighted_carb += field_species_weight * s_props.get("mean_carb", 45.61333333333334)
            field_weighted_cell += field_species_weight * s_props.get("mean_holocellulose", 41.945099400000004)
            field_weighted_lign += field_species_weight * s_props.get("mean_lignin", 5.989393939393938)

    field_summary = {
        "avg_biomass": avg_field_biomass,
        "avg_n": field_weighted_n,
        "avg_carb": field_weighted_carb,
        "avg_cell": field_weighted_cell,
        "avg_lign": field_weighted_lign
    }

    complete_blocks = []
    incomplete_blocks = []
    zero_biomass_blocks = []

    total_area_acres = combined_geom_m.area / 4046.86
    max_blocks = math.floor(total_area_acres * 0.10) # number of blocks covering 10% of total area for all categories except capped treatment

    # Fix potential invalidity from reprojection or unary_union
    combined_geom_m = make_valid(combined_geom_m)

    # Calculate weighted average target nitrogen for each grid cell
    for c_idx, x in enumerate(np.arange(minx, maxx, side)):
        for r_idx, y in enumerate(np.arange(miny, maxy, side)):
            grid_cell = box(x, y, x + side, y + side)
            cell_intersection = grid_cell.intersection(combined_geom_m)

            if cell_intersection.is_empty:
                continue

            weighted_average = 0

            if has_fixed_rate:
                # Skip spatial intersection logic and use the fixed value provided
                weighted_average = target_n
            else:
            # Check intersection with each feature and calculate area-weighted average
                feature_intersections = []
                total_intersect_area = 0
                weighted_property_sum = 0

                for feat_idx, feat in enumerate(all_features_m):
                    feat_geom = feat['geometry']
                    poly_intersection = cell_intersection.intersection(feat_geom)

                    if not poly_intersection.is_empty:
                        poly_intersection_area = poly_intersection.area
                        property_value = feat['properties'].get(property_key, 0)

                        feature_intersections.append({
                            "feature_id": feat_idx,
                            "intersection_area_m2": poly_intersection_area,
                            "intersection_area_acres": poly_intersection_area / 4046.86,
                            "percentage_of_grid": (poly_intersection_area / cell_intersection.area) * 100,
                            "property_value": property_value,
                        })

                        total_intersect_area += poly_intersection_area
                        weighted_property_sum += property_value * poly_intersection_area

                weighted_average = weighted_property_sum / total_intersect_area if total_intersect_area > 0 else 0

            block = {
                "row": r_idx,
                "col": c_idx,
                "grid_cell": grid_cell,
                "intersection": cell_intersection,
                "area_acres": cell_intersection.area / 4046.86,
                "biomass_count": biomass_count[r_idx, c_idx].item(),
                "biomass_average": biomass_average[r_idx, c_idx],
                "species_biomass_average": {species: species_biomass_average[species][r_idx][c_idx] for species in species_all},
                "target_n_weighted_avg": weighted_average
            }

            if combined_geom_m.covers(grid_cell):
                if biomass_average[r_idx, c_idx] == 0:
                    zero_biomass_blocks.append(block)
                else:
                    complete_blocks.append(block)
            else:
                incomplete_blocks.append(block)

    random.shuffle(complete_blocks)

    zero_count = len(zero_biomass_blocks)

    if zero_count <= max_blocks:
        # control gets all zero biomass blocks + required complete blocks to reach 10%
        needed = max_blocks - zero_count
        cat1 = zero_biomass_blocks + complete_blocks[:needed]
        remaining = complete_blocks[needed:]
        
        cat2 = remaining[:max_blocks] # full
        cat3 = remaining[max_blocks:2 * max_blocks] # average
        cat4 = remaining[2 * max_blocks:] + incomplete_blocks # cap

    else:
        # cat1 exceeds 10%, distribute remaining complete blocks in 1:1:7 ratio
        cat1 = zero_biomass_blocks
        n = len(complete_blocks)
        split = math.ceil(n / 9)
        cat2 = complete_blocks[:split] # full
        cat3 = complete_blocks[split:2 * split] # average
        cat4 = complete_blocks[2 * split:] + incomplete_blocks # cap

    prescription_features = []

    def build_geojson_features(blocks, category):
        for b in blocks:
            # Convert meter-based intersection back to standard lat/lon coordinates
            latlon_geom = transform(from_projected.transform, b["intersection"])

            properties = {
                "row": b["row"],
                "col": b["col"],
                "area_acres": b["area_acres"],
                "biomass_count": b["biomass_count"],
                "biomass_average": b["biomass_average"],
                "species_biomass_average": b["species_biomass_average"],
            }

            # Only add "category" and "target_n_weighted_avg" if no_prescription is False
            if not no_prescription:
                properties["category"] = category
                properties["target_n_weighted_avg"] = b["target_n_weighted_avg"]

            prescription_features.append({
                "type": "Feature",
                "geometry": latlon_geom.__geo_interface__,
                "properties": properties
            })

    build_geojson_features(cat1, 1)
    build_geojson_features(cat2, 2)
    build_geojson_features(cat3, 3)
    build_geojson_features(cat4, 4)

    prescription_features.sort(key=lambda x: (x["properties"]["row"], x["properties"]["col"]))

    if len(prescription_features) == 0:
        return JSONResponse(
        status_code=400,
        content={"message": "No prescription features found."}
    )

    geojson_data = {
        "type": "FeatureCollection",
        "features": prescription_features
    }

    final_geojson, _ , average_n_credit = await calculate_nitrogen_pm3d(geojson_data, species_list_new, growth_stage_list_new, start, end)

    for feature in final_geojson["features"]:
        n_credit = feature["properties"].get("MinNfromFOM", 0)

        if not no_prescription:
            category = feature["properties"].get("category", 0)
            if input_mode == 'nitrogen':
                target_n = feature["properties"].get("target_n_weighted_avg", 0) * 1.12085 # convert lb/ac to kg/ha
            else:
                target_n = feature["properties"].get("target_n_weighted_avg", 0) * multiplier # conversion to kg/ha already included in multiplier

            if category == 1: # control
                req_n = target_n
            elif category == 2: # full
                req_n = target_n - n_credit
            elif category == 3: # average
                req_n = target_n - average_n_credit
            elif category == 4: # cap
                req_n = target_n - min(n_credit, (25 * 1.12085))

            feature["properties"]["ReqN"] = max(req_n, 0) * 0.8922 # convert kg/ha to lb/ac
            feature["properties"]["ReqN_product"] = max(req_n, 0) / multiplier

        feature["properties"]["MinNfromFOM"] = round(n_credit * 0.8922) # convert kg/ha to lb/ac
        feature["properties"]["biomass_average"] *= 0.8922 # convert kg/ha to lb/ac
        feature["properties"]["species_biomass_average"] = {
            species: value * 0.8922 # convert kg/ha to lb/ac
            for species, value in feature["properties"]["species_biomass_average"].items()
        }

    if format == "shapefile":
        gdf = gpd.GeoDataFrame.from_features(final_geojson["features"], crs="EPSG:4326")

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            shapefile_name = "prescription"
            shapefile_path = tmpdir_path / f"{shapefile_name}.shp"
            gdf.to_file(shapefile_path, driver='ESRI Shapefile')

            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for file in tmpdir_path.glob(f"{shapefile_name}.*"):
                    zipf.write(file, file.name)

            zip_buffer.seek(0)
            zip_bytes = zip_buffer.read()

        # Return bytes directly
        return Response(
            content=zip_bytes,
            media_type="application/zip",
            headers={
                "Content-Disposition": "attachment; filename=prescription_shapefile.zip"
            }
        )

    return {"message": "Prescription generated", "geojson_data": final_geojson, "field_summary": field_summary}

@app.post("/export-shapefile")
async def export_shapefile(payload: Dict[str, Any]):
    geojson = payload.get("geojson")

    gdf = gpd.GeoDataFrame.from_features(geojson["features"], crs="EPSG:4326")

    gdf.geometry = gdf.geometry.make_valid()
    gdf = gdf.explode(index_parts=False)
    gdf = gdf[gdf.geometry.type == 'Polygon']

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        shapefile_name = "prescription"
        shapefile_path = tmpdir_path / f"{shapefile_name}.shp"
        gdf.to_file(shapefile_path, driver='ESRI Shapefile')

        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for file in tmpdir_path.glob(f"{shapefile_name}.*"):
                zipf.write(file, file.name)

        zip_buffer.seek(0)
        zip_bytes = zip_buffer.read()

        # Return bytes directly
        return Response(
            content=zip_bytes,
            media_type="application/zip",
            headers={"Content-Disposition": f"attachment; filename={shapefile_name}.zip"}
        )

def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())

def resolve_column(gdf, canonical: str):
    """
    Find the column matching a canonical Deere field name, tolerating the
    DBF 10-char truncation applied when the export is a shapefile.
    'Swth Wdth(ft)' -> 'Swth_Wdth_', 'Distance(ft)' -> 'Distance_f'.
    """
    target = _norm(canonical)
    best, best_len = None, 0
    for col in gdf.columns:
        n = _norm(col)
        if not n:
            continue
        # Either side may be the truncated one.
        if target.startswith(n) or n.startswith(target):
            if len(n) > best_len:
                best, best_len = col, len(n)
    return best

def build_swaths(geojson):
    """
    Turn as-applied points into swath rectangles.
    Returns (swaths in a UTM CRS, None) on success or (None, JSONResponse) on bad input.
    """
    FT = 0.3048

    if not geojson or not geojson.get("features"):
        return None, JSONResponse(status_code=400, content={"message": "No features provided."})

    gdf = gpd.GeoDataFrame.from_features(geojson["features"], crs="EPSG:4326")

    wanted = {
        "track": "Track(deg)",
        "distance": "Distance(ft)",
        "swath": "Swth Wdth(ft)",
    }
    resolved = {k: resolve_column(gdf, v) for k, v in wanted.items()}

    missing = [wanted[k] for k, v in resolved.items() if v is None]
    if missing:
        return None, JSONResponse(
            status_code=400,
            content={
                "message": f"Missing required properties: {missing}",
                "available": list(gdf.columns),
            },
        )

    cols = list(resolved.values())
    gdf = gdf[gdf.geometry.geom_type == "Point"].dropna(subset=cols + ["geometry"])
    if gdf.empty:
        return None, JSONResponse(status_code=400, content={"message": "No usable point records."})

    # Project to UTM so we can work in meters.
    c_lon = gdf.geometry.x.mean()
    c_lat = gdf.geometry.y.mean()
    zone = int((c_lon + 180) / 6) + 1
    utm = f"+proj=utm +zone={zone} +{'north' if c_lat >= 0 else 'south'} +datum=WGS84 +units=m"
    g = gdf.to_crs(utm).reset_index(drop=True)

    theta = np.radians(g[resolved["track"]].to_numpy(float))
    half_l = g[resolved["distance"]].to_numpy(float) * FT / 2
    half_w = g[resolved["swath"]].to_numpy(float) * FT / 2

    ax, ay = np.sin(theta) * half_l, np.cos(theta) * half_l   # along track
    px, py = np.cos(theta) * half_w, -np.sin(theta) * half_w  # across track

    x, y = g.geometry.x.to_numpy(), g.geometry.y.to_numpy()

    # Add original point and id as properties to the swath polygon
    reprojected_g = g.to_crs("EPSG:4326").geometry
    g["center_lon"], g["center_lat"] = reprojected_g.x.to_numpy(), reprojected_g.y.to_numpy()
    g["swath_id"] = np.arange(len(g))

    corners = np.stack([
        np.column_stack([x - ax - px, y - ay - py]),
        np.column_stack([x + ax - px, y + ay - py]),
        np.column_stack([x + ax + px, y + ay + py]),
        np.column_stack([x - ax + px, y - ay + py]),
    ], axis=1)

    g["geometry"] = shapely.polygons(shapely.linearrings(corners))
    g["area_m2"] = g.geometry.area

    # Records logged while stopped have no along-track extent.
    g = g[g["area_m2"] > 0]
    if g.empty:
        return None, JSONResponse(status_code=400, content={"message": "All records were degenerate."})

    return g, None

def swath_summary(g):
    return {
        "polygon_count": len(g),
        "median_area_m2": float(g["area_m2"].median()),
        "total_area_acres": float(g["area_m2"].sum() / 4046.8564224),
    }

@app.post("/points-to-polygon")
async def points_to_polygon(payload: Dict[str, Any]):
    g, err = build_swaths(payload.get("geojson"))
    if err is not None:
        return err

    return {
        "message": "Swath polygons generated",
        "geojson_data": json.loads(g.to_crs("EPSG:4326").to_json()),
        "summary": swath_summary(g),
    }

@app.post("/swaths-to-cells")
async def swaths_to_cells(payload: Dict[str, Any]):
    """""
    Builds the swaths from the as-applied points (same as /points-to-polygon) and
    aggregates them into prescription cells in one call, so the swath GeoJSON never
    has to be round-tripped through the client.
    """""
    presc_fc = payload.get("prescription")

    centered_swaths_only = payload.get("centered_swaths_only", False)
    threshold = payload.get("threshold", 10)
    remove_intersection = payload.get("remove_intersection", True)
    include_swaths = payload.get("include_swaths", False)
    TARGET_COL = payload.get("target_col", "ReqN_product")  # prescription column a swath's rate is compared against

    if not presc_fc or not presc_fc.get("features"):
        return JSONResponse(status_code=400, content={"message": "No prescription provided."})

    g, err = build_swaths(payload.get("geojson"))
    if err is not None:
        return err

    presc = gpd.GeoDataFrame.from_features(presc_fc["features"], crs="EPSG:4326")

    # Project both layers to the same UTM zone before any area maths.
    c = presc.geometry.representative_point()
    zone = int((float(c.x.mean()) + 180) / 6) + 1
    hemi = "north" if float(c.y.mean()) >= 0 else "south"
    utm = f"+proj=utm +zone={zone} +{hemi} +datum=WGS84 +units=m"

    g = g.to_crs(utm)
    presc = presc.to_crs(utm)
    presc_cells = presc[["row", "col", "geometry"]].copy()

    
    '''
    Build two structures: swaths_per_cell and centers_per_cell

    swaths_per_cell - a swath intersects with which prescription cell(s)
    centers_per_cell - the center of a swath lies in which prescription cell

    Both the structures will be of the following format:
    { prescription_cell_id: [swath_1, swath_2, ... , swath_n] }
    where   prescription_cell_id = (row, col) of the prescription cell
            swath_n = {"swath_id": sid, "area_m2": <area of intersection of the swath with the cell>, "geom": <geometry of the intersection>}

    swaths_per_cell will have every (swath, cell) fragment it intersects with.
    centers_per_cell will only the fragment in the cell the swath's centre falls in, so each swath contributes to exactly one cell.
    '''

    # Rebuild the centre points from the stored lon/lat.
    centers = gpd.GeoDataFrame(
        {"swath_id": g["swath_id"].to_numpy()},
        geometry=gpd.points_from_xy(g["center_lon"], g["center_lat"], crs="EPSG:4326"),
    ).to_crs(g.crs)

    # Find the cell each swath's centre lands in (one swath -> one cell).
    centers_in_cells = gpd.sjoin(centers, presc_cells, predicate="within", how="inner")
    center_cell = {
        int(t.swath_id): (int(t.row), int(t.col))
        for t in centers_in_cells.itertuples(index=False)
    }

    # overlay splits every swath at cell boundaries -> one row per (swath, cell) pair;
    # keep_geom_type drops any line/point slivers.
    fragments = gpd.overlay(
        g[["swath_id", "geometry"]], presc_cells, how="intersection", keep_geom_type=True
    )
    fragments["frag_area_m2"] = fragments.geometry.area

    swaths_per_cell = defaultdict(list)
    centers_per_cell = defaultdict(list)
    for t in fragments.itertuples(index=False):
        sid = int(t.swath_id)
        key = (int(t.row), int(t.col))
        member = {"swath_id": sid, "area_m2": float(t.frag_area_m2), "geom": t.geometry}
        swaths_per_cell[key].append(member)
        if center_cell.get(sid) == key:
            centers_per_cell[key].append(member)

    print(f"{len(centers_in_cells)}/{len(centers)} centres inside a cell, {len(centers_per_cell)} cells populated")
    print(f"{len(fragments)} (swath, cell) fragments across {len(swaths_per_cell)} cells")

    RATE_COL = resolve_column(g, "Rt Apd Liq")
    if RATE_COL is None:
        return JSONResponse(
            status_code=400,
            content={"message": "No applied-rate column found.", "available": list(g.columns)},
        )

    '''
    # Per-cell aggregation: for every prescription cell, take the swaths that
    # belong to it, area-weight their applied rate, and combine their geometry.
    '''

    # Per-swath / per-cell lookups.
    presc_cell_geom = dict(zip(zip(presc_cells["row"], presc_cells["col"], strict=True), presc_cells.geometry, strict=True))
    presc_cell_target = dict(zip(zip(presc["row"], presc["col"], strict=True), presc[TARGET_COL].astype(float), strict=True))
    swath_rate = dict(zip(g["swath_id"], g[RATE_COL].astype(float), strict=True))

    # Iterate the structure chosen by the flag: centres or intersections.
    structure = centers_per_cell if centered_swaths_only else swaths_per_cell

    rows = []
    for key, members in structure.items():
        if key not in presc_cell_geom:
            continue

        ids = [m["swath_id"] for m in members]
        weights = np.array([m["area_m2"] for m in members], float)
        geoms = [m["geom"] for m in members]

        rates = np.array([swath_rate[i] for i in ids], float)

        # Remove overlapped area - update geometry and re-weight the weights
        if remove_intersection and len(geoms) > 1:
            # The region covered by >=2 swaths equals the union of the pairwise swath intersections.
            # Find the overlapping pairs with a spatial index, union those areas, then subtract from every swath.
            tree = shapely.STRtree(geoms)
            ia, ib = tree.query(geoms, predicate="intersects")
            overlap_parts = [geoms[a].intersection(geoms[b]) for a, b in zip(ia, ib, strict=True) if a < b]
            if overlap_parts:
                overlap = shapely.union_all(overlap_parts)
                geoms = [gm.difference(overlap) for gm in geoms]
            # Reweight by each swath's singly-covered area.
            weights = np.array([gm.area for gm in geoms], float)

        # Drop outlier swaths: rate more than `threshold` above or below the cell's prescription target.
        target = presc_cell_target.get(key)
        if target is not None and threshold is not None:
            keep = np.abs(rates - target) <= threshold
            if not keep.any():
                continue    # every swath was an outlier -> no cell
            ids = [i for i, k in zip(ids, keep, strict=True) if k]
            geoms = [gm for gm, k in zip(geoms, keep, strict=True) if k]
            weights = weights[keep]
            rates = rates[keep]

        # Combine the surviving fragments (clipped to the cell).
        clipped = shapely.union_all(geoms)

        wavg = np.average(rates, weights=weights) if weights.sum() > 0 else np.nan

        rows.append({
            "row": key[0],
            "col": key[1],
            "n_swaths": len(ids),
            "weighted_rate": wavg,
            "combined_area_m2": clipped.area,
            "geometry": clipped,
        })

    if not rows:
        return JSONResponse(status_code=400, content={"message": "No cells summarised."})

    cell_summary = gpd.GeoDataFrame(rows, geometry="geometry", crs=g.crs)
    print(f"{len(cell_summary)} cells summarised (centered_swaths_only={centered_swaths_only})")

    geojson_data = json.loads(cell_summary.to_crs("EPSG:4326").to_json())
    response = {
        "message": "Cell summary generated",
        "geojson_data": geojson_data,
        "swath_summary": swath_summary(g),
    }
    if include_swaths:
        response["swaths_geojson"] = json.loads(g.to_crs("EPSG:4326").to_json())
    return response