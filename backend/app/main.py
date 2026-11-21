import json
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr

from .scheduler import schedule

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
DIST = ROOT / "frontend" / "dist"
MAX_TASKS = 60

app = FastAPI()


class Task(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: StrictStr
    name: StrictStr
    owner: Optional[StrictStr]
    duration_days: StrictInt = Field(ge=1)
    depends_on: list[StrictStr]


class ScheduleRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    tasks: list[Task] = Field(max_length=MAX_TASKS)
    deadline_day: StrictInt


def refuse(message):
    return JSONResponse(status_code=422, content={"message": message})


@app.exception_handler(RequestValidationError)
def invalid_request(request: Request, exc: RequestValidationError):
    error = exc.errors()[0]
    field = ".".join(str(p) for p in error["loc"] if p != "body")
    return refuse(f"{field}: {error['msg']}" if field else error["msg"])


@app.get("/api/plans")
def list_plans():
    plans = []
    for path in sorted((DATA / "plans").glob("*.md"), reverse=True):
        title = next((line.lstrip("# ").strip() for line in path.read_text().splitlines() if line.startswith("#")), path.stem)
        plans.append({"id": path.stem, "title": title})
    return plans


@app.get("/api/plans/{plan_id}")
def get_plan(plan_id: str):
    text = (DATA / "plans" / f"{plan_id}.md").read_text()
    review = json.loads((DATA / "reviews" / f"{plan_id}.json").read_text())
    return {
        "id": plan_id,
        "text": text,
        "review": review,
        "schedule": schedule(review["tasks"], review["deadline_day"]),
    }


@app.post("/api/schedule")
def post_schedule(body: ScheduleRequest):
    tasks = [task.model_dump() for task in body.tasks]
    ids = [t["id"] for t in tasks]
    repeated = sorted({i for i in ids if ids.count(i) > 1})
    if repeated:
        return refuse(f"Task ids must be unique. Repeated: {', '.join(map(repr, repeated))}.")
    known = set(ids)
    for t in tasks:
        for dep in t["depends_on"]:
            if dep not in known:
                return refuse(f"Task {t['id']!r} depends on {dep!r}, which is not in the request.")
    return schedule(tasks, body.deadline_day)


if DIST.exists():
    app.mount("/", StaticFiles(directory=DIST, html=True))
