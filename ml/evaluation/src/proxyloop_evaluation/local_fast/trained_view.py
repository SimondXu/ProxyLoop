"""The trained half of the Fast input: a product view in the 03C prompt format.

The distilled model was trained on views whose latest Provider event carries
``PHASE03B_PUBLIC_MARKER`` plus the canonical ``SafeObservation`` JSON
(``phase03c_prompt_set._public_content``).  ``trained_view`` puts the given
observation there, byte-for-byte in that format, and nothing else changes;
the frozen v6 builder then renders the prompt.  When the observation equals
the one the trained view was built from, the prompt is byte-identical.
"""

from __future__ import annotations

import json
from typing import Final

from proxyloop_agent_core import SafeObservation
from proxyloop_contracts import FastModelView
from pydantic import ValidationError

from proxyloop_evaluation.phase03b_experiment import PHASE03B_PUBLIC_MARKER

TRAINED_VIEW_VERSION: Final = "phase-03c-trained-view-v1"


class ObservationMismatchError(ValueError):
    """The observation names another Case, Case revision, or constraint set."""


class TrainedViewError(ValueError):
    """The view cannot carry the observation in the trained format."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def observation_content(observation: SafeObservation) -> str:
    return f"{PHASE03B_PUBLIC_MARKER}\n" + json.dumps(
        observation.to_dict(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def check_observation_matches(
    view: FastModelView, observation: SafeObservation
) -> None:
    if (
        observation.case_id != str(view.case_id)
        or observation.case_revision != view.pins.case_revision
        or observation.constraint_set_revision != view.pins.constraint_set_revision
    ):
        raise ObservationMismatchError("observation does not match the view pins")


def trained_view(view: FastModelView, observation: SafeObservation) -> FastModelView:
    check_observation_matches(view, observation)
    latest = view.latest_provider_event
    if latest is None:
        raise TrainedViewError("no_provider_event")
    event = latest.model_copy(update={"content": observation_content(observation)})
    recent = tuple(
        event if item.event_id == latest.event_id else item
        for item in view.recent_events
    )
    data = view.model_dump(mode="python")
    data["latest_provider_event"] = event.model_dump(mode="python")
    data["recent_events"] = tuple(item.model_dump(mode="python") for item in recent)
    try:
        return FastModelView.model_validate(data)
    except ValidationError as error:
        raise TrainedViewError("trained_view_invalid") from error


__all__ = [
    "TRAINED_VIEW_VERSION",
    "ObservationMismatchError",
    "TrainedViewError",
    "check_observation_matches",
    "observation_content",
    "trained_view",
]
