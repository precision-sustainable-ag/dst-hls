import os
import sys
import numpy as np
sys.path.append(os.path.join(os.getcwd(), "celery"))
from worker import create_biomass_geojson_projected
sys.stdout.flush()
import uvicorn
from celery.result import AsyncResult
from fastapi import FastAPI, APIRouter, HTTPException, Body, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.encoders import jsonable_encoder

# os.chdir(os.path.join(os.getcwd(), 'app'))
from app.model import TaskIDModel, TaskRequestModel, TaskResponseModel, GenerateGridRequest
from app.constants import API_PREFIX, ALLOWED_CORS

os.chdir(os.path.join(os.getcwd(), 'celery'))
from worker import create_task


root = APIRouter()


@root.get("/", include_in_schema=False)
async def docs_redirect(request: Request):
    return RedirectResponse(url='/docs')


@root.get("/health")
async def health_check() -> dict:
    """Full health-check endpoint"""
    return {"dst": "ok"}

@root.post("/tasks", response_model=TaskIDModel, status_code=201)
async def run_task(payload: TaskRequestModel) -> TaskIDModel:
    task = create_task.delay(jsonable_encoder(payload))
    return JSONResponse({"task_id": task.id})


@root.get("/tasks/{task_id}", response_model=TaskResponseModel)
async def get_task_status(task_id: str) -> TaskResponseModel:
    task_result = AsyncResult(task_id)
    print(task_result)
    result = jsonable_encoder({
        "task_id": task_id,
        "task_status": task_result.status,
        "task_result": task_result.result
    })
    return JSONResponse(result)

@root.post("/generate-grid")
async def generate_grid(payload: GenerateGridRequest):
    try:
        points = [p.dict() for p in payload.points]
        S = payload.grid_size_meters

        lons = [p["lon"] for p in points]
        lats = [p["lat"] for p in points]
        min_lon, max_lon = min(lons), max(lons)
        min_lat, max_lat = min(lats), max(lats)
        bbox = [min_lon, min_lat, max_lon, max_lat]

        lat_ref = (min_lat + max_lat) / 2
        deg_per_meter_lat = 1 / 111_320.0
        deg_per_meter_lon = 1 / (111_320.0 * np.cos(np.radians(lat_ref)))

        grid_size_lat = S * deg_per_meter_lat
        grid_size_lon = S * deg_per_meter_lon

        row_count = int(np.ceil((max_lat - min_lat) / grid_size_lat))
        col_count = int(np.ceil((max_lon - min_lon) / grid_size_lon))

        biomass_sum = np.zeros((row_count, col_count))
        biomass_count = np.zeros((row_count, col_count), dtype=int)

        species_biomass_sum = {}
        species_biomass_count = {}
        species_all = set()

        for point in points:
            row_index = int((point['lat'] - min_lat) / grid_size_lat)
            col_index = int((point['lon'] - min_lon) / grid_size_lon)
            row_index = row_count - 1 - row_index

            added = False
            for species, biomass_value in point['species'].items():
                if not np.isfinite(biomass_value):
                    continue

                if biomass_value < 0:
                    continue

                if species not in species_biomass_sum:
                    species_biomass_sum[species] = np.zeros((row_count, col_count))
                    species_biomass_count[species] = np.zeros((row_count, col_count), dtype=int)

                biomass_sum[row_index, col_index] += biomass_value

                species_biomass_sum[species][row_index, col_index] += biomass_value
                species_biomass_count[species][row_index, col_index] += 1

                if not added:
                    biomass_count[row_index, col_index] += 1
                    added = True
                species_all.add(species)

        with np.errstate(invalid='ignore', divide='ignore'):
            biomass_average = biomass_sum / biomass_count
        biomass_average[np.isnan(biomass_average)] = 0

        species_biomass_average = {}
        for species in species_all:
            with np.errstate(invalid='ignore', divide='ignore'):
                avg = species_biomass_sum[species] / species_biomass_count[species]
            avg[np.isnan(avg)] = 0
            species_biomass_average[species] = avg.tolist()

        data_array = biomass_average.tolist()
        biomass_geojson = create_biomass_geojson_projected(data_array, bbox)

        response_data = {
            "data_array": data_array,
            "bbox": bbox,
            "grid_dimensions": {
                "rows": row_count,
                "cols": col_count
            },
            "biomass_count": biomass_count.tolist(),
            "species": list(species_all),
            "biomass_geojson": biomass_geojson,
            "species_biomass_sum": {species: species_biomass_sum[species].tolist() for species in species_all},
            "species_biomass_average": species_biomass_average,
        }

        return JSONResponse(content=response_data, status_code=200)
    except Exception as e:
        return JSONResponse(content=e, status_code=400)

app = FastAPI(
    debug=True,
    docs_url=f'{API_PREFIX}/docs',
    redoc_url=f'{API_PREFIX}/redoc',
    openapi_url=f'{API_PREFIX}/openapi.json')

app.include_router(root, prefix=API_PREFIX)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=ALLOWED_CORS,
    allow_methods=ALLOWED_CORS,
    allow_headers=ALLOWED_CORS,
)

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
