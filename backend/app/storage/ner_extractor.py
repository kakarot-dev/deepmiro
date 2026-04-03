"""
NER/RE Extractor -- entity and relation extraction via LLM.

Uses the app's LLMClient with a structured prompt to extract
entities and relations from text chunks, guided by the graph's ontology.
"""

import logging
from typing import Dict, Any, List, Optional

from ..utils.llm_client import LLMClient

logger = logging.getLogger("mirofish.ner_extractor")

# System prompt template for NER/RE extraction
_SYSTEM_PROMPT = """You are a Named Entity Recognition and Relation Extraction system.
Given a text and an ontology (entity types + relation types), extract all entities and relations.

ONTOLOGY:
{ontology_description}

RULES:
1. Only extract entity types and relation types defined in the ontology.
2. Normalize entity names: strip whitespace, use canonical form (e.g., "Jack Ma" not "ma jack").
3. Each entity must have: name, type (from ontology), and optional attributes.
4. Each relation must have: source entity name, target entity name, type (from ontology), and a fact sentence describing the relationship.
5. If no entities or relations are found, return empty lists.
6. Be precise -- only extract what is explicitly stated or strongly implied in the text.
7. Merge co-references: "the company", "it", "the firm" all resolve to the canonical entity name.
8. Fact sentences should be self-contained and readable without the original text.

REJECTION RULES (critical):
9. REJECT fragments and descriptions as entity names. "NYU dropout", "the founder", \
"a large company", "CO" are NOT valid entity names. Entity names must be proper nouns \
or specific identifiers (e.g., "Shayne Coplan", "Polymarket", "CFTC").
10. REJECT abstract concepts and events as entities unless they match the ontology. \
"prediction markets", "US presidential election", "blockchain technology" are NOT entities \
unless the ontology explicitly defines them as a type.
11. When the same entity appears with a short name AND a full name (e.g., "Hanson" and \
"Robin Hanson"), use ONLY the full canonical name.
12. For the "summary" in attributes, extract a SHORT factual sentence from the text that \
describes what this entity IS or DOES. Not just "Name (Type)" -- e.g., \
"Polymarket is a prediction market platform founded in 2020" or \
"Shayne Coplan is the 26-year-old founder of Polymarket".

EXAMPLES:

Example input: "Tesla CEO Elon Musk announced plans to cut 10% of the workforce. The move was criticized by the United Auto Workers union."
Example output:
{{
  "entities": [
    {{"name": "Elon Musk", "type": "PublicFigure", "attributes": {{"role": "CEO"}}}},
    {{"name": "Tesla", "type": "Company", "attributes": {{"industry": "automotive"}}}},
    {{"name": "United Auto Workers", "type": "Organization", "attributes": {{"type": "labor union"}}}}
  ],
  "relations": [
    {{"source": "Elon Musk", "target": "Tesla", "type": "LEADS", "fact": "Elon Musk is the CEO of Tesla."}},
    {{"source": "Tesla", "target": "United Auto Workers", "type": "OPPOSES", "fact": "Tesla's plan to cut 10% of workforce was criticized by the United Auto Workers union."}}
  ]
}}

Return ONLY valid JSON in this exact format:
{{
  "entities": [
    {{"name": "...", "type": "...", "attributes": {{"key": "value"}}}}
  ],
  "relations": [
    {{"source": "...", "target": "...", "type": "...", "fact": "..."}}
  ]
}}"""

_USER_PROMPT = """Extract entities and relations from the following text:

{text}"""


