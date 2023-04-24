from pydantic import BaseModel, create_model
from constants import SAMPLE_GEOMETRY


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

    
class TaskResopnseModel(BaseModel):
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
    
    
