"""
SurrealDB schema definitions as SurrealQL strings.

All DEFINE statements are idempotent -- re-running is safe.
The Python adapter executes these on startup via ``_ensure_schema()``.
"""

# ---------------------------------------------------------------------------
# Graph metadata table
# ---------------------------------------------------------------------------

SCHEMA_GRAPH = """
DEFINE TABLE graph SCHEMAFULL;

DEFINE FIELD graph_id     ON graph TYPE string   ASSERT $value != NONE;
DEFINE FIELD name         ON graph TYPE string   ASSERT $value != NONE;
DEFINE FIELD description  ON graph TYPE string   DEFAULT "";
DEFINE FIELD ontology_json ON graph TYPE string  DEFAULT "{}";
DEFINE FIELD created_at   ON graph TYPE datetime DEFAULT time::now();

DEFINE INDEX idx_graph_id ON graph FIELDS graph_id UNIQUE;
"""

# ---------------------------------------------------------------------------
# Entity table (graph nodes)
# ---------------------------------------------------------------------------

SCHEMA_ENTITY = """
DEFINE TABLE entity SCHEMAFULL;

DEFINE FIELD graph_id        ON entity TYPE string    ASSERT $value != NONE;
DEFINE FIELD name            ON entity TYPE string    ASSERT $value != NONE;
DEFINE FIELD name_lower      ON entity TYPE string    ASSERT $value != NONE;
DEFINE FIELD entity_type     ON entity TYPE string    DEFAULT "Entity";
DEFINE FIELD summary         ON entity TYPE string    DEFAULT "";
DEFINE FIELD attributes_json ON entity TYPE string    DEFAULT "{}";
DEFINE FIELD embedding       ON entity TYPE array<float> DEFAULT [];
DEFINE FIELD created_at      ON entity TYPE datetime  DEFAULT time::now();

DEFINE INDEX idx_entity_graph    ON entity FIELDS graph_id;
DEFINE INDEX idx_entity_type     ON entity FIELDS graph_id, entity_type;
DEFINE INDEX idx_entity_name     ON entity FIELDS graph_id, name_lower UNIQUE;

DEFINE ANALYZER entity_analyzer TOKENIZERS blank, class FILTERS lowercase, ascii, snowball(english);
DEFINE INDEX idx_entity_ft ON entity FIELDS name, summary
    SEARCH ANALYZER entity_analyzer BM25;

DEFINE INDEX idx_entity_vec ON entity FIELDS embedding
    HNSW DIMENSION 768
    DIST COSINE
    TYPE F32
    EFC 150
    M 12;
"""

# ---------------------------------------------------------------------------
# Relation table (graph edges)
# ---------------------------------------------------------------------------

SCHEMA_RELATION = """
DEFINE TABLE relation SCHEMAFULL;

DEFINE FIELD graph_id        ON relation TYPE string    ASSERT $value != NONE;
DEFINE FIELD name            ON relation TYPE string    DEFAULT "";
DEFINE FIELD fact            ON relation TYPE string    DEFAULT "";
DEFINE FIELD fact_embedding  ON relation TYPE array<float> DEFAULT [];
DEFINE FIELD attributes_json ON relation TYPE string    DEFAULT "{}";
DEFINE FIELD episode_ids     ON relation TYPE array<string> DEFAULT [];
DEFINE FIELD weight          ON relation TYPE float     DEFAULT 1.0;
DEFINE FIELD created_at      ON relation TYPE datetime  DEFAULT time::now();
DEFINE FIELD valid_at        ON relation TYPE option<datetime>;
DEFINE FIELD invalid_at      ON relation TYPE option<datetime>;
DEFINE FIELD expired_at      ON relation TYPE option<datetime>;

DEFINE INDEX idx_relation_graph ON relation FIELDS graph_id;

DEFINE ANALYZER relation_analyzer TOKENIZERS blank, class FILTERS lowercase, ascii, snowball(english);
DEFINE INDEX idx_relation_ft ON relation FIELDS fact, name
    SEARCH ANALYZER relation_analyzer BM25;

DEFINE INDEX idx_relation_vec ON relation FIELDS fact_embedding
    HNSW DIMENSION 768
    DIST COSINE
    TYPE F32
    EFC 150
    M 12;
"""

# ---------------------------------------------------------------------------
# Episode table (text chunks)
# ---------------------------------------------------------------------------

SCHEMA_EPISODE = """
DEFINE TABLE episode SCHEMAFULL;

DEFINE FIELD graph_id    ON episode TYPE string   ASSERT $value != NONE;
DEFINE FIELD data        ON episode TYPE string   DEFAULT "";
DEFINE FIELD processed   ON episode TYPE bool     DEFAULT true;
DEFINE FIELD created_at  ON episode TYPE datetime DEFAULT time::now();

DEFINE INDEX idx_episode_graph ON episode FIELDS graph_id;
"""

# ---------------------------------------------------------------------------
# Agent table (AVM -- Agent Virtual Memory)
# ---------------------------------------------------------------------------

SCHEMA_AGENT = """
DEFINE TABLE agent SCHEMAFULL;

DEFINE FIELD simulation_id   ON agent TYPE string    ASSERT $value != NONE;
DEFINE FIELD graph_id        ON agent TYPE string    ASSERT $value != NONE;
DEFINE FIELD agent_id        ON agent TYPE int       ASSERT $value != NONE;
DEFINE FIELD user_name       ON agent TYPE string    DEFAULT "";
DEFINE FIELD name            ON agent TYPE string    DEFAULT "";
DEFINE FIELD bio             ON agent TYPE string    DEFAULT "";
DEFINE FIELD persona         ON agent TYPE string    DEFAULT "";
DEFINE FIELD persona_embedding ON agent TYPE array<float> DEFAULT [];

DEFINE FIELD age             ON agent TYPE option<int>;
DEFINE FIELD gender          ON agent TYPE option<string>;
DEFINE FIELD mbti            ON agent TYPE option<string>;
DEFINE FIELD country         ON agent TYPE option<string>;
DEFINE FIELD profession      ON agent TYPE option<string>;
DEFINE FIELD interested_topics ON agent TYPE array<string> DEFAULT [];

DEFINE FIELD karma           ON agent TYPE int       DEFAULT 1000;
DEFINE FIELD friend_count    ON agent TYPE int       DEFAULT 100;
DEFINE FIELD follower_count  ON agent TYPE int       DEFAULT 150;
DEFINE FIELD statuses_count  ON agent TYPE int       DEFAULT 500;

DEFINE FIELD active          ON agent TYPE bool      DEFAULT true;
DEFINE FIELD mood            ON agent TYPE string    DEFAULT "neutral";
DEFINE FIELD memory_summary  ON agent TYPE string    DEFAULT "";

DEFINE FIELD source_entity_uuid ON agent TYPE option<string>;
DEFINE FIELD source_entity_type ON agent TYPE option<string>;
DEFINE FIELD created_at      ON agent TYPE datetime  DEFAULT time::now();
DEFINE FIELD updated_at      ON agent TYPE datetime  DEFAULT time::now();

DEFINE INDEX idx_agent_sim       ON agent FIELDS simulation_id;
DEFINE INDEX idx_agent_graph     ON agent FIELDS graph_id;
DEFINE INDEX idx_agent_active    ON agent FIELDS simulation_id, active;
DEFINE INDEX idx_agent_sim_id    ON agent FIELDS simulation_id, agent_id UNIQUE;

DEFINE INDEX idx_agent_persona_vec ON agent FIELDS persona_embedding
    HNSW DIMENSION 768
    DIST COSINE
    TYPE F32
    EFC 150
    M 12;
"""

# ---------------------------------------------------------------------------
# Simulation action table
# ---------------------------------------------------------------------------

SCHEMA_SIMULATION_ACTION = """
DEFINE TABLE simulation_action SCHEMAFULL;

DEFINE FIELD simulation_id ON simulation_action TYPE string    ASSERT $value != NONE;
DEFINE FIELD round_num     ON simulation_action TYPE int       DEFAULT 0;
DEFINE FIELD timestamp     ON simulation_action TYPE datetime  DEFAULT time::now();
DEFINE FIELD platform      ON simulation_action TYPE string    DEFAULT "twitter";
DEFINE FIELD agent_id      ON simulation_action TYPE int       ASSERT $value != NONE;
DEFINE FIELD agent_name    ON simulation_action TYPE string    DEFAULT "";
DEFINE FIELD action_type   ON simulation_action TYPE string    ASSERT $value != NONE;
DEFINE FIELD action_args   ON simulation_action TYPE object    DEFAULT {};
DEFINE FIELD result        ON simulation_action TYPE option<string>;
DEFINE FIELD success       ON simulation_action TYPE bool      DEFAULT true;

DEFINE INDEX idx_action_sim      ON simulation_action FIELDS simulation_id;
DEFINE INDEX idx_action_round    ON simulation_action FIELDS simulation_id, round_num;
DEFINE INDEX idx_action_agent    ON simulation_action FIELDS simulation_id, agent_id;
DEFINE INDEX idx_action_type     ON simulation_action FIELDS simulation_id, action_type;
DEFINE INDEX idx_action_platform ON simulation_action FIELDS simulation_id, platform;
"""

# ---------------------------------------------------------------------------
# Ontology table
# ---------------------------------------------------------------------------

SCHEMA_ONTOLOGY = """
DEFINE TABLE ontology SCHEMAFULL;

DEFINE FIELD graph_id     ON ontology TYPE string   ASSERT $value != NONE;
DEFINE FIELD entity_types ON ontology TYPE array<object> DEFAULT [];
DEFINE FIELD relation_types ON ontology TYPE array<object> DEFAULT [];
DEFINE FIELD raw_json     ON ontology TYPE string   DEFAULT "{}";
DEFINE FIELD created_at   ON ontology TYPE datetime DEFAULT time::now();
DEFINE FIELD updated_at   ON ontology TYPE datetime DEFAULT time::now();

DEFINE INDEX idx_ontology_graph ON ontology FIELDS graph_id UNIQUE;
"""


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

ALL_SCHEMAS = [
    SCHEMA_GRAPH,
    SCHEMA_ENTITY,
    SCHEMA_RELATION,
    SCHEMA_EPISODE,
    SCHEMA_AGENT,
    SCHEMA_SIMULATION_ACTION,
    SCHEMA_ONTOLOGY,
]


def get_all_schema_queries() -> list[str]:
    """Return all schema definition strings, split into individual statements.

    Each returned string is a single SurrealQL statement suitable for
    passing to ``db.query()``.
    """
    statements: list[str] = []
    for schema_block in ALL_SCHEMAS:
        for line in schema_block.strip().splitlines():
            line = line.strip()
            # Skip empty lines and comments
            if not line or line.startswith("--"):
                continue
            # Accumulate multi-line statements (ending with ;)
            if statements and not statements[-1].endswith(";"):
                statements[-1] += " " + line
            else:
                statements.append(line)
    # Clean up: remove trailing semicolons for SurrealDB SDK
    return [s.rstrip(";").strip() for s in statements if s.strip()]
