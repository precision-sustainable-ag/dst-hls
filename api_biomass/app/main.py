import os
import sys
sys.stdout.flush()
import uvicorn
from celery.result import AsyncResult
from fastapi import FastAPI, APIRouter, HTTPException, Body, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.encoders import jsonable_encoder

# os.chdir(os.path.join(os.getcwd(), 'app'))
from app.model import TaskIDModel, TaskRequestModel, TaskResopnseModel
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


@root.get("/tasks/{task_id}", response_model=TaskResopnseModel)
async def get_task_status(task_id: str) -> TaskResopnseModel:
    task_result = AsyncResult(task_id)
    print(task_result, flush=True)
    result = jsonable_encoder({
        "task_id": task_id,
        "task_status": task_result.status,
        "task_result": task_result.result
    })
    return JSONResponse(result)

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
