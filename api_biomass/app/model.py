from pydantic import BaseModel, create_model
from app.constants import SAMPLE_GEOMETRY
from typing import Dict, List, Optional


class HLSGeomModel(BaseModel):
    type: str = SAMPLE_GEOMETRY["type"]
    coordinates: list[list[list[float]]] = SAMPLE_GEOMETRY["coordinates"]

class TaskIDModel(BaseModel):
    task_id: str

class TaskRequestModel(BaseModel):
    maxCloudCover: int = 5
    startDate: str = "2022-10-01"
    endDate: str = "2023-03-03"
    geometry: HLSGeomModel

    
class TaskResponseModel(BaseModel):
    task_id: str
    task_status: str
    task_result: create_model('TaskResult', 
                                time_elapsed=(str, ...), 
                                tile_num=(int, ...), 
                                dates=(list[str], ...), 
                                epsg=(list[str], ...), 
                                bbox=(list[float], ...), 
                                data_array=(list[list[list[int]]], ...),
                                mask_array=(list[list[list[bool]]], ...),
                              ) | None
    

class PointModel(BaseModel):
    camera_id: int
    lon: float
    lat: float
    species: Dict[str, float]
    biomass_percentile_per_species: Optional[Dict[str, float]]

class GenerateGridRequest(BaseModel):
    points: List[PointModel]
    grid_size_meters: Optional[float]
    species_name: Optional[str]
    
