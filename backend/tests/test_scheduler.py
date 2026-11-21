import itertools
import random
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app import scheduler  # noqa: E402
from app.scheduler import create_data, end_of, greedy, schedule  # noqa: E402
from check_contract import validate_schedule_response  # noqa: E402

needs_minizinc = pytest.mark.skipif(shutil.which("minizinc") is None, reason="MiniZinc runs in Docker")


def task(id, duration_days, depends_on=(), owner=None):
    return {"id": id, "name": id, "owner": owner, "duration_days": duration_days, "depends_on": list(depends_on)}


def check(tasks, deadline_day=10):
    result = schedule(tasks, deadline_day)
    assert validate_schedule_response({"tasks": tasks, "deadline_day": deadline_day}, result) == []
    return result


def random_plan(seed, n, people):
    rnd = random.Random(seed)
    return [task(f"T{i}", rnd.randint(1, 9), [f"T{j}" for j in range(i) if rnd.random() < 0.15],
                 rnd.choice(people + [None])) for i in range(n)]


def brute_force_end(tasks):
    """Greedy over every task order: the best one is optimal for small plans."""
    data = create_data(tasks)
    return min(end_of(data, greedy(data, list(order))) for order in itertools.permutations(range(len(tasks))))


def greedy_end(tasks):
    data = create_data(tasks)
    return end_of(data, greedy(data))


def test_single_task_ends_after_its_duration():
    result = schedule([task("A", 3)], 10)
    assert result["schedule"] == [{"id": "A", "start_day": 0, "end_day": 3}]
    assert result["end_day"] == 3


def test_dependent_task_starts_after_its_dependency():
    result = schedule([task("A", 3), task("B", 2, ["A"])], 10)
    by_id = {item["id"]: item for item in result["schedule"]}
    assert by_id["B"]["start_day"] == 3
    assert result["end_day"] == 5


def test_contract_example():
    tasks = [task("A", 3, [], "Ann"), task("B", 2, ["A"], "Ann"), task("C", 4, [], "Ann"), task("D", 2, ["C"], "Bob")]
    result = check(tasks)
    assert result["end_day"] == 9
    assert result["meets_deadline"] is True and result["days_late"] == 0


def test_empty_plan():
    result = check([], deadline_day=5)
    assert result["schedule"] == [] and result["end_day"] == 0 and result["meets_deadline"] is True


@pytest.mark.parametrize("tasks, expected", [
    ([task("A", 1, ["A"])], {"A"}),
    ([task("A", 1, ["B"]), task("B", 1, ["A"])], {"A", "B"}),
    ([task("X", 1, ["A"]), task("A", 1, ["B"]), task("B", 1, ["C"]), task("C", 1, ["A"])], {"A", "B", "C"}),
])
def test_cycle_is_named(tasks, expected):
    result = check(tasks)
    assert result["status"] == "cycle" and set(result["cycle"]) == expected


def test_invalid_solver_answer_is_not_used(monkeypatch):
    def overlapping(data, pairs, upper):
        return {"status": "OPTIMAL_SOLUTION", "sol": [0] * data["n"]}
    monkeypatch.setattr(scheduler, "run_minizinc", overlapping)
    tasks = [task("A", 2, [], "Ann"), task("B", 2, [], "Ann"), task("C", 1, ["A"], "Bob")]
    result = check(tasks)
    assert result["end_day"] == greedy_end(tasks) and result["optimal"] is False


@needs_minizinc
@pytest.mark.parametrize("seed", range(25))
def test_minizinc_matches_brute_force(seed):
    tasks = random_plan(100 + seed, 7, ["Ann", "Bob"])
    result = check(tasks)
    assert result["end_day"] == brute_force_end(tasks) and result["optimal"] is True
