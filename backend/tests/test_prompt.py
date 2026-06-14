"""Unit tests for tolerant JSON parsing/repair (no PDF, no network)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.generation.prompt import SYSTEM_PROMPT, parse_cards


def test_system_prompt_covers_examples_and_comparatives():
    assert "illustrative example" in SYSTEM_PROMPT.lower()
    assert "comparative" in SYSTEM_PROMPT.lower()
    assert "split into multiple cards" in SYSTEM_PROMPT


def test_system_prompt_skips_guide_roadmap():
    lower = SYSTEM_PROMPT.lower()
    assert "guide navigation" in lower or "roadmap" in lower
    assert "section ii of this guide" in lower


def test_system_prompt_covers_source_attribution():
    lower = SYSTEM_PROMPT.lower()
    assert "source attribution" in lower
    assert "according to" in lower


def test_system_prompt_covers_yes_no_guidance():
    lower = SYSTEM_PROMPT.lower()
    assert "avoid yes/no backs" in lower or "avoid yes/no" in lower
    assert "little ice age" in lower
    assert "single, unified event" in lower


def test_user_prompt_mentions_yes_no_guidance():
    from app.generation.prompt import build_user_prompt

    prompt = build_user_prompt(
        subject="Social Science",
        section="SECTION III",
        subheader="Climate",
        tags=[("date", "years and eras")],
        track="A",
        text="The LIA impacted regions unevenly.",
    )
    assert "substantive backs over yes/no" in prompt.lower()


def test_user_prompt_mentions_source_attribution():
    from app.generation.prompt import build_user_prompt

    prompt = build_user_prompt(
        subject="Social Science",
        section="SECTION III",
        subheader="Section III Introduction",
        tags=[("date", "years and eras")],
        track="A",
        text="According to the IUGS, the Holocene began about 11,700 years ago.",
    )
    assert "source attribution" in prompt.lower()


def test_plain_json():
    raw = '{"cards":[{"front":"Q","back":"A","tag":"date"}]}'
    cards = parse_cards(raw)
    assert cards == [{"front": "Q", "back": "A", "tag": "date"}]


def test_fenced_json():
    raw = '```json\n{"cards":[{"front":"Q","back":"A","tag":"x"}]}\n```'
    assert parse_cards(raw)[0]["front"] == "Q"


def test_truncated_json_salvaged():
    raw = (
        '{"cards":[{"front":"Q1","back":"A1","tag":"t"},'
        '{"front":"Q2","back":"A2","tag":"t"},{"front":"Q3","back":'
    )
    cards = parse_cards(raw)
    assert len(cards) == 2
    assert cards[1]["front"] == "Q2"


def test_missing_fields_dropped():
    raw = '{"cards":[{"front":"only front"},{"front":"Q","back":"A","tag":"t"}]}'
    cards = parse_cards(raw)
    assert len(cards) == 1


def test_question_answer_aliases():
    raw = '{"cards":[{"question":"Q","answer":"A","category":"date"}]}'
    cards = parse_cards(raw)
    assert cards == [{"front": "Q", "back": "A", "tag": "date"}]


def test_empty_cards_array():
    assert parse_cards('{"cards":[]}') == []


def test_chunk_low_yield_detects_listening_timestamps():
    from app.generation.prompt import chunk_low_yield

    text = "\n".join(["0:00 Intro", "0:45 Verse", "1:30 Chorus"])
    assert chunk_low_yield(text)


def test_no_json_raises():
    import pytest

    with pytest.raises(ValueError):
        parse_cards("sorry, I cannot help with that")
