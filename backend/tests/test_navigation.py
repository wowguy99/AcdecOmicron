"""Guide navigation / roadmap sentence filtering."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.parsing.navigation import (
    filter_navigation_cards,
    is_guide_navigation_card,
    is_guide_navigation_sentence,
    strip_guide_navigation,
)


def test_detects_section_preview_sentence():
    assert is_guide_navigation_sentence(
        "In Section I of this resource guide, we will establish some key concepts "
        "that will serve as the foundation for what climate change means."
    )
    assert is_guide_navigation_sentence(
        "Sections II and III of this guide will cover the history of human "
        "interactions with climate over roughly the past 10,000 years."
    )
    assert is_guide_navigation_sentence(
        "That phenomenon will be the subject of section III of this resource guide."
    )


def test_keeps_substantive_section_facts():
    assert not is_guide_navigation_sentence(
        "The third, and final, set of key concepts in Section I focuses on "
        "the idea of the Anthropocene."
    )
    assert not is_guide_navigation_sentence(
        "According to the International Union of Geological Sciences (IUGS), "
        "the Holocene began about 11,700 years ago."
    )


def test_strip_guide_navigation_removes_roadmap():
    body = (
        "Climate change is important. In Section II of this guide, we will "
        "describe human civilization. The Holocene began 11,700 years ago."
    )
    stripped = strip_guide_navigation(body)
    assert "Section II of this guide" not in stripped
    assert "11,700 years ago" in stripped
    assert "Climate change is important" in stripped


def test_filter_navigation_cards():
    cards = [
        {
            "front": "What will Section II of this guide describe?",
            "back": "human interactions with climate",
            "tag": "other",
        },
        {
            "front": "When did the Holocene begin?",
            "back": "about 11,700 years ago",
            "tag": "date",
        },
    ]
    kept = filter_navigation_cards(cards)
    assert len(kept) == 1
    assert kept[0]["front"] == "When did the Holocene begin?"


def test_is_guide_navigation_card():
    assert is_guide_navigation_card(
        "What does Section III of this guide will cover?",
        "the Anthropocene",
    )
    assert not is_guide_navigation_card(
        "What is the Anthropocene?",
        "a proposed geological epoch",
    )
