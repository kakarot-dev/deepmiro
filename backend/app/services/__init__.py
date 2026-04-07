"""
业务服务模块
"""

from .ontology_generator import OntologyGenerator
from .graph_builder import GraphBuilderService
from .text_processor import TextProcessor

# New storage-backed names
from .entity_reader import EntityReader, EntityNode, FilteredEntities
from .graph_tools import GraphToolsService
from .graph_memory_updater import GraphMemoryUpdater, GraphMemoryManager, AgentActivity

# Backward-compatible Zep-prefixed aliases
from .entity_reader import EntityReader
from .graph_memory_updater import GraphMemoryUpdater, GraphMemoryManager
from .graph_tools import GraphToolsService

from .oasis_profile_generator import OasisProfileGenerator, OasisAgentProfile
from .simulation_manager import SimulationManager, SimulationState, SimulationStatus
from .simulation_config_generator import (
    SimulationConfigGenerator,
    SimulationParameters,
    AgentActivityConfig,
    TimeSimulationConfig,
    EventConfig,
    PlatformConfig
)
from .simulation_runner import (
    SimulationRunner,
    SimulationRunState,
    RunnerStatus,
    AgentAction,
    RoundSummary
)
from .simulation_ipc import (
    SimulationIPCClient,
    SimulationIPCServer,
    IPCCommand,
    IPCResponse,
    CommandType,
    CommandStatus
)

__all__ = [
    'OntologyGenerator',
    'GraphBuilderService',
    'TextProcessor',
    # New names
    'EntityReader',
    'GraphToolsService',
    'GraphMemoryUpdater',
    'GraphMemoryManager',
    # Legacy aliases
    'EntityReader',
    'GraphToolsService',
    'GraphMemoryUpdater',
    'GraphMemoryManager',
    # Shared
    'EntityNode',
    'FilteredEntities',
    'AgentActivity',
    'OasisProfileGenerator',
    'OasisAgentProfile',
    'SimulationManager',
    'SimulationState',
    'SimulationStatus',
    'SimulationConfigGenerator',
    'SimulationParameters',
    'AgentActivityConfig',
    'TimeSimulationConfig',
    'EventConfig',
    'PlatformConfig',
    'SimulationRunner',
    'SimulationRunState',
    'RunnerStatus',
    'AgentAction',
    'RoundSummary',
    'SimulationIPCClient',
    'SimulationIPCServer',
    'IPCCommand',
    'IPCResponse',
    'CommandType',
    'CommandStatus',
]
