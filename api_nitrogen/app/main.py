import json
import numpy as np
from typing import Union, List
from typing_extensions import Self
from fastapi import FastAPI, Depends, Query
from fastapi.exceptions import HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field, validator, ValidationError, model_validator
from typing import List, Optional, Literal
from fastapi.middleware.cors import CORSMiddleware
from .constants import species, plant_groups, plant_growth_stages

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

with open('app/assets/plant_growth_lut.json') as fp:
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
    return species_lower


@app.get("/plantgroups")
def read_plantgroups():
    return plant_groups


@app.get("/plantgrowthstages")
def read_plantgrowthstages():
    return plant_growth_stages


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
    

@app.post("/nitrogen")
async def read_nitrogen(biomass_payload: BiomassPayload):
    biomass_payload.data_array = (0.001*np.array(biomass_payload.data_array)**2).tolist()
    
    return biomass_payload