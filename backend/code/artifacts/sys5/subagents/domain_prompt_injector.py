"""Pure Python -- no LLM call. Loads the domain snippet already read by
config_loader and logs what will be injected into the generation/verification
system prompts."""

from __future__ import annotations

from config_loader import RunConfig
from logging_setup import get_logger, stage

log = get_logger("domain_prompt_injector")


def run(config: RunConfig) -> str:
    with stage(log, "domain_prompt_injector", domain=config.domain):
        text = config.domain_prompt_text
        if not text:
            log.warning("No domain prompt text available for domain=%s -- generation proceeds without domain guidance", config.domain)
        else:
            log.info("Domain prompt for '%s' ready (%d chars)", config.domain, len(text))
        return text
