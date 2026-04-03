"""
SurrealSearchService -- hybrid search (vector + BM25) over SurrealDB graph data.

Scoring: 0.7 * vector_score + 0.3 * keyword_score.

Uses SurrealDB's native HNSW vector index and full-text BM25 index.
Results from both channels are merged via weighted scoring in Python.
"""

import logging
from typing import List, Dict, Any

from surrealdb import Surreal

from .embedding_service import EmbeddingService

logger = logging.getLogger("mirofish.search")


class SurrealSearchService:
    """Hybrid search combining vector similarity and BM25 keyword matching."""

    VECTOR_WEIGHT = 0.7
    KEYWORD_WEIGHT = 0.3

    def __init__(self, db: Surreal, embedding_service: EmbeddingService):
        self._db = db
        self._embedding = embedding_service

    # ----------------------------------------------------------------
    # Public API
    # ----------------------------------------------------------------

    def search_edges(
        self,
        graph_id: str,
        query: str,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Search edges (facts/relations) using hybrid scoring.

        Returns list of dicts with edge properties + 'score'.
        """
        query_vector = self._embedding.embed(query)

        vector_results = self._edge_vector_search(
            graph_id, query_vector, limit * 2
        )
        keyword_results = self._edge_keyword_search(
            graph_id, query, limit * 2
        )

        return self._merge_results(
            vector_results, keyword_results, limit=limit
        )

    def search_nodes(
        self,
        graph_id: str,
        query: str,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Search nodes (entities) using hybrid scoring.

        Returns list of dicts with node properties + 'score'.
        """
        query_vector = self._embedding.embed(query)

        vector_results = self._node_vector_search(
            graph_id, query_vector, limit * 2
        )
        keyword_results = self._node_keyword_search(
            graph_id, query, limit * 2
        )

        return self._merge_results(
            vector_results, keyword_results, limit=limit
        )

    # ----------------------------------------------------------------
    # Edge search internals
    # ----------------------------------------------------------------

    def _edge_vector_search(
        self,
        graph_id: str,
        query_vector: List[float],
        limit: int,
    ) -> List[Dict[str, Any]]:
        """Vector similarity search on relation fact_embedding (HNSW)."""
        try:
            result = self._db.query(
                f"""
                SELECT *,
                       in AS source_id,
                       out AS target_id,
                       vector::similarity::cosine(fact_embedding, $qvec) AS _score
                FROM relation
                WHERE graph_id = $gid
                    AND fact_embedding <|{limit}|> $qvec;
                """,
                {
                    "gid": graph_id,
                    "qvec": query_vector,
                },
            )
            return self._extract_rows(result)
        except Exception as exc:
            logger.warning(
                "Vector edge search failed (index may not exist yet): %s", exc
            )
            return []

    def _edge_keyword_search(
        self,
        graph_id: str,
        query: str,
        limit: int,
    ) -> List[Dict[str, Any]]:
        """BM25 full-text search on relation fact + name."""
        try:
            result = self._db.query(
                """
                SELECT *,
                       in AS source_id,
                       out AS target_id,
                       search::score(1) AS _score
                FROM relation
                WHERE graph_id = $gid
                    AND (fact @1@ $qtext OR name @1@ $qtext)
                ORDER BY _score DESC
                LIMIT $limit;
                """,
                {
                    "gid": graph_id,
                    "qtext": query,
                    "limit": limit,
                },
            )
            return self._extract_rows(result)
        except Exception as exc:
            logger.warning("Keyword edge search failed: %s", exc)
            return []

    # ----------------------------------------------------------------
    # Node search internals
    # ----------------------------------------------------------------

    def _node_vector_search(
        self,
        graph_id: str,
        query_vector: List[float],
        limit: int,
    ) -> List[Dict[str, Any]]:
        """Vector similarity search on entity embedding (HNSW)."""
        try:
            result = self._db.query(
                f"""
                SELECT *,
                       vector::similarity::cosine(embedding, $qvec) AS _score
                FROM entity
                WHERE graph_id = $gid
                    AND embedding <|{limit}|> $qvec;
                """,
                {
                    "gid": graph_id,
                    "qvec": query_vector,
                },
            )
            return self._extract_rows(result)
        except Exception as exc:
            logger.warning("Vector node search failed: %s", exc)
            return []

    def _node_keyword_search(
        self,
        graph_id: str,
        query: str,
        limit: int,
    ) -> List[Dict[str, Any]]:
        """BM25 full-text search on entity name + summary."""
        try:
            result = self._db.query(
                """
                SELECT *,
                       search::score(1) AS _score
                FROM entity
                WHERE graph_id = $gid
                    AND (name @1@ $qtext OR summary @1@ $qtext)
                ORDER BY _score DESC
                LIMIT $limit;
                """,
                {
                    "gid": graph_id,
                    "qtext": query,
                    "limit": limit,
                },
            )
            return self._extract_rows(result)
        except Exception as exc:
            logger.warning("Keyword node search failed: %s", exc)
            return []

    # ----------------------------------------------------------------
    # Result processing
    # ----------------------------------------------------------------

    @staticmethod
    def _extract_rows(result: list) -> List[Dict[str, Any]]:
        """Safely extract rows from a SurrealDB query response."""
        if not result:
            return []
        item = result[0]
        if isinstance(item, dict):
            return item.get("result", []) or []
        if isinstance(item, list):
            return item
        return []

    def _merge_results(
        self,
        vector_results: List[Dict[str, Any]],
        keyword_results: List[Dict[str, Any]],
        limit: int,
    ) -> List[Dict[str, Any]]:
        """
        Merge vector and keyword results with weighted scoring.

        Normalizes scores to [0, 1] range before combining:
            combined = VECTOR_WEIGHT * norm_vec + KEYWORD_WEIGHT * norm_kw
        """
        # Normalize vector scores
        v_max = (
            max((r.get("_score", 0) for r in vector_results), default=1.0)
            or 1.0
        )
        v_scores: Dict[str, float] = {}
        items: Dict[str, Dict[str, Any]] = {}
        for row in vector_results:
            rid = str(row.get("id", ""))
            v_scores[rid] = row.get("_score", 0) / v_max
            items[rid] = row

        # Normalize keyword scores
        k_max = (
            max((r.get("_score", 0) for r in keyword_results), default=1.0)
            or 1.0
        )
        k_scores: Dict[str, float] = {}
        for row in keyword_results:
            rid = str(row.get("id", ""))
            k_scores[rid] = row.get("_score", 0) / k_max
            if rid not in items:
                items[rid] = row

        # Combine
        scored: List[Dict[str, Any]] = []
        for rid, item in items.items():
            v = v_scores.get(rid, 0.0)
            k = k_scores.get(rid, 0.0)
            combined = self.VECTOR_WEIGHT * v + self.KEYWORD_WEIGHT * k

            # Strip internal fields before returning
            clean = {
                key: val
                for key, val in item.items()
                if key not in ("_score", "embedding", "fact_embedding")
            }
            clean["score"] = combined
            scored.append(clean)

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:limit]
