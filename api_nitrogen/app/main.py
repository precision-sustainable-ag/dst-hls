import json
from typing import Union
from fastapi import FastAPI
from .constants import species, plant_groups, plant_growth_stages

app = FastAPI()


@app.get("/")
def read_root():
    return {"health": "ok"}

@app.get("/species")
def read_species():
    return species

@app.get("/plantgroups")
def read_species():
    return plant_groups

@app.get("/plantgrowthstages")
def read_species():
    return plant_growth_stages

@app.get("/plantfactors")
def read_species():
    with open('app/assets/plant_growth_lut.json') as fp:
        lut = json.loads(fp.read())
    return lut

@app.get("/plantfactors/{plant_specie}/{growth_stage}")
def plant_fators(plant_specie: str = None, growth_stage: str = None):
    with open('app/assets/plant_growth_lut.json') as fp:
        lut = json.loads(fp.read())
    return lut[plant_specie][growth_stage]

