import json
import numpy as np
from typing import Union, List, Dict
from typing_extensions import Self
from fastapi import FastAPI, Depends, Query
from fastapi.exceptions import HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field, validator, ValidationError, model_validator
from typing import List, Optional, Literal
from fastapi.middleware.cors import CORSMiddleware
from .constants import species, plant_groups
from .utilities.helpers import create_biomass_geojson, get_center
from datetime import datetime
import httpx
import asyncio

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

with open('app/assets/summarized_lookup_table.json') as fp:
    plant_growth_lut = json.loads(fp.read())
    
species_lower = {}
for key, val in species.items():
    species_lower[key.lower()] = [v.lower() for v in val] 


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


@app.get("/plantgroups")
def read_plantgroups():
    return plant_groups


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


class BiomassPayload(BaseModel):
    data_array: List[List[float]] = [[1,2], [3,4]]
    nitrogen_percentage: float = 0.0
    carbohydrates_percentage: float = 0.0
    holo_cellulose_percentage: float = 0.0
    lignin_percentage: float = 0.0
    bbox: List[float] = [0,0,0,0]
    species: Union[str, List[str]] = ""
    growth_stage: Union[str, List[str]] = ""
    start: str = ""
    end: str = ""
    target_n: float = 0.0
    mode: str = "satellite",
    species_biomass_average: Dict[str, List[List[float]]] = {"Oats" : [[1,2], [3,4]]}
    

@app.post("/nitrogen")
async def read_nitrogen(biomass_payload: BiomassPayload):

    data_array = np.array(biomass_payload.data_array)
    bbox = biomass_payload.bbox
    species = biomass_payload.species
    growth_stage = biomass_payload.growth_stage
    start = biomass_payload.start
    end = biomass_payload.end
    target_n = biomass_payload.target_n
    mode = biomass_payload.mode
    species_biomass_average = biomass_payload.species_biomass_average

    biomass_geojson = create_biomass_geojson(data_array, bbox, mode, species_biomass_average)
    average_weighted_n = 0

    if mode == 'satellite' or mode == 'sampled':

        if not plant_growth_lut.get(species).get(growth_stage):
            species_lookup_values = plant_growth_lut.get(species).get("Unknown growth stage")
        else:
            species_lookup_values = plant_growth_lut.get(species).get(growth_stage)

        lats, lons, biomasses = [], [], []

        for feature in biomass_geojson["features"]:
            lon, lat = get_center(feature)
            biomass = feature["properties"]["value"]

            lats.append(lat)
            lons.append(lon)
            biomasses.append(biomass)

        batch_size = 30
        MAX_RETRIES = 3
        RETRY_DELAY = 2

        async with httpx.AsyncClient(timeout=30.0) as client:
            for i in range(0, len(lats), batch_size):
                query_params = {
                    "lat": lats[i:i+batch_size],
                    "lon": lons[i:i+batch_size],
                    "biomass": biomasses[i:i+batch_size],
                    "start": start,
                    "end": end,
                    "n": species_lookup_values["mean_n"],
                    "carb": species_lookup_values["mean_carb"],
                    "cell": species_lookup_values["mean_cellulose"],
                    "lign": species_lookup_values["mean_lignin"],
                    "summary": True,
                }

                for attempt in range(MAX_RETRIES):
                    try:
                        response = await client.get("https://developapi.covercrop-ncalc.org/surface/", params=query_params)
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
                                continue
                            if attempt < MAX_RETRIES - 1:
                                await asyncio.sleep(RETRY_DELAY)
                                continue
                            else:
                                for j in range(batch_size):
                                    feature_index = i + j
                                    if feature_index < len(biomass_geojson["features"]):
                                        biomass_geojson["features"][feature_index]["properties"]["MinNfromFOM"] = 0
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
                                    biomass_geojson["features"][feature_index]["properties"]["ReqN"] = target_n - min_n
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
                                biomass_geojson["features"][i]["properties"]["ReqN"] = target_n - min_n

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

        print(datetime.now().strftime("%H:%M:%S"))

    elif mode == 'pm3d':

        species_lookup_values = {}
        for index, s in enumerate(species):
            if not plant_growth_lut.get(s).get(growth_stage[index]):
                species_lookup_values[s] = plant_growth_lut.get(s).get("Unknown growth stage")
            else:
                species_lookup_values[s] = plant_growth_lut.get(s).get(growth_stage[index])

        lats, lons, biomasses = [], [], []
        total_weighted_n, number_weighted_n = 0, 0

        for feature in biomass_geojson["features"]:
            lon, lat = get_center(feature)
            biomass = feature["properties"]["value"]

            species_data = feature["properties"].get("species", {})

            if species_data:
                total_biomass = sum(species_data.values())

                weighted_n = 0
                weighted_carb = 0
                weighted_cell = 0
                weighted_lign = 0

                for species_name, species_biomass in species_data.items():
                    weight = species_biomass / total_biomass
                    print(species_name, weight)
                    species_props = species_lookup_values.get(species_name, {})

                    weighted_n += weight * species_props.get("mean_n", 0)
                    weighted_carb += weight * species_props.get("mean_carb", 0)
                    weighted_cell += weight * species_props.get("mean_cellulose", 0)
                    weighted_lign += weight * species_props.get("mean_lignin", 0)

                if weighted_n > 0:
                    total_weighted_n += weighted_n
                    number_weighted_n += 1
            else:
                weighted_n = 0
                weighted_carb = 0
                weighted_cell = 0
                weighted_lign = 0

            MAX_RETRIES = 3
            RETRY_DELAY = 2

            async with httpx.AsyncClient(timeout=30.0) as client:
                query_params = {
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
                }
                print(query_params)

                for attempt in range(MAX_RETRIES):
                    try:
                        response = await client.get("https://developapi.covercrop-ncalc.org/surface/", params=query_params)
                    except httpx.RequestError as e:
                        print(f"Request error {type(e).__name__}: {repr(e)} (attempt {attempt + 1})")
                        if attempt < MAX_RETRIES - 1:
                            await asyncio.sleep(RETRY_DELAY)
                            continue
                        else:
                            # Set 0 for this feature
                            feature["properties"]["properties"]["MinNfromFOM"] = 0
                            feature["properties"]["properties"]["ReqN"] = 0
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
                                continue
                            if attempt < MAX_RETRIES - 1:
                                await asyncio.sleep(RETRY_DELAY)
                                continue
                            else:
                                feature["properties"]["MinNfromFOM"] = 0
                                feature["properties"]["ReqN"] = 0
                                break

                        elif isinstance(data, dict):
                            min_n = 0

                            try:
                                if "surface" in data and data["surface"]:
                                    min_n = data["surface"][0].get("MinNfromFOM", 0) or 0
                            except (KeyError, IndexError, TypeError):
                                print("Missing MinNfromFOM for feature")
                            feature["properties"]["MinNfromFOM"] = min_n
                            feature["properties"]["ReqN"] = target_n - min_n
                            break

                        else:
                            print(f"Unexpected response structure: {data}")
                            if attempt < MAX_RETRIES - 1:
                                await asyncio.sleep(RETRY_DELAY)
                                continue
                            else:
                                feature["properties"]["MinNfromFOM"] = 0
                                feature["properties"]["ReqN"] = 0
                                break

                    else:
                        print(f"Error: {response.status_code}, {response.text}")
                        feature["properties"]["MinNfromFOM"] = 0
                        feature["properties"]["ReqN"] = 0
                        break

        if number_weighted_n > 0:
            average_weighted_n = total_weighted_n / number_weighted_n

    return { "geojson_data" : biomass_geojson, "n": average_weighted_n }