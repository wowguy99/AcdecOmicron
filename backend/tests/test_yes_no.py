"""Tests for yes/no card enhancement post-processor."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.generation.yes_no import enhance_yes_no_cards


def _one(front: str, back: str) -> dict[str, str]:
    return {"front": front, "back": back, "tag": "other"}


def test_lia_evenly_no_becomes_substantive():
    front = "Did the Little Ice Age (LIA) impact the entire globe evenly?"
    cards = enhance_yes_no_cards([_one(front, "No")])
    assert cards[0]["front"] == "How did the Little Ice Age (LIA) impact the entire globe?"
    assert cards[0]["back"] == "Unevenly"


def test_lia_single_unified_event_keeps_yes_no():
    front = "Was the LIA a single, Unified Event?"
    cards = enhance_yes_no_cards([_one(front, "No")])
    assert cards[0]["front"] == front
    assert cards[0]["back"] == "No"


def test_evenly_yes_becomes_substantive():
    front = "Did the LIA impact the entire globe evenly?"
    cards = enhance_yes_no_cards([_one(front, "Yes")])
    assert cards[0]["front"] == "How did the LIA impact the entire globe?"
    assert cards[0]["back"] == "Evenly"


def test_non_yes_no_unchanged():
    card = _one("What year did the LIA begin?", "1300")
    assert enhance_yes_no_cards([card]) == [card]


def test_was_x_a_type_of_y_keeps_yes_no():
    front = "Was X a type of Y?"
    cards = enhance_yes_no_cards([_one(front, "No")])
    assert cards[0]["front"] == front
    assert cards[0]["back"] == "No"


def test_occurrence_question_keeps_yes_no():
    front = "Did the volcanic eruption occur in 1815?"
    cards = enhance_yes_no_cards([_one(front, "Yes")])
    assert cards[0]["front"] == front
    assert cards[0]["back"] == "Yes"


def test_yes_no_without_manner_adverb_unchanged():
    front = "Did the LIA affect all continents?"
    cards = enhance_yes_no_cards([_one(front, "No")])
    assert cards[0]["front"] == front
    assert cards[0]["back"] == "No"
