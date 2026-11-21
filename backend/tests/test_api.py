import json
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.main import app  # noqa: E402
from check_contract import validate_schedule_response  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
client = TestClient(app)


def task(id="A", **changes):
    return {"id": id, "name": "Book the hall", "owner": "Ann", "duration_days": 3, "depends_on": [], **changes}


def test_plans_are_listed():
    response = TestClient(app).get("/api/plans")
    assert response.status_code == 200
    assert {plan["id"] for plan in response.json()} == {"spring-market", "lantern-festival", "harbour-run"}


def test_schedule_contract_example():
    request = json.loads((ROOT / "examples" / "schedule-request.json").read_text())
    response = client.post("/api/schedule", json=request)
    assert response.status_code == 200
    assert validate_schedule_response(request, response.json()) == []
    assert response.json()["end_day"] == 9


def test_extra_fields_are_ignored():
    response = client.post("/api/schedule", json={"tasks": [task(colour="red")], "deadline_day": 10, "note": "x"})
    assert response.status_code == 200


def test_self_dependency_is_a_cycle_not_an_error():
    response = client.post("/api/schedule", json={"tasks": [task(depends_on=["A"])], "deadline_day": 10})
    assert response.status_code == 200
    assert response.json()["status"] == "cycle" and response.json()["cycle"] == ["A"]


@pytest.mark.parametrize("body", [
    {"tasks": [task(), task()], "deadline_day": 10},
    {"tasks": [task(depends_on=["Z"])], "deadline_day": 10},
    {"tasks": [task(depends_on=["Z", "A"])], "deadline_day": 10},
    {"tasks": [task(duration_days=0)], "deadline_day": 10},
    {"tasks": [task(duration_days=-2)], "deadline_day": 10},
    {"tasks": [task(duration_days=1.5)], "deadline_day": 10},
    {"tasks": [task(duration_days="3")], "deadline_day": 10},
    {"tasks": [task(duration_days=True)], "deadline_day": 10},
    {"tasks": [task(id=1)], "deadline_day": 10},
    {"tasks": [task(owner=5)], "deadline_day": 10},
    {"tasks": [{k: v for k, v in task().items() if k != "owner"}], "deadline_day": 10},
    {"tasks": [task(depends_on="B")], "deadline_day": 10},
    {"tasks": [task(id=f"T{i}") for i in range(61)], "deadline_day": 10},
    {"tasks": [task()], "deadline_day": None},
    {"tasks": [task()]},
    {"deadline_day": 10},
    {"tasks": "A", "deadline_day": 10},
    [task()],
])
def test_bad_input_is_refused(body):
    response = client.post("/api/schedule", json=body)
    assert 400 <= response.status_code < 500
    assert response.json()["message"]


def test_bad_json_is_refused():
    response = client.post("/api/schedule", content=b"{not json", headers={"Content-Type": "application/json"})
    assert 400 <= response.status_code < 500
    assert response.json()["message"]


def test_sixty_tasks_answer_in_time():
    tasks = [task(f"T{i}", owner=["Ann", "Bob", "Cy"][i % 3], duration_days=1 + i % 9,
                  depends_on=[f"T{i - 7}"] if i >= 7 else []) for i in range(60)]
    started = time.time()
    response = client.post("/api/schedule", json={"tasks": tasks, "deadline_day": 50})
    assert response.status_code == 200
    assert time.time() - started < 8
    assert validate_schedule_response({"tasks": tasks, "deadline_day": 50}, response.json()) == []


def test_plan_with_a_cycle_does_not_crash():
    response = client.get("/api/plans/harbour-run")
    assert response.status_code == 200
    assert response.json()["schedule"]["status"] == "cycle"
