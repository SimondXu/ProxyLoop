"""Deterministic fictional Provider simulator interface."""

from proxyloop_telecom_domain import ApprovalExpiredError

from .episode import EpisodeResult, Phase01AEpisode, run_success_episode
from .leakage import PrivateTokens, leaked_private_values, private_tokens
from .multi_turn import (
    MultiTurnEnvironmentState,
    MultiTurnEvent,
    MultiTurnProviderEnvironment,
    MultiTurnProviderTurn,
    MultiTurnTransition,
    Phase03A1Manifest,
    Phase03A1ScenarioAssignment,
    Phase03A1Split,
    SimulatorCapabilityAttempt,
    generate_phase03a1_manifest,
)
from .provider import IllegalOfferTransitionError, OfferState

__all__ = [
    "ApprovalExpiredError",
    "EpisodeResult",
    "IllegalOfferTransitionError",
    "MultiTurnEnvironmentState",
    "MultiTurnEvent",
    "MultiTurnProviderEnvironment",
    "MultiTurnProviderTurn",
    "MultiTurnTransition",
    "OfferState",
    "Phase01AEpisode",
    "Phase03A1Manifest",
    "Phase03A1ScenarioAssignment",
    "Phase03A1Split",
    "PrivateTokens",
    "SimulatorCapabilityAttempt",
    "generate_phase03a1_manifest",
    "leaked_private_values",
    "private_tokens",
    "run_success_episode",
]
