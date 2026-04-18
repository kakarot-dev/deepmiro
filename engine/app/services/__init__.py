"""
Business service layer exports.

Lifecycle state machine lives in `.lifecycle`. Import `SimState`,
`store`, `bus`, `SimSnapshot` from there — not from simulation_manager
or simulation_runner.
"""

from .entity_reader import EntityNode, EntityReader, FilteredEntities
from .graph_builder import GraphBuilderService
from .graph_memory_updater import AgentActivity, GraphMemoryManager, GraphMemoryUpdater
from .graph_tools import GraphToolsService
from .lifecycle import (
    Event,
    EventBus,
    InvalidTransition,
    LifecycleStore,
    SimSnapshot,
    SimState,
    assert_transition,
    bus,
    is_terminal,
    store,
)
from .oasis_profile_generator import OasisAgentProfile, OasisProfileGenerator
from .ontology_generator import OntologyGenerator
from .simulation_config_generator import (
    AgentActivityConfig,
    EventConfig,
    PlatformConfig,
    SimulationConfigGenerator,
    SimulationParameters,
    TimeSimulationConfig,
)
from .simulation_ipc import (
    CommandStatus,
    CommandType,
    IPCCommand,
    IPCResponse,
    SimulationIPCClient,
    SimulationIPCServer,
)
from .simulation_manager import SimulationManager
from .simulation_runner import SimulationRunner
from .text_processor import TextProcessor

__all__ = [
    # Graph / entities
    "OntologyGenerator",
    "GraphBuilderService",
    "TextProcessor",
    "EntityReader",
    "EntityNode",
    "FilteredEntities",
    "GraphToolsService",
    "GraphMemoryUpdater",
    "GraphMemoryManager",
    "AgentActivity",
    # Profiles + config
    "OasisProfileGenerator",
    "OasisAgentProfile",
    "SimulationConfigGenerator",
    "SimulationParameters",
    "AgentActivityConfig",
    "TimeSimulationConfig",
    "EventConfig",
    "PlatformConfig",
    # Runner + manager
    "SimulationManager",
    "SimulationRunner",
    # Lifecycle (state machine)
    "SimState",
    "SimSnapshot",
    "LifecycleStore",
    "store",
    "EventBus",
    "Event",
    "bus",
    "InvalidTransition",
    "assert_transition",
    "is_terminal",
    # IPC
    "SimulationIPCClient",
    "SimulationIPCServer",
    "IPCCommand",
    "IPCResponse",
    "CommandType",
    "CommandStatus",
]
