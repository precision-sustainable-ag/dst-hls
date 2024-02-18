from typing import Union
from fastapi import FastAPI
from .constants import species 

app = FastAPI()


@app.get("/")
def read_root():
    return {"health": "ok"}

@app.get("/species")
def read_species():
    return species

@app.get("/plantfactors/{plant_specie}/{growth_stage}")
def plant_fators(plant_specie: str = None, growth_stage: str = None):
    return {"plant_specie": plant_specie, "growth_stage": growth_stage}