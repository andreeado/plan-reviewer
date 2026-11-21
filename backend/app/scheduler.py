import json
import logging
import os
import subprocess
import tempfile
from functools import cache
from pathlib import Path

logger = logging.getLogger(__name__)

MODEL_FILE = Path(__file__).resolve().parents[1] / "minizinc" / "schedule.mzn"
TIME_LIMIT_MS = int(os.environ.get("SCHEDULE_TIME_LIMIT_MS", 5000))
SEED = 55


def schedule(tasks, deadline_day):
    data = create_data(tasks)
    cycle = find_cycle(data)
    if cycle:
        return cycle_response(cycle, deadline_day)

    # PHASE 1: FEASIBILITY (greedy, always a valid schedule)
    start = greedy(data)
    pairs = order_pairs(data)
    if not pairs:
        # Nobody has two tasks that could clash: earliest starts are optimal
        return scheduled_response(data, start, deadline_day, optimal=True)

    # PHASE 2: OPTIMIZATION (MiniZinc + Gecode, bounded by the greedy end day)
    try:
        result = run_minizinc(data, pairs, end_of(data, start))
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        logger.warning(f"MiniZinc failed ({e}), keeping the greedy schedule.")
        return scheduled_response(data, start, deadline_day, optimal=False)

    optimal = False
    match result["status"]:
        # SOLUTION FOUND (proven optimal, or the best one within the time limit)
        case "OPTIMAL_SOLUTION" | "SATISFIED" if valid(data, result["sol"]):
            start, optimal = result["sol"], result["status"] == "OPTIMAL_SOLUTION"
        # TIMEOUT WITHOUT SOLUTION OR UNUSABLE ANSWER
        case _:
            logger.warning(f"MiniZinc returned {result['status']}, keeping the greedy schedule.")
    return scheduled_response(data, start, deadline_day, optimal)


def create_data(tasks):
    ids = [t["id"] for t in tasks]
    position = {task_id: i for i, task_id in enumerate(ids)}
    owners = sorted({t["owner"] for t in tasks if t["owner"] is not None})
    return {
        'n': len(tasks),
        'ids': ids,
        'dur': [t["duration_days"] for t in tasks],
        'deps': [sorted({position[d] for d in t["depends_on"]}) for t in tasks],
        'owner': [owners.index(t["owner"]) + 1 if t["owner"] is not None else 0 for t in tasks],
    }


def find_cycle(data):
    """Ids of one circular dependency, in dependency order, or [] if there is none."""
    state, path = {}, []

    def visit(i):
        state[i] = "on path"
        path.append(i)
        for d in data['deps'][i]:
            if state.get(d) == "on path":
                return path[path.index(d):]
            if d not in state and (cycle := visit(d)):
                return cycle
        state[i] = "done"
        path.pop()
        return None

    for i in range(data['n']):
        if i not in state and (cycle := visit(i)):
            return [data['ids'][k] for k in cycle]
    return []


def order_pairs(data):
    """Same-owner pairs that dependencies do not already order (the y[i,j] pairs of the MIP)."""
    @cache
    def ancestors(j):
        return frozenset().union(*({i} | ancestors(i) for i in data['deps'][j]))

    owner = data['owner']
    return [(i, j) for i in range(data['n']) for j in range(i + 1, data['n'])
            if owner[i] and owner[i] == owner[j] and i not in ancestors(j) and j not in ancestors(i)]


def greedy(data, priority=None):
    """Place the ready task with the highest priority (default: longest chain after it) at its earliest free time."""
    n, dur, deps, owner = data['n'], data['dur'], data['deps'], data['owner']
    succ = [[j for j in range(n) if i in deps[j]] for i in range(n)]

    @cache
    def tail(i):
        return dur[i] + max((tail(s) for s in succ[i]), default=0)

    priority = priority or [tail(i) for i in range(n)]
    start, busy = [None] * n, {}
    ready = [i for i in range(n) if not deps[i]]
    while ready:
        i = max(ready, key=lambda k: (priority[k], -k))
        ready.remove(i)
        t = max((start[d] + dur[d] for d in deps[i]), default=0)
        if owner[i]:
            for busy_start, busy_end in sorted(busy.setdefault(owner[i], [])):
                if t + dur[i] <= busy_start:
                    break
                t = max(t, busy_end)
            busy[owner[i]].append((t, t + dur[i]))
        start[i] = t
        ready += [j for j in succ[i] if all(start[d] is not None for d in deps[j])]
    return start


def run_minizinc(data, pairs, upper):
    model_data = {
        "n": data['n'], "UB": upper, "dur": data['dur'], "owner": data['owner'],
        "deps": [{"set": [d + 1 for d in task_deps]} for task_deps in data['deps']],
        "pair_i": [i + 1 for i, _ in pairs], "pair_j": [j + 1 for _, j in pairs],
    }
    with tempfile.NamedTemporaryFile("w", suffix=".json") as data_file:
        json.dump(model_data, data_file)
        data_file.flush()
        cmd = ["minizinc", str(MODEL_FILE), data_file.name, "--solver", "gecode",
               "--time-limit", str(TIME_LIMIT_MS), "--random-seed", str(SEED), "--json-stream", "--intermediate"]
        output = subprocess.run(cmd, capture_output=True, text=True, timeout=TIME_LIMIT_MS / 1000 + 2).stdout

    result = {"status": "UNKNOWN", "sol": None}
    for message in map(json.loads, output.splitlines()):
        match message.get("type"):
            case "solution":
                result["sol"] = json.loads(message["output"]["default"])["start"]
            case "status":
                result["status"] = message["status"]
            case "error":
                raise ValueError(message.get("message", "MiniZinc error"))
    return result


def end_of(data, start):
    return max((start[i] + data['dur'][i] for i in range(data['n'])), default=0)


def valid(data, start):
    """Durations, dependencies and one task at a time per person."""
    n, dur, owner = data['n'], data['dur'], data['owner']
    if not isinstance(start, list) or len(start) != n or any(type(s) is not int or s < 0 for s in start):
        return False
    if any(start[j] < start[i] + dur[i] for j in range(n) for i in data['deps'][j]):
        return False
    return all(start[i] + dur[i] <= start[j] or start[j] + dur[j] <= start[i]
               for i in range(n) for j in range(i + 1, n) if owner[i] and owner[i] == owner[j])


def scheduled_response(data, start, deadline_day, optimal):
    end_day = end_of(data, start)
    return {
        "status": "scheduled",
        "schedule": [{"id": data['ids'][i], "start_day": start[i], "end_day": start[i] + data['dur'][i]}
                     for i in range(data['n'])],
        "end_day": end_day,
        "deadline_day": deadline_day,
        "meets_deadline": None if deadline_day is None else end_day <= deadline_day,
        "days_late": None if deadline_day is None else max(0, end_day - deadline_day),
        "cycle": [],
        "optimal": optimal,
    }


def cycle_response(cycle, deadline_day):
    return {
        "status": "cycle",
        "schedule": [],
        "end_day": None,
        "deadline_day": deadline_day,
        "meets_deadline": None,
        "days_late": None,
        "cycle": cycle,
    }
