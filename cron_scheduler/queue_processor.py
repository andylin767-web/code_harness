"""Compatibility import for the processor's former cron-specific location."""

from code_harness.events.processor import QueueProcessor

__all__ = ["QueueProcessor"]
