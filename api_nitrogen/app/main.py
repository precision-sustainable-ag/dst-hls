import json
from typing import Union
from fastapi import FastAPI
from fastapi.exceptions import HTTPException
from fastapi.responses import RedirectResponse
from .constants import species, plant_groups, plant_growth_stages

description = """
Plants Factors API for Ncalc DST tool. 🌱 🌿 🍀
"""

app = FastAPI(
    title="Plants Factors API",
    description=description,
    summary="Plants Factors API for Ncalc DST tool",
    version="0.0.1",
    terms_of_service="For more information about Precision Sustainable Agriculture projects, please visit https://precisionsustainableag.org/",
    contact={
        "name": "Precision Sustainable Agriculture",
        "url": "https://precisionsustainableag.org/",
    },
)

with open('app/assets/plant_growth_lut.json') as fp:
    plant_growth_lut = json.loads(fp.read())
    
species_lower = {}
for key, val in species.items():
    species_lower[key.lower()] = [v.lower() for v in val] 


@app.get("/")
async def docs_redirect():
    return RedirectResponse(url='/docs')


@app.get("/health")
def read_root():
    return {"health": "ok"}


@app.get("/species")
def read_species():
    return species_lower


@app.get("/plantgroups")
def read_species():
    return plant_groups


@app.get("/plantgrowthstages")
def read_species():
    return plant_growth_stages


@app.get("/plantfactors")
def read_species():
    return plant_growth_lut


@app.get("/plantfactors/{plant_specie}/{growth_stage}")
async def plant_fators(plant_specie: str = None, growth_stage: str = None):
    if not plant_specie in plant_growth_lut.keys():
        raise HTTPException(status_code=404, detail=f"{plant_specie} doesn't exist and is not a valid plant specie")
    
    if not growth_stage in plant_growth_lut[plant_specie]:
        raise HTTPException(status_code=404, detail=f"{growth_stage} doesn't exist and is not a valid plant growth stage")
    
    return plant_growth_lut[plant_specie][growth_stage]

