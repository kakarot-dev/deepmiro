# SPDX-License-Identifier: AGPL-3.0-only
# Copyright 2026 kakarot-dev
"""
MiroFish Zep-to-SurrealDB Patch

Replaces the `zep_cloud` Python module with our SurrealDB-backed shim.
Drop-in replacement — no MiroFish source changes needed.

Usage:
    import surrealdb_adapter.patch_mirofish
"""

import sys
import os
import types
import logging
from dataclasses import dataclass

logger = logging.getLogger("mirofish.surreal_patch")


def apply_patch():
    """Replace zep_cloud module with SurrealDB shim."""
    from .zep_shim import ZepSurrealShim

    # Create fake zep_cloud module hierarchy
    zep_cloud = types.ModuleType("zep_cloud")
    zep_cloud_client = types.ModuleType("zep_cloud.client")

    zep_cloud_client.Zep = ZepSurrealShim
    zep_cloud.client = zep_cloud_client

    @dataclass
    class EpisodeData:
        data: str = ""
        text: str = ""
        source: str = "text"
        source_description: str = ""

        def __init__(self, data: str = "", text: str = "", **kwargs):
            self.data = data or text
            self.text = text or data
            for k, v in kwargs.items():
                setattr(self, k, v)

    @dataclass
    class EntityEdgeSourceTarget:
        source: str = ""
        target: str = ""

    zep_cloud.EpisodeData = EpisodeData
    zep_cloud.EntityEdgeSourceTarget = EntityEdgeSourceTarget

    class InternalServerError(Exception):
        pass

    zep_cloud.InternalServerError = InternalServerError

    # Mock external_clients.ontology — must be Pydantic BaseModel
    # because graph_builder.py uses type(name, (EntityModel,), attrs)
    # with pydantic.Field()
    zep_cloud_ontology = types.ModuleType("zep_cloud.external_clients.ontology")

    try:
        from pydantic import BaseModel as _BaseModel

        class EntityModel(_BaseModel):
            name: str = ""
            description: str = ""
            class Config:
                extra = "allow"

        class EntityText(_BaseModel):
            text: str = ""
            class Config:
                extra = "allow"

        class EdgeModel(_BaseModel):
            name: str = ""
            description: str = ""
            source_entity: str = ""
            target_entity: str = ""
            class Config:
                extra = "allow"
    except ImportError:
        # Fallback to dataclass if pydantic not available
        @dataclass
        class EntityModel:
            name: str = ""
            description: str = ""

        @dataclass
        class EntityText:
            text: str = ""

        @dataclass
        class EdgeModel:
            name: str = ""
            description: str = ""
            source_entity: str = ""
            target_entity: str = ""

    zep_cloud_ontology.EntityModel = EntityModel
    zep_cloud_ontology.EntityText = EntityText
    zep_cloud_ontology.EdgeModel = EdgeModel

    zep_cloud_external = types.ModuleType("zep_cloud.external_clients")
    zep_cloud_external.ontology = zep_cloud_ontology
    zep_cloud.external_clients = zep_cloud_external

    sys.modules["zep_cloud"] = zep_cloud
    sys.modules["zep_cloud.client"] = zep_cloud_client
    sys.modules["zep_cloud.external_clients"] = zep_cloud_external
    sys.modules["zep_cloud.external_clients.ontology"] = zep_cloud_ontology

    logger.info("Zep Cloud patched → SurrealDB adapter active")


if os.environ.get("USE_SURREALDB", "").lower() == "true":
    apply_patch()
