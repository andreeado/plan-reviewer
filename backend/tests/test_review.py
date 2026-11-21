import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.review import check, review_plan  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
PLAN = "| Book the hall | Ann | 3 days | - |\nAnn will book the hall."
GOOD = {"deadline_day": 10, "findings": [],
        "tasks": [{"id": "T1", "name": "Book the hall", "owner": "Ann", "duration_days": 3, "depends_on": [], "quote": "Book the hall"}]}


def with_task(**changes):
    return json.dumps({**GOOD, "tasks": [{**GOOD["tasks"][0], **changes}]})


@pytest.mark.parametrize("answer", [
    "not json",
    with_task(depends_on=["T9"]),
    with_task(duration_days=0),
    with_task(quote="Booking the hall"),
    with_task(owner=7),
])
def test_unusable_review_is_refused(answer):
    """A fake model that gives the same bad answer twice: the code must refuse it, not return it."""
    with pytest.raises(ValueError):
        review_plan(PLAN, ask=lambda messages: answer)


@pytest.mark.parametrize("name", ["spring-market", "lantern-festival", "harbour-run"])
def test_stored_reviews_are_valid(name):
    plan = (ROOT / "data" / "plans" / f"{name}.md").read_text()
    review = (ROOT / "data" / "reviews" / f"{name}.json").read_text()
    assert check(review, plan)[1] == []
