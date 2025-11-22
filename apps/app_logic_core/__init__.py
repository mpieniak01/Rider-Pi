#!/usr/bin/env python3
"""
Warstwa App Logic Core – cienki adaptor na FeatureManager/FeatureDefinition.
Cel: wyraźnie oddzielić logikę aplikacyjną (app) od warstw services/api.
"""

from services.core.features import DEFAULT_REGISTRY, FeatureDefinition, FeatureManager, NullPublisher

__all__ = ["FeatureDefinition", "FeatureManager", "NullPublisher", "DEFAULT_REGISTRY"]
