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
DEFINE TABLE relation TYPE RELATION SCHEMAFULL;

DEFINE FIELD in              ON relation TYPE record<entity>;
DEFINE FIELD out             ON relation TYPE record<entity>;
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
# Simulation table (replaces state.json)
# ---------------------------------------------------------------------------

SCHEMA_SIMULATION = """
DEFINE TABLE simulation SCHEMAFULL;

DEFINE FIELD simulation_id   ON simulation TYPE string   ASSERT $value != NONE;
DEFINE FIELD project_id      ON simulation TYPE string   DEFAULT "";
DEFINE FIELD graph_id        ON simulation TYPE string   DEFAULT "";
DEFINE FIELD status          ON simulation TYPE string   DEFAULT "created";
DEFINE FIELD enable_twitter  ON simulation TYPE bool     DEFAULT true;
DEFINE FIELD enable_reddit   ON simulation TYPE bool     DEFAULT true;
DEFINE FIELD entities_count  ON simulation TYPE int      DEFAULT 0;
DEFINE FIELD profiles_count  ON simulation TYPE int      DEFAULT 0;
DEFINE FIELD entity_types    ON simulation TYPE array<string> DEFAULT [];
DEFINE FIELD config_json     ON simulation TYPE string   DEFAULT "{}";
DEFINE FIELD error           ON simulation TYPE option<string>;
DEFINE FIELD user_id         ON simulation TYPE option<string>;
DEFINE FIELD created_at      ON simulation TYPE datetime DEFAULT time::now();
DEFINE FIELD updated_at      ON simulation TYPE datetime DEFAULT time::now();

DEFINE INDEX idx_simulation_id      ON simulation FIELDS simulation_id UNIQUE;
DEFINE INDEX idx_simulation_project ON simulation FIELDS project_id;
DEFINE INDEX idx_simulation_status  ON simulation FIELDS status;
DEFINE INDEX idx_simulation_user    ON simulation FIELDS user_id;
"""

# ---------------------------------------------------------------------------
# Simulation run table (replaces run_state.json)
# ---------------------------------------------------------------------------

SCHEMA_SIMULATION_RUN = """
DEFINE TABLE simulation_run SCHEMAFULL;

DEFINE FIELD simulation_id          ON simulation_run TYPE string  ASSERT $value != NONE;
DEFINE FIELD runner_status          ON simulation_run TYPE string  DEFAULT "idle";
DEFINE FIELD current_round          ON simulation_run TYPE int     DEFAULT 0;
DEFINE FIELD total_rounds           ON simulation_run TYPE int     DEFAULT 0;
DEFINE FIELD simulated_hours        ON simulation_run TYPE int     DEFAULT 0;
DEFINE FIELD total_simulation_hours ON simulation_run TYPE int     DEFAULT 0;
DEFINE FIELD twitter_current_round  ON simulation_run TYPE int     DEFAULT 0;
DEFINE FIELD reddit_current_round   ON simulation_run TYPE int     DEFAULT 0;
DEFINE FIELD twitter_simulated_hours ON simulation_run TYPE int    DEFAULT 0;
DEFINE FIELD reddit_simulated_hours ON simulation_run TYPE int     DEFAULT 0;
DEFINE FIELD twitter_running        ON simulation_run TYPE bool    DEFAULT false;
DEFINE FIELD reddit_running         ON simulation_run TYPE bool    DEFAULT false;
DEFINE FIELD twitter_actions_count  ON simulation_run TYPE int     DEFAULT 0;
DEFINE FIELD reddit_actions_count   ON simulation_run TYPE int     DEFAULT 0;
DEFINE FIELD twitter_completed      ON simulation_run TYPE bool    DEFAULT false;
DEFINE FIELD reddit_completed       ON simulation_run TYPE bool    DEFAULT false;
DEFINE FIELD process_pid            ON simulation_run TYPE option<int>;
DEFINE FIELD started_at             ON simulation_run TYPE option<datetime>;
DEFINE FIELD completed_at           ON simulation_run TYPE option<datetime>;
DEFINE FIELD error                  ON simulation_run TYPE option<string>;

DEFINE INDEX idx_run_sim_id ON simulation_run FIELDS simulation_id UNIQUE;
DEFINE INDEX idx_run_status ON simulation_run FIELDS runner_status;
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
# Agent chat memory table (AVM smart paging)
# ---------------------------------------------------------------------------

SCHEMA_AGENT_CHAT_MEMORY = """
DEFINE TABLE agent_chat_memory SCHEMAFULL;

DEFINE FIELD simulation_id ON agent_chat_memory TYPE string   ASSERT $value != NONE;
DEFINE FIELD agent_id      ON agent_chat_memory TYPE int      ASSERT $value != NONE;
DEFINE FIELD platform      ON agent_chat_memory TYPE string   DEFAULT "twitter";
DEFINE FIELD records_json  ON agent_chat_memory TYPE string   DEFAULT "[]";
DEFINE FIELD records_count ON agent_chat_memory TYPE int      DEFAULT 0;
DEFINE FIELD updated_at    ON agent_chat_memory TYPE datetime DEFAULT time::now();

DEFINE INDEX idx_acm_sim_agent ON agent_chat_memory FIELDS simulation_id, agent_id, platform UNIQUE;
"""

# ---------------------------------------------------------------------------
# Simulation post embeddings (vector feed for rec table)
# ---------------------------------------------------------------------------

SCHEMA_SIM_POST = """
DEFINE TABLE sim_post SCHEMAFULL;

DEFINE FIELD simulation_id ON sim_post TYPE string   ASSERT $value != NONE;
DEFINE FIELD platform      ON sim_post TYPE string   DEFAULT "twitter";
DEFINE FIELD post_id       ON sim_post TYPE int      ASSERT $value != NONE;
DEFINE FIELD user_id       ON sim_post TYPE int      DEFAULT 0;
DEFINE FIELD content       ON sim_post TYPE string   DEFAULT "";
DEFINE FIELD embedding     ON sim_post TYPE array<float> DEFAULT [];
DEFINE FIELD created_at    ON sim_post TYPE datetime DEFAULT time::now();

DEFINE INDEX idx_sp_sim ON sim_post FIELDS simulation_id, platform;
DEFINE INDEX idx_sp_post ON sim_post FIELDS simulation_id, platform, post_id UNIQUE;
DEFINE INDEX idx_sp_vec ON sim_post FIELDS embedding
    HNSW DIMENSION 768
    DIST COSINE
    TYPE F32
    EFC 150
    M 12;
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
    SCHEMA_SIMULATION,
    SCHEMA_SIMULATION_RUN,
    SCHEMA_ONTOLOGY,
    SCHEMA_AGENT_CHAT_MEMORY,
    SCHEMA_SIM_POST,
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
