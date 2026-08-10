"""Project profile registry."""

from __future__ import annotations

import logging

from ..utils.text import normalize
from .base import ProjectProfile, RequirementIdPolicy
from .tmhc import TMHC_PROFILE

logger = logging.getLogger(__name__)

GENERIC_PROFILE = ProjectProfile()

_PROFILES: dict[str, ProjectProfile] = {
    "tmhc": TMHC_PROFILE,
    "generic": GENERIC_PROFILE,
}


def register(profile: ProjectProfile) -> ProjectProfile:
    """Register a profile under its name."""
    _PROFILES[normalize(profile.name)] = profile
    return profile


def available() -> list[str]:
    return sorted(_PROFILES)


def resolve(*candidates: str) -> ProjectProfile:
    """First profile matching any candidate hint, else the generic profile.

    Candidates are tried in order — an explicit ``project_profile`` setting first, then
    softer hints like the project name — so ``project_name="tmhc_demo"`` still lands on
    the TMHC profile without the caller having to spell it out.
    """
    for candidate in candidates:
        key = normalize(candidate)
        if not key:
            continue
        if key in _PROFILES:
            return _PROFILES[key]
        for name, profile in _PROFILES.items():
            if name != "generic" and name in key:
                logger.info("[sys5] project profile %r matched from hint %r", profile.name, candidate)
                return profile

    logger.info("[sys5] no project profile matched %s; using generic", list(candidates))
    return GENERIC_PROFILE


__all__ = [
    "GENERIC_PROFILE",
    "TMHC_PROFILE",
    "ProjectProfile",
    "RequirementIdPolicy",
    "available",
    "register",
    "resolve",
]