class NERExtractor:
    """Extract entities and relations from text using an LLM."""

    def __init__(self, llm_client: Optional[LLMClient] = None, max_retries: int = 2):
        self.llm = llm_client or LLMClient()
        self.max_retries = max_retries

    def extract(self, text: str, ontology: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract entities and relations from text, guided by ontology.

        Args:
            text: Input text chunk
            ontology: Dict with 'entity_types' and 'relation_types' from graph

        Returns:
            Dict with 'entities' and 'relations' lists
        """
        if not text or not text.strip():
            return {"entities": [], "relations": []}

        ontology_desc = self._format_ontology(ontology)
        system_msg = _SYSTEM_PROMPT.format(ontology_description=ontology_desc)
        user_msg = _USER_PROMPT.format(text=text.strip())

        messages = [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ]

        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                result = self.llm.chat_json(
                    messages=messages,
                    temperature=0.1,  # Low temp for extraction precision
                    max_tokens=4096,
                )
                return self._validate_and_clean(result, ontology)

            except ValueError as e:
                last_error = e
                logger.warning(
                    f"NER extraction failed (attempt {attempt + 1}): invalid JSON -- {e}"
                )
            except Exception as e:
                last_error = e
                logger.error(f"NER extraction error: {e}")
                if attempt >= self.max_retries:
                    break

        logger.error(
            f"NER extraction failed after {self.max_retries + 1} attempts: {last_error}"
        )
        return {"entities": [], "relations": []}

    def _format_ontology(self, ontology: Dict[str, Any]) -> str:
        """Format ontology dict into readable text for the LLM prompt."""
        parts = []

        entity_types = ontology.get("entity_types", [])
        if entity_types:
            parts.append("Entity Types:")
            for et in entity_types:
                if isinstance(et, dict):
                    name = et.get("name", str(et))
                    desc = et.get("description", "")
                    attrs = et.get("attributes", [])
                    line = f"  - {name}"
                    if desc:
                        line += f": {desc}"
                    if attrs:
                        attr_names = [
                            a.get("name", str(a)) if isinstance(a, dict) else str(a)
                            for a in attrs
                        ]
                        line += f" (attributes: {', '.join(attr_names)})"
                    parts.append(line)
                else:
                    parts.append(f"  - {et}")

        relation_types = ontology.get("relation_types", ontology.get("edge_types", []))
        if relation_types:
            parts.append("\nRelation Types:")
            for rt in relation_types:
                if isinstance(rt, dict):
                    name = rt.get("name", str(rt))
                    desc = rt.get("description", "")
                    source_targets = rt.get("source_targets", [])
                    line = f"  - {name}"
                    if desc:
                        line += f": {desc}"
                    if source_targets:
                        st_strs = [
                            f"{st.get('source', '?')} -> {st.get('target', '?')}"
                            for st in source_targets
                        ]
                        line += f" ({', '.join(st_strs)})"
                    parts.append(line)
                else:
                    parts.append(f"  - {rt}")

        if not parts:
            parts.append(
                "No specific ontology defined. Extract all entities and relations you find."
            )

        return "\n".join(parts)

    def _validate_and_clean(
        self, result: Dict[str, Any], ontology: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Validate and normalize LLM output."""
        entities = result.get("entities", [])
        relations = result.get("relations", [])

        # Get valid type names from ontology
        valid_entity_types = set()
        for et in ontology.get("entity_types", []):
            if isinstance(et, dict):
                valid_entity_types.add(et.get("name", "").strip())
            else:
                valid_entity_types.add(str(et).strip())

        valid_relation_types = set()
        for rt in ontology.get("relation_types", ontology.get("edge_types", [])):
            if isinstance(rt, dict):
                valid_relation_types.add(rt.get("name", "").strip())
            else:
                valid_relation_types.add(str(rt).strip())

        # Clean entities
        cleaned_entities = []
        seen_names: set[str] = set()
        for entity in entities:
            if not isinstance(entity, dict):
                continue
            name = str(entity.get("name", "")).strip()
            etype = str(entity.get("type", "Entity")).strip()
            if not name:
                continue

            # Reject fragments
            name_lower = name.lower()
            if len(name) <= 2:
                continue
            if " " not in name and name_lower == name and len(name) < 5:
                continue
            _reject_prefixes = (
                "a ", "an ", "the ", "some ", "this ", "that ",
                "his ", "her ", "their ", "our ", "my ", "its ",
            )
            if any(name_lower.startswith(p) for p in _reject_prefixes):
                continue
            _reject_suffixes = (
                " dropout", " founder", " user", " trader", " official",
            )
            if any(name_lower.endswith(s) for s in _reject_suffixes):
                continue

            # Deduplicate
            if name_lower in seen_names:
                continue
            seen_names.add(name_lower)

            cleaned_entities.append(
                {
                    "name": name,
                    "type": etype,
                    "attributes": entity.get("attributes", {}),
                }
            )

        # Clean relations
        cleaned_relations = []
        entity_names_lower = {e["name"].lower() for e in cleaned_entities}
        for relation in relations:
            if not isinstance(relation, dict):
                continue
            source = str(relation.get("source", "")).strip()
            target = str(relation.get("target", "")).strip()
            rtype = str(relation.get("type", "RELATED_TO")).strip()
            fact = str(relation.get("fact", "")).strip()

            if not source or not target:
                continue

            # Ensure source and target entities exist
            if source.lower() not in entity_names_lower:
                cleaned_entities.append({"name": source, "type": "Entity", "attributes": {}})
                entity_names_lower.add(source.lower())
            if target.lower() not in entity_names_lower:
                cleaned_entities.append({"name": target, "type": "Entity", "attributes": {}})
                entity_names_lower.add(target.lower())

            cleaned_relations.append(
                {
                    "source": source,
                    "target": target,
                    "type": rtype,
                    "fact": fact or f"{source} {rtype} {target}",
                }
            )

        return {
            "entities": cleaned_entities,
            "relations": cleaned_relations,
        }
