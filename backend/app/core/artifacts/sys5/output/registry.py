"""Output-template registry with fail-fast resolution.

The template is chosen *before* the graph runs. An unknown name must abort in
milliseconds with the list of what is available, rather than after a full generation
pass has already been paid for.
"""

from __future__ import annotations

import logging
from importlib import import_module

from ..utils.text import normalize
from .base import OutputTemplate

logger = logging.getLogger(__name__)

_TEMPLATES: dict[str, OutputTemplate] = {}

#: Template packages imported on first resolution, relative to this package (so this
#: keeps working no matter where the `sys5` package itself is mounted on disk).
_BUILTIN_MODULES = (".templates.tmhc_v1",)

_loaded = False


class UnknownTemplateError(ValueError):
    """Raised when a requested output template is not registered."""


def register(template: OutputTemplate) -> OutputTemplate:
    """Register a template under its name."""
    key = normalize(template.name)
    if not key:
        raise ValueError("an output template must declare a name")
    if key in _TEMPLATES and _TEMPLATES[key] is not template:
        logger.warning("[sys5] output template %r re-registered", template.name)
    _TEMPLATES[key] = template
    return template


def _load_builtins() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    for module in _BUILTIN_MODULES:
        try:
            import_module(module, package=__package__)
        except Exception as exc:  # noqa: BLE001 - a broken template must be reported, not hidden
            logger.error("[sys5] could not load output template module %s: %s", module, exc)


def available() -> list[str]:
    """Names of every registered template."""
    _load_builtins()
    return sorted(t.name for t in _TEMPLATES.values())


def resolve(name: str) -> OutputTemplate:
    """The template called ``name``.

    Raises :class:`UnknownTemplateError` — with the available names — rather than
    silently falling back, because rendering into the wrong layout is worse than not
    rendering at all.
    """
    _load_builtins()
    key = normalize(name)
    template = _TEMPLATES.get(key)
    if template is None:
        raise UnknownTemplateError(
            f"unknown output template {name!r}. Available: {', '.join(available()) or 'none'}. "
            "Set it with the `output_template` config key or SYS5_OUTPUT_TEMPLATE."
        )
    return template
