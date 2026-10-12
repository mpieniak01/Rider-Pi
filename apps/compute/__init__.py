"""Lightweight, goal-owned transport to the selected remote inference executor."""

from .client import ComputeClient, ComputeError

__all__ = ["ComputeClient", "ComputeError"]
