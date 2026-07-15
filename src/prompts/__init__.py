"""Prompt modules for LLM-driven features.

Edit education/jobs opportunity copy in the dedicated modules under this package.
"""

from src.prompts.opportunities import PromptPair, build_opportunity_prompts

__all__ = ["PromptPair", "build_opportunity_prompts"]
