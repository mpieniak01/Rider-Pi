"""Compatibility metadata exports derived exclusively from the Pi catalog."""

from __future__ import annotations

from typing import TypedDict

from common.service_catalog import UNIT_CATALOG


class ServiceMeta(TypedDict, total=False):
    id: str
    group: str
    label: str
    description: str
    edges_out: list[str]
    can_move: bool
    lifecycle: str
    resources: list[str]


SERVICE_META = {unit: dict(meta) for unit, meta in UNIT_CATALOG.items()}
SERVICE_IDS_BY_UNIT = {unit: meta["id"] for unit, meta in SERVICE_META.items()}
UNIT_BY_ID = {meta["id"]: unit for unit, meta in SERVICE_META.items()}

__all__ = ["SERVICE_META", "SERVICE_IDS_BY_UNIT", "UNIT_BY_ID", "ServiceMeta"]
