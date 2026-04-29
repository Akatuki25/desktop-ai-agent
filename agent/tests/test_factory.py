"""Tests for factory.py — focuses on logic that lives there.

Most of factory.build_app is wiring (FastAPI + scheduler + TTS) that
gets exercised through the integration tests. The one piece of actual
*conditional* logic worth a unit test is the first-run persona seed:
it must populate empty memory but must NOT overwrite a user's
customized persona/tone on subsequent boots.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent.factory import _DEFAULT_PERSONA, _DEFAULT_TONE, seed_default_persona
from agent.memory import BehaviorConfig, CoreMemory, Database


@pytest.fixture()
def memories(tmp_path: Path) -> tuple[CoreMemory, BehaviorConfig]:
    db = Database(tmp_path / "factory.sqlite")
    return CoreMemory(db), BehaviorConfig(db)


def test_seed_writes_defaults_when_empty(
    memories: tuple[CoreMemory, BehaviorConfig],
) -> None:
    core, behavior = memories
    assert core.all() == {}
    assert behavior.all() == {}

    seed_default_persona(core, behavior)

    assert core.get("persona") == _DEFAULT_PERSONA
    assert behavior.get("tone") == _DEFAULT_TONE


def test_seed_preserves_existing_user_customization(
    memories: tuple[CoreMemory, BehaviorConfig],
) -> None:
    # The "first run only" guard is the whole point — without it, a user
    # who customizes their persona would have it overwritten every daemon
    # restart. Lock that guarantee in.
    core, behavior = memories
    core.set("persona", "user-customized persona")
    behavior.set("tone", "user-customized tone")

    seed_default_persona(core, behavior)

    assert core.get("persona") == "user-customized persona"
    assert behavior.get("tone") == "user-customized tone"


def test_seed_is_idempotent_on_partial_state(
    memories: tuple[CoreMemory, BehaviorConfig],
) -> None:
    # Edge case: user has touched core but not behavior (or vice versa).
    # Each table's "empty?" check is independent, so the untouched table
    # still gets its default while the touched one is left alone.
    core, behavior = memories
    core.set("persona", "user-customized")
    # behavior remains empty

    seed_default_persona(core, behavior)

    assert core.get("persona") == "user-customized"
    assert behavior.get("tone") == _DEFAULT_TONE
