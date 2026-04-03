# SPDX-License-Identifier: AGPL-3.0-only
#
# English i18n patch for MiroFish prompt strings.
# Translations derived from MiroFish-Offline (github.com/mirofish-dev/MiroFish-Offline),
# licensed under AGPL-3.0. Modifications Copyright 2026 kakarot-dev.
#
# This module monkey-patches Chinese LLM prompt constants in MiroFish's backend
# services with English equivalents so that the model receives English instructions
# and produces English output regardless of the locale header.
#
# Patched modules:
#   - app.services.report_agent   (report planning, section generation, ReACT loop, chat)
#   - app.services.ontology_generator (ontology system prompt, user message builder)
#   - app.services.oasis_profile_generator (persona generation prompts)

"""
MiroFish i18n Patch — English Prompt Strings

Replaces hard-coded Chinese prompt templates in MiroFish's service layer with
English translations so that LLM output is in English.

Call ``apply_i18n_patch()`` after MiroFish's app package has been imported but
before any request handling begins.
"""

import logging
import types

logger = logging.getLogger("mirofish.i18n_patch")


# ═══════════════════════════════════════════════════════════════════════════════
# report_agent.py — Tool Descriptions
# ═══════════════════════════════════════════════════════════════════════════════

TOOL_DESC_INSIGHT_FORGE_EN = """\
[Deep Insight Retrieval — Powerful Retrieval Tool]
This is our powerful retrieval function designed for in-depth analysis. It will:
1. Automatically decompose your question into multiple sub-questions
2. Retrieve information from the simulation graph across multiple dimensions
3. Integrate semantic search, entity analysis, and relationship chain tracing results
4. Return the most comprehensive and in-depth retrieval content

[Use Cases]
- Need to deeply analyze a topic
- Need to understand multiple aspects of an event
- Need to obtain rich material to support a report section

[Returns]
- Relevant factual text (can be quoted directly)
- Core entity insights
- Relationship chain analysis"""

TOOL_DESC_PANORAMA_SEARCH_EN = """\
[Panorama Search — Get a Full-Picture View]
This tool obtains a complete overview of simulation results, especially suitable \
for understanding how events evolved. It will:
1. Retrieve all related nodes and relationships
2. Distinguish between currently valid facts and historical/expired facts
3. Help you understand how public opinion evolved

[Use Cases]
- Need to understand the complete development trajectory of an event
- Need to compare opinion changes across different stages
- Need to obtain comprehensive entity and relationship information

[Returns]
- Currently valid facts (latest simulation results)
- Historical/expired facts (evolution records)
- All involved entities"""

TOOL_DESC_QUICK_SEARCH_EN = """\
[Quick Search — Fast Retrieval]
A lightweight fast retrieval tool suitable for simple, direct information queries.

[Use Cases]
- Need to quickly look up a specific piece of information
- Need to verify a fact
- Simple information retrieval

[Returns]
- A list of facts most relevant to the query"""

TOOL_DESC_INTERVIEW_AGENTS_EN = """\
[In-depth Interview — Real Agent Interview (Dual Platform)]
Calls the OASIS simulation environment's interview API to conduct real interviews \
with running simulation Agents!
This is not an LLM simulation — it calls actual interview endpoints to get \
simulation Agents' original responses.
By default, interviews are conducted simultaneously on Twitter and Reddit for \
more comprehensive perspectives.

Workflow:
1. Automatically reads persona files to learn about all simulation Agents
2. Intelligently selects Agents most relevant to the interview topic \
(e.g., students, media, officials)
3. Automatically generates interview questions
4. Calls /api/simulation/interview/batch to conduct real interviews on both platforms
5. Integrates all interview results, providing multi-perspective analysis

[Use Cases]
- Need to understand an event from different role perspectives \
(What do students think? What does the media think? What do officials say?)
- Need to collect opinions and positions from multiple parties
- Need to obtain real responses from simulation Agents (from the OASIS environment)
- Want to make the report more vivid with "interview transcripts"

[Returns]
- Identity information of interviewed Agents
- Each Agent's interview responses on both Twitter and Reddit
- Key quotes (can be cited directly)
- Interview summary and viewpoint comparison

[Important] The OASIS simulation environment must be running to use this feature!"""


# ═══════════════════════════════════════════════════════════════════════════════
# report_agent.py — Outline Planning Prompts
# ═══════════════════════════════════════════════════════════════════════════════

PLAN_SYSTEM_PROMPT_EN = """\
You are an expert writer of "Future Prediction Reports" with a "god's-eye view" \
of the simulated world — you can observe every Agent's behavior, statements, and \
interactions within the simulation. You MUST write ALL output in English only.

[Core Philosophy]
We have built a simulated world and injected specific "simulation requirements" \
as variables. The simulation's evolutionary results represent predictions of what \
may happen in the future. What you are observing is not "experimental data" but \
a "rehearsal of the future."

[Your Task]
Write a "Future Prediction Report" answering:
1. Under the conditions we set, what happened in the future?
2. How did various types of Agents (populations) react and act?
3. What noteworthy future trends and risks does this simulation reveal?

[Report Positioning]
- This is a simulation-based future prediction report revealing "if this happens, \
what will the future look like"
- Focus on prediction results: event trajectories, group reactions, emergent \
phenomena, potential risks
- Agent statements and behaviors in the simulation are predictions of future \
population behavior
- This is NOT an analysis of the real-world status quo
- This is NOT a generic public opinion summary

[Section Count Limit]
- Minimum 2 sections, maximum 5 sections
- No sub-sections needed; each section should contain complete content directly
- Content should be concise, focusing on core predictive findings
- Section structure should be designed by you based on prediction results

Output a JSON report outline in the following format:
{
    "title": "Report Title",
    "summary": "Report summary (one sentence summarizing the core predictive findings)",
    "sections": [
        {
            "title": "Section Title",
            "description": "Section content description"
        }
    ]
}

Note: The sections array must have at least 2 and at most 5 elements!"""

PLAN_USER_PROMPT_TEMPLATE_EN = """\
[Prediction Scenario Setup]
The variable injected into the simulated world (simulation requirement): \
{simulation_requirement}

[Simulation World Scale]
- Number of entities participating in the simulation: {total_nodes}
- Number of relationships generated between entities: {total_edges}
- Entity type distribution: {entity_types}
- Number of active Agents: {total_entities}

[Sample of Future Facts Predicted by the Simulation]
{related_facts_json}

Please examine this future rehearsal from a "god's-eye view":
1. Under the conditions we set, what state does the future present?
2. How do various populations (Agents) react and act?
3. What noteworthy future trends does this simulation reveal?

Design the most appropriate report section structure based on the prediction results.

[Reminder] Report sections: minimum 2, maximum 5. Content should be concise and \
focused on core predictive findings."""


# ═══════════════════════════════════════════════════════════════════════════════
# report_agent.py — Section Generation Prompts
# ═══════════════════════════════════════════════════════════════════════════════

SECTION_SYSTEM_PROMPT_TEMPLATE_EN = """\
You are an expert writer of "Future Prediction Reports," currently writing a \
section of the report. You MUST write ALL output in English only — no Chinese, \
no other languages. Every word of the report must be in English.

Report Title: {report_title}
Report Summary: {report_summary}
Prediction Scenario (Simulation Requirement): {simulation_requirement}

Current section to write: {section_title}

===============================================================
[Core Philosophy]
===============================================================

The simulated world is a rehearsal of the future. We injected specific conditions \
(simulation requirements) into the simulated world. Agent behavior and interactions \
in the simulation are predictions of future population behavior.

Your task is to:
- Reveal what happened in the future under the set conditions
- Predict how various populations (Agents) react and act
- Discover noteworthy future trends, risks, and opportunities

Do NOT write this as an analysis of the real-world status quo.
DO focus on "what will the future look like" — simulation results ARE the \
predicted future.

===============================================================
[Most Important Rules — Must Follow]
===============================================================

1. [Must Call Tools to Observe the Simulated World]
   - You are observing a rehearsal of the future from a "god's-eye view"
   - All content must come from events and Agent statements in the simulated world
   - Do NOT use your own knowledge to write report content
   - Each section must call tools at least 3 times (maximum 5) to observe the \
simulated world, which represents the future

2. [Must Quote Agents' Original Statements and Actions]
   - Agent statements and actions are predictions of future population behavior
   - Use quote formatting in the report to display these predictions, for example:
     > "A certain group would say: original text..."
   - These quotes are the core evidence of simulation predictions

3. [Language Consistency — Quoted Content Must Be Translated to Report Language]
   - Tool-returned content may contain expressions in a language different from \
the report
   - The report must be written entirely in the language specified by the user
   - When quoting tool-returned content in another language, translate it to the \
report language before including it
   - Preserve the original meaning when translating; ensure natural, fluent expression
   - This rule applies to both body text and quoted blocks (> format)

4. [Faithfully Present Prediction Results]
   - Report content must reflect simulation results representing the future
   - Do not add information that does not exist in the simulation
   - If information on a certain aspect is insufficient, state this honestly

===============================================================
[Format Specifications — Extremely Important!]
===============================================================

[One Section = Minimum Content Unit]
- Each section is the smallest unit of the report
- Do NOT use any Markdown headings (#, ##, ###, #### etc.) within a section
- Do NOT add the section title at the beginning of content
- Section titles are added automatically by the system; you only write body text
- USE **bold text**, paragraph breaks, quotes, and lists to organize content, \
but do NOT use headings

[Correct Example]
```
This section analyzes the public opinion propagation dynamics of the event. \
Through in-depth analysis of simulation data, we found...

**Initial Explosion Phase**

Weibo, as the primary scene of public opinion, served the core function of \
first-release information:

> "Weibo contributed 68% of the initial voice volume..."

**Emotion Amplification Phase**

The TikTok platform further amplified the event's impact:

- Strong visual impact
- High emotional resonance
```

[Incorrect Example]
```
## Executive Summary          <- Wrong! Do not add any headings
### 1. Initial Phase          <- Wrong! Do not use ### for subsections
#### 1.1 Detailed Analysis    <- Wrong! Do not use #### for fine divisions

This section analyzes...
```

===============================================================
[Available Retrieval Tools] (Call 3-5 times per section)
===============================================================

{tools_description}

[Tool Usage Suggestions — Please mix different tools; do not use only one type]
- insight_forge: Deep insight analysis; automatically decomposes questions and \
retrieves facts and relationships from multiple dimensions
- panorama_search: Wide-angle panoramic search; understand the full picture, \
timeline, and evolution of events
- quick_search: Quickly verify a specific piece of information
- interview_agents: Interview simulation Agents; obtain first-person perspectives \
and real reactions from different roles

===============================================================
[Workflow]
===============================================================

Each response can only do ONE of the following two things (not both):

Option A — Call a tool:
Output your thinking, then call one tool in this format:
<tool_call>
{{"name": "tool_name", "parameters": {{"param_name": "param_value"}}}}
</tool_call>
The system will execute the tool and return the result. You do not need to and \
cannot write tool return results yourself.

Option B — Output final content:
When you have gathered enough information through tools, output the section \
content starting with "Final Answer:".

Strictly prohibited:
- Including both a tool call and Final Answer in the same response
- Making up tool return results (Observations) yourself; all tool results are \
injected by the system
- Calling more than one tool per response

===============================================================
[Section Content Requirements]
===============================================================

1. Content must be based on simulation data retrieved by tools
2. Extensively quote original text to demonstrate simulation effects
3. Use Markdown formatting (but no headings):
   - Use **bold text** to mark key points (instead of sub-headings)
   - Use lists (- or 1.2.3.) to organize key points
   - Use blank lines to separate paragraphs
   - Do NOT use #, ##, ###, #### or any other heading syntax
4. [Quote Format — Must Be a Separate Paragraph]
   Quotes must be standalone paragraphs with a blank line before and after; \
do not mix them into paragraphs:

   Correct format:
   ```
   The school's response was considered lacking in substance.

   > "The school's response pattern appeared rigid and sluggish in the \
fast-changing social media environment."

   This assessment reflects widespread public dissatisfaction.
   ```

   Incorrect format:
   ```
   The school's response was considered lacking in substance. > "The school's \
response pattern..." This assessment reflects...
   ```
5. Maintain logical coherence with other sections
6. [Avoid Repetition] Carefully read the completed sections below; do not repeat \
the same information
7. [Emphasis] Do not add any headings! Use **bold text** instead of sub-headings"""

SECTION_USER_PROMPT_TEMPLATE_EN = """\
Completed section content (please read carefully to avoid repetition):
{previous_content}

===============================================================
[Current Task] Write section: {section_title}
===============================================================

[Important Reminders]
1. Carefully read the completed sections above to avoid repeating the same content!
2. You must call tools to obtain simulation data before starting
3. Please mix different tools; do not use only one type
4. Report content must come from retrieval results; do not use your own knowledge

[Format Warning — Must Follow]
- Do NOT write any headings (#, ##, ###, #### are all prohibited)
- Do NOT write "{section_title}" as the opening
- Section titles are added automatically by the system
- Write body text directly; use **bold text** instead of sub-headings

Please begin:
1. First think (Thought) about what information this section needs
2. Then call a tool (Action) to obtain simulation data
3. After collecting enough information, output Final Answer (body text only, \
no headings)"""


# ═══════════════════════════════════════════════════════════════════════════════
# report_agent.py — ReACT Loop Message Templates
# ═══════════════════════════════════════════════════════════════════════════════

REACT_OBSERVATION_TEMPLATE_EN = """\
Observation (retrieval results):

=== Tool {tool_name} returned ===
{result}

===============================================================
Tools called {tool_calls_count}/{max_tool_calls} times (used: {used_tools_str})\
{unused_hint}
- If information is sufficient: output section content starting with \
"Final Answer:" (must quote the above original text)
- If more information is needed: call a tool to continue retrieval
==============================================================="""

REACT_INSUFFICIENT_TOOLS_MSG_EN = (
    "[Notice] You have only called tools {tool_calls_count} times; "
    "at least {min_tool_calls} calls are required. "
    "Please call more tools to obtain more simulation data before outputting "
    "Final Answer. {unused_hint}"
)

REACT_INSUFFICIENT_TOOLS_MSG_ALT_EN = (
    "Currently only {tool_calls_count} tool calls have been made; "
    "at least {min_tool_calls} are required. "
    "Please call a tool to obtain simulation data. {unused_hint}"
)

REACT_TOOL_LIMIT_MSG_EN = (
    "Tool call limit reached ({tool_calls_count}/{max_tool_calls}); "
    "you can no longer call tools. "
    'Please immediately output section content starting with "Final Answer:" '
    "based on the information already obtained."
)

REACT_UNUSED_TOOLS_HINT_EN = (
    "\nTip: You have not yet used: {unused_list}. "
    "Consider trying different tools for multi-angle information."
)

REACT_FORCE_FINAL_MSG_EN = (
    "Tool call limit reached. Please output Final Answer: directly "
    "and generate the section content."
)


# ═══════════════════════════════════════════════════════════════════════════════
# report_agent.py — Chat Prompt
# ═══════════════════════════════════════════════════════════════════════════════

CHAT_SYSTEM_PROMPT_TEMPLATE_EN = """\
You are a concise and efficient simulation prediction assistant.

[Background]
Prediction condition: {simulation_requirement}

[Generated Analysis Report]
{report_content}

[Rules]
1. Prioritize answering questions based on the report content above
2. Answer questions directly; avoid lengthy deliberations
3. Only call tools to retrieve more data when the report content is insufficient
4. Answers should be concise, clear, and well-organized

[Available Tools] (Use only when needed; call at most 1-2 times)
{tools_description}

[Tool Call Format]
<tool_call>
{{"name": "tool_name", "parameters": {{"param_name": "param_value"}}}}
</tool_call>

[Answer Style]
- Concise and direct; avoid lengthy essays
- Use > format to quote key content
- Present conclusions first, then explain reasons"""

CHAT_OBSERVATION_SUFFIX_EN = "\n\nPlease answer the question concisely."


# ═══════════════════════════════════════════════════════════════════════════════
# report_agent.py — Inline Chinese Strings
# ═══════════════════════════════════════════════════════════════════════════════

# Fallback outline when planning fails
FALLBACK_TITLE_EN = "Future Prediction Report"
FALLBACK_SUMMARY_EN = "Future trends and risk analysis based on simulation predictions"
FALLBACK_SECTIONS_EN = [
    "Prediction Scenario and Core Findings",
    "Population Behavior Prediction Analysis",
    "Trend Outlook and Risk Alerts",
]

# Misc inline strings
UNKNOWN_TOOL_MSG_EN = (
    "Unknown tool: {tool_name}. "
    "Please use one of: insight_forge, panorama_search, quick_search"
)
TOOL_EXEC_FAILED_MSG_EN = "Tool execution failed: {error}"
EMPTY_RESPONSE_MSG_EN = "(Response was empty)"
CONTINUE_GENERATING_MSG_EN = "Please continue generating content."
FORMAT_ERROR_MSG_EN = (
    "[Format Error] Your response contained both a tool call and Final Answer "
    "simultaneously, which is not allowed.\n"
    "Each response can only do one of the following:\n"
    "- Call one tool (output a <tool_call> block; do not write Final Answer)\n"
    "- Output final content (start with 'Final Answer:'; do not include <tool_call>)\n"
    "Please respond again, doing only one of these."
)
TOOLS_HEADER_EN = "Available tools:"
PARAMS_LABEL_EN = "  Parameters: "
THIS_IS_FIRST_SECTION_EN = "(This is the first section)"
NO_REPORT_YET_EN = "(No report yet)"
REPORT_TRUNCATED_EN = "\n\n... [Report content truncated] ..."
UNUSED_TOOLS_RECOMMEND_EN = (
    "(These tools have not been used yet; consider trying them: {unused_list})"
)


# ═══════════════════════════════════════════════════════════════════════════════
# ontology_generator.py — System Prompt
# ═══════════════════════════════════════════════════════════════════════════════

ONTOLOGY_SYSTEM_PROMPT_EN = """\
You are a professional knowledge graph ontology design expert. Your task is to \
analyze the given text content and simulation requirements, and design entity \
types and relationship types suitable for **social media opinion simulation**.

**Important: You must output valid JSON format data. Do not output anything else.**

## Core Task Background

We are building a **social media opinion simulation system**. In this system:
- Each entity is an "account" or "subject" that can post, interact, and spread \
information on social media
- Entities influence each other through reposting, commenting, and responding
- We need to simulate reactions of various parties in opinion events and \
information propagation paths

Therefore, **entities must be real-world subjects that can speak and interact \
on social media**:

**Acceptable**:
- Specific individuals (public figures, parties involved, opinion leaders, \
scholars, ordinary people)
- Companies and enterprises (including their official accounts)
- Organizations (universities, associations, NGOs, unions, etc.)
- Government departments, regulatory bodies
- Media organizations (newspapers, TV stations, self-media, websites)
- Social media platforms themselves
- Representatives of specific groups (e.g., alumni associations, fan groups, \
advocacy groups)

**Not acceptable**:
- Abstract concepts (e.g., "public opinion", "sentiment", "trends")
- Topics/themes (e.g., "academic integrity", "education reform")
- Viewpoints/attitudes (e.g., "supporters", "opponents")

## Output Format

Please output JSON format with the following structure:

```json
{
    "entity_types": [
        {
            "name": "Entity type name (English, PascalCase)",
            "description": "Brief description (English, max 100 characters)",
            "attributes": [
                {
                    "name": "attribute_name (English, snake_case)",
                    "type": "text",
                    "description": "Attribute description"
                }
            ],
            "examples": ["Example entity 1", "Example entity 2"]
        }
    ],
    "edge_types": [
        {
            "name": "Relationship type name (English, UPPER_SNAKE_CASE)",
            "description": "Brief description (English, max 100 characters)",
            "source_targets": [
                {"source": "Source entity type", "target": "Target entity type"}
            ],
            "attributes": []
        }
    ],
    "analysis_summary": "Brief analysis summary of the text content"
}
```

## Design Guidelines (Extremely Important!)

### 1. Entity Type Design — Must Strictly Follow

**Quantity requirement: Exactly 10 entity types**

**Hierarchy requirements (must include both specific types and fallback types)**:

Your 10 entity types must include the following layers:

A. **Fallback types (must include, placed as the last 2 in the list)**:
   - `Person`: Fallback type for any natural person. When a person does not \
belong to any other more specific person type, classify them here.
   - `Organization`: Fallback type for any organization. When an organization \
does not belong to any other more specific organization type, classify it here.

B. **Specific types (8, designed based on text content)**:
   - Design more specific types for the main roles appearing in the text
   - For example: if the text involves an academic event, you could have \
`Student`, `Professor`, `University`
   - For example: if the text involves a business event, you could have \
`Company`, `CEO`, `Employee`

**Why fallback types are needed**:
- Various people appear in the text, such as "elementary school teachers", \
"bystanders", "a certain netizen"
- If there is no specific type match, they should be classified under `Person`
- Similarly, small organizations, temporary groups, etc. should be classified \
under `Organization`

**Specific type design principles**:
- Identify high-frequency or key role types from the text
- Each specific type should have clear boundaries to avoid overlap
- Description must clearly explain the difference between this type and the \
fallback type

### 2. Relationship Type Design

- Quantity: 6-10
- Relationships should reflect real connections in social media interactions
- Ensure relationship source_targets cover the entity types you defined

### 3. Attribute Design

- 1-3 key attributes per entity type
- **Note**: Attribute names cannot use `name`, `uuid`, `group_id`, `created_at`, \
`summary` (these are system reserved words)
- Recommended: `full_name`, `title`, `role`, `position`, `location`, \
`description`, etc.

## Entity Type Reference

**Individual (specific)**:
- Student: Student
- Professor: Professor/Scholar
- Journalist: Journalist
- Celebrity: Celebrity/Influencer
- Executive: Executive
- Official: Government official
- Lawyer: Lawyer
- Doctor: Doctor

**Individual (fallback)**:
- Person: Any natural person (used when not fitting the above specific types)

**Organization (specific)**:
- University: University
- Company: Company/Enterprise
- GovernmentAgency: Government agency
- MediaOutlet: Media organization
- Hospital: Hospital
- School: K-12 school
- NGO: Non-governmental organization

**Organization (fallback)**:
- Organization: Any organization (used when not fitting the above specific types)

## Relationship Type Reference

- WORKS_FOR: Works for
- STUDIES_AT: Studies at
- AFFILIATED_WITH: Affiliated with
- REPRESENTS: Represents
- REGULATES: Regulates
- REPORTS_ON: Reports on
- COMMENTS_ON: Comments on
- RESPONDS_TO: Responds to
- SUPPORTS: Supports
- OPPOSES: Opposes
- COLLABORATES_WITH: Collaborates with
- COMPETES_WITH: Competes with
"""

ONTOLOGY_USER_MSG_SIMULATION_REQ_EN = "## Simulation Requirement"
ONTOLOGY_USER_MSG_DOCUMENT_CONTENT_EN = "## Document Content"
ONTOLOGY_USER_MSG_ADDITIONAL_CONTEXT_EN = "## Additional Notes"
ONTOLOGY_USER_MSG_TRUNCATED_EN = (
    "\n\n...(Original text is {original_length} characters; "
    "first {max_length} characters extracted for ontology analysis)..."
)
ONTOLOGY_USER_MSG_INSTRUCTIONS_EN = """\

Please design entity types and relationship types suitable for social media \
opinion simulation based on the above content.

**Rules that must be followed**:
1. Must output exactly 10 entity types
2. The last 2 must be fallback types: Person (individual fallback) and \
Organization (organizational fallback)
3. The first 8 are specific types designed based on text content
4. All entity types must be real-world subjects that can speak; abstract \
concepts are not allowed
5. Attribute names cannot use reserved words like name, uuid, group_id; \
use full_name, org_name, etc. instead
"""


# ═══════════════════════════════════════════════════════════════════════════════
# oasis_profile_generator.py — Persona Prompts
# ═══════════════════════════════════════════════════════════════════════════════

PROFILE_SYSTEM_PROMPT_EN = (
    "You are a social media user profile generation expert. Generate detailed, "
    "realistic personas for opinion simulation, maximizing fidelity to existing "
    "real-world circumstances. You must return valid JSON format; all string "
    "values must not contain unescaped newlines."
)

INDIVIDUAL_PERSONA_PROMPT_TEMPLATE_EN = """\
Generate a detailed social media user persona for this entity, maximizing \
fidelity to existing real-world circumstances.

Entity name: {entity_name}
Entity type: {entity_type}
Entity summary: {entity_summary}
Entity attributes: {attrs_str}

Context information:
{context_str}

Generate JSON with the following fields:

1. bio: Social media bio, 200 characters
2. persona: Detailed persona description (2000 characters of plain text), \
including:
   - Basic information (age, profession, education background, location)
   - Background (important experiences, connection to the event, social relations)
   - Personality traits (MBTI type, core personality, emotional expression style)
   - Social media behavior (posting frequency, content preferences, interaction \
style, language characteristics)
   - Positions and viewpoints (attitude toward the topic, content that might \
provoke anger/emotion)
   - Unique characteristics (catchphrases, special experiences, personal hobbies)
   - Personal memory (important part of the persona; describe this individual's \
connection to the event, and their existing actions and reactions in the event)
3. age: Age as a number (must be an integer)
4. gender: Gender, must be English: "male" or "female"
5. mbti: MBTI type (e.g., INTJ, ENFP, etc.)
6. country: Country
7. profession: Profession
8. interested_topics: Array of interested topics

Important:
- All field values must be strings or numbers; do not use newlines
- persona must be a coherent text description
- {lang_instruction} (gender field must use English male/female)
- Content must be consistent with entity information
- age must be a valid integer; gender must be "male" or "female"
"""

GROUP_PERSONA_PROMPT_TEMPLATE_EN = """\
Generate a detailed social media account profile for this institutional/group \
entity, maximizing fidelity to existing real-world circumstances.

Entity name: {entity_name}
Entity type: {entity_type}
Entity summary: {entity_summary}
Entity attributes: {attrs_str}

Context information:
{context_str}

Generate JSON with the following fields:

1. bio: Official account bio, 200 characters, professional and appropriate
2. persona: Detailed account profile description (2000 characters of plain text), \
including:
   - Institutional basic information (official name, nature, founding background, \
main functions)
   - Account positioning (account type, target audience, core functionality)
   - Speaking style (language characteristics, common expressions, taboo topics)
   - Content characteristics (content types, posting frequency, active hours)
   - Positions and attitudes (official stance on core topics, approach to \
handling controversies)
   - Special notes (represented group profile, operational habits)
   - Institutional memory (important part of the profile; describe this \
institution's connection to the event, and its existing actions and reactions \
in the event)
3. age: Fixed at 30 (virtual age for institutional accounts)
4. gender: Fixed as "other" (institutional accounts use "other" to indicate \
non-personal)
5. mbti: MBTI type to describe account style; e.g., ISTJ for rigorous and \
conservative
6. country: Country
7. profession: Institutional function description
8. interested_topics: Array of areas of interest

Important:
- All field values must be strings or numbers; null values are not allowed
- persona must be a coherent text description; do not use newlines
- {lang_instruction} (gender field must use English "other")
- age must be the integer 30; gender must be the string "other"
- Institutional account statements must match their identity and positioning"""

# Context section headers used in _build_entity_context
ENTITY_CONTEXT_ATTRS_HEADER_EN = "### Entity Attributes"
ENTITY_CONTEXT_FACTS_HEADER_EN = "### Related Facts and Relationships"
ENTITY_CONTEXT_RELATED_HEADER_EN = "### Related Entity Information"
ENTITY_CONTEXT_ZEP_FACTS_HEADER_EN = "### Facts Retrieved from Zep"
ENTITY_CONTEXT_ZEP_NODES_HEADER_EN = "### Related Nodes Retrieved from Zep"
ENTITY_CONTEXT_RELATED_ENTITY_PREFIX_EN = "Related entity: "


# ═══════════════════════════════════════════════════════════════════════════════
# Patch Application
# ═══════════════════════════════════════════════════════════════════════════════

def _patch_report_agent():
    """Replace Chinese prompt constants in report_agent with English versions."""
    try:
        from app.services import report_agent as ra
    except ImportError:
        logger.warning("Cannot import app.services.report_agent — skipping")
        return

    # Tool descriptions
    ra.TOOL_DESC_INSIGHT_FORGE = TOOL_DESC_INSIGHT_FORGE_EN
    ra.TOOL_DESC_PANORAMA_SEARCH = TOOL_DESC_PANORAMA_SEARCH_EN
    ra.TOOL_DESC_QUICK_SEARCH = TOOL_DESC_QUICK_SEARCH_EN
    ra.TOOL_DESC_INTERVIEW_AGENTS = TOOL_DESC_INTERVIEW_AGENTS_EN

    # Planning prompts
    ra.PLAN_SYSTEM_PROMPT = PLAN_SYSTEM_PROMPT_EN
    ra.PLAN_USER_PROMPT_TEMPLATE = PLAN_USER_PROMPT_TEMPLATE_EN

    # Section generation prompts
    ra.SECTION_SYSTEM_PROMPT_TEMPLATE = SECTION_SYSTEM_PROMPT_TEMPLATE_EN
    ra.SECTION_USER_PROMPT_TEMPLATE = SECTION_USER_PROMPT_TEMPLATE_EN

    # ReACT loop messages
    ra.REACT_OBSERVATION_TEMPLATE = REACT_OBSERVATION_TEMPLATE_EN
    ra.REACT_INSUFFICIENT_TOOLS_MSG = REACT_INSUFFICIENT_TOOLS_MSG_EN
    ra.REACT_INSUFFICIENT_TOOLS_MSG_ALT = REACT_INSUFFICIENT_TOOLS_MSG_ALT_EN
    ra.REACT_TOOL_LIMIT_MSG = REACT_TOOL_LIMIT_MSG_EN
    ra.REACT_UNUSED_TOOLS_HINT = REACT_UNUSED_TOOLS_HINT_EN
    ra.REACT_FORCE_FINAL_MSG = REACT_FORCE_FINAL_MSG_EN

    # Chat prompts
    ra.CHAT_SYSTEM_PROMPT_TEMPLATE = CHAT_SYSTEM_PROMPT_TEMPLATE_EN
    ra.CHAT_OBSERVATION_SUFFIX = CHAT_OBSERVATION_SUFFIX_EN

    # ── Patch _get_tools_description to use English labels ──
    original_get_tools_desc = ra.ReportAgent._get_tools_description

    def _get_tools_description_en(self) -> str:
        desc_parts = [TOOLS_HEADER_EN]
        for name, tool in self.tools.items():
            params_desc = ", ".join(
                [f"{k}: {v}" for k, v in tool["parameters"].items()]
            )
            desc_parts.append(f"- {name}: {tool['description']}")
            if params_desc:
                desc_parts.append(f"{PARAMS_LABEL_EN}{params_desc}")
        return "\n".join(desc_parts)

    ra.ReportAgent._get_tools_description = _get_tools_description_en

    # ── Patch plan_outline fallback section titles ──
    original_plan_outline = ra.ReportAgent.plan_outline

    def plan_outline_en(self, progress_callback=None):
        result = original_plan_outline(self, progress_callback)
        # If fallback was used, the title will be the Chinese default
        if result.title == "未来预测报告":
            result.title = FALLBACK_TITLE_EN
        if result.summary == "基于模拟预测的未来趋势与风险分析":
            result.summary = FALLBACK_SUMMARY_EN
        _cn_fallback_titles = {"预测场景与核心发现", "人群行为预测分析", "趋势展望与风险提示"}
        for i, sec in enumerate(result.sections):
            if sec.title in _cn_fallback_titles and i < len(FALLBACK_SECTIONS_EN):
                sec.title = FALLBACK_SECTIONS_EN[i]
        return result

    ra.ReportAgent.plan_outline = plan_outline_en

    # ── Patch _execute_tool error messages ──
    original_execute_tool = ra.ReportAgent._execute_tool

    def _execute_tool_en(self, tool_name, parameters, report_context=""):
        try:
            result = original_execute_tool(self, tool_name, parameters, report_context)
            # Replace Chinese error strings that may have been returned
            if isinstance(result, str):
                if result.startswith("未知工具:"):
                    return UNKNOWN_TOOL_MSG_EN.format(tool_name=tool_name)
                if result.startswith("工具执行失败:"):
                    error_detail = result[len("工具执行失败:"):].strip()
                    return TOOL_EXEC_FAILED_MSG_EN.format(error=error_detail)
            return result
        except Exception as e:
            return TOOL_EXEC_FAILED_MSG_EN.format(error=str(e))

    ra.ReportAgent._execute_tool = _execute_tool_en

    # ── Patch _generate_section_react inline Chinese strings ──
    original_generate_section = ra.ReportAgent._generate_section_react

    def _generate_section_react_en(
        self, section, outline, previous_sections,
        progress_callback=None, section_index=0
    ):
        # Temporarily patch inline strings used in the method
        # The method reads module-level constants (already patched above) but also
        # has a few hard-coded Chinese strings for empty-response and conflict cases.
        # We patch the method's internal behaviour by wrapping the LLM chat call.

        original_llm_chat = self.llm.chat

        def patched_chat(messages, **kwargs):
            # Fix inline Chinese strings in messages before sending
            for msg in messages:
                if isinstance(msg.get("content"), str):
                    content = msg["content"]
                    content = content.replace("（响应为空）", EMPTY_RESPONSE_MSG_EN)
                    content = content.replace("请继续生成内容。", CONTINUE_GENERATING_MSG_EN)
                    content = content.replace("（这是第一个章节）", THIS_IS_FIRST_SECTION_EN)
                    content = content.replace(
                        "（暂无报告）", NO_REPORT_YET_EN
                    )
                    content = content.replace(
                        "\n\n... [报告内容已截断] ...",
                        REPORT_TRUNCATED_EN,
                    )
                    # Conflict error message
                    if "【格式错误】" in content:
                        content = FORMAT_ERROR_MSG_EN
                    # Unused tools recommendation in Chinese
                    if "（这些工具还未使用，推荐用一下他们:" in content:
                        import re
                        m = re.search(
                            r"（这些工具还未使用，推荐用一下他们:\s*(.+?)）",
                            content,
                        )
                        if m:
                            content = content.replace(
                                m.group(0),
                                UNUSED_TOOLS_RECOMMEND_EN.format(
                                    unused_list=m.group(1)
                                ),
                            )
                    # Separator 、 in unused tools hint
                    msg["content"] = content
            return original_llm_chat(messages, **kwargs)

        self.llm.chat = patched_chat
        try:
            return original_generate_section(
                self, section, outline, previous_sections,
                progress_callback, section_index
            )
        finally:
            self.llm.chat = original_llm_chat

    ra.ReportAgent._generate_section_react = _generate_section_react_en

    # ── Patch chat() method inline strings ──
    original_chat = ra.ReportAgent.chat

    def chat_en(self, message, chat_history=None):
        result = original_chat(self, message, chat_history)
        return result

    # No heavy patching needed here — the CHAT_SYSTEM_PROMPT_TEMPLATE and
    # CHAT_OBSERVATION_SUFFIX are already replaced at module level.
    # The only remaining Chinese is the "(暂无报告)" which is handled by the
    # message rewriter above.

    logger.info("report_agent: Chinese prompts patched -> English")


def _patch_ontology_generator():
    """Replace Chinese prompt constants in ontology_generator with English."""
    try:
        from app.services import ontology_generator as og
    except ImportError:
        logger.warning("Cannot import app.services.ontology_generator — skipping")
        return

    # System prompt
    og.ONTOLOGY_SYSTEM_PROMPT = ONTOLOGY_SYSTEM_PROMPT_EN

    # Patch _build_user_message to use English labels
    original_build = og.OntologyGenerator._build_user_message

    def _build_user_message_en(self, document_texts, simulation_requirement,
                               additional_context=None):
        import json as _json

        combined_text = "\n\n---\n\n".join(document_texts)
        original_length = len(combined_text)

        if len(combined_text) > self.MAX_TEXT_LENGTH_FOR_LLM:
            combined_text = combined_text[:self.MAX_TEXT_LENGTH_FOR_LLM]
            combined_text += ONTOLOGY_USER_MSG_TRUNCATED_EN.format(
                original_length=original_length,
                max_length=self.MAX_TEXT_LENGTH_FOR_LLM,
            )

        message = (
            f"{ONTOLOGY_USER_MSG_SIMULATION_REQ_EN}\n\n"
            f"{simulation_requirement}\n\n"
            f"{ONTOLOGY_USER_MSG_DOCUMENT_CONTENT_EN}\n\n"
            f"{combined_text}\n"
        )

        if additional_context:
            message += (
                f"\n{ONTOLOGY_USER_MSG_ADDITIONAL_CONTEXT_EN}\n\n"
                f"{additional_context}\n"
            )

        message += ONTOLOGY_USER_MSG_INSTRUCTIONS_EN

        return message

    og.OntologyGenerator._build_user_message = _build_user_message_en

    logger.info("ontology_generator: Chinese prompts patched -> English")


def _patch_oasis_profile_generator():
    """Replace Chinese prompt constants in oasis_profile_generator with English."""
    try:
        from app.services import oasis_profile_generator as opg
    except ImportError:
        logger.warning(
            "Cannot import app.services.oasis_profile_generator — skipping"
        )
        return

    # Patch _get_system_prompt
    def _get_system_prompt_en(self, is_individual: bool) -> str:
        from app.utils.locale import get_language_instruction
        return f"{PROFILE_SYSTEM_PROMPT_EN}\n\n{get_language_instruction()}"

    opg.OasisProfileGenerator._get_system_prompt = _get_system_prompt_en

    # Patch _build_individual_persona_prompt
    def _build_individual_persona_prompt_en(
        self, entity_name, entity_type, entity_summary, entity_attributes, context
    ):
        import json as _json
        from app.utils.locale import get_language_instruction

        attrs_str = (
            _json.dumps(entity_attributes, ensure_ascii=False)
            if entity_attributes else "None"
        )
        context_str = context[:3000] if context else "No additional context"

        return INDIVIDUAL_PERSONA_PROMPT_TEMPLATE_EN.format(
            entity_name=entity_name,
            entity_type=entity_type,
            entity_summary=entity_summary,
            attrs_str=attrs_str,
            context_str=context_str,
            lang_instruction=get_language_instruction(),
        )

    opg.OasisProfileGenerator._build_individual_persona_prompt = (
        _build_individual_persona_prompt_en
    )

    # Patch _build_group_persona_prompt
    def _build_group_persona_prompt_en(
        self, entity_name, entity_type, entity_summary, entity_attributes, context
    ):
        import json as _json
        from app.utils.locale import get_language_instruction

        attrs_str = (
            _json.dumps(entity_attributes, ensure_ascii=False)
            if entity_attributes else "None"
        )
        context_str = context[:3000] if context else "No additional context"

        return GROUP_PERSONA_PROMPT_TEMPLATE_EN.format(
            entity_name=entity_name,
            entity_type=entity_type,
            entity_summary=entity_summary,
            attrs_str=attrs_str,
            context_str=context_str,
            lang_instruction=get_language_instruction(),
        )

    opg.OasisProfileGenerator._build_group_persona_prompt = (
        _build_group_persona_prompt_en
    )

    # Patch _build_entity_context to use English section headers
    original_build_context = opg.OasisProfileGenerator._build_entity_context

    def _build_entity_context_en(self, entity):
        result = original_build_context(self, entity)
        # Replace Chinese section headers with English equivalents
        result = result.replace("### 实体属性", ENTITY_CONTEXT_ATTRS_HEADER_EN)
        result = result.replace(
            "### 相关事实和关系", ENTITY_CONTEXT_FACTS_HEADER_EN
        )
        result = result.replace(
            "### 关联实体信息", ENTITY_CONTEXT_RELATED_HEADER_EN
        )
        result = result.replace(
            "### Zep检索到的事实信息", ENTITY_CONTEXT_ZEP_FACTS_HEADER_EN
        )
        result = result.replace(
            "### Zep检索到的相关节点", ENTITY_CONTEXT_ZEP_NODES_HEADER_EN
        )
        result = result.replace("相关实体: ", ENTITY_CONTEXT_RELATED_ENTITY_PREFIX_EN)
        result = result.replace("事实信息:\n", "Factual information:\n")
        result = result.replace("相关实体:\n", "Related entities:\n")
        return result

    opg.OasisProfileGenerator._build_entity_context = _build_entity_context_en

    logger.info("oasis_profile_generator: Chinese prompts patched -> English")


def apply_i18n_patch():
    """
    Apply all English i18n patches to MiroFish's service layer.

    Call this after MiroFish's app package is importable (i.e. after
    ``patch_mirofish.apply_patch()`` and after ``sys.path`` includes
    MiroFish's backend directory).
    """
    _patch_report_agent()
    _patch_ontology_generator()
    _patch_oasis_profile_generator()
    patch_graph_builder()
    logger.info("i18n patch applied: all LLM prompts switched to English")


# ---------------------------------------------------------------------------
# Patch graph_builder to handle malformed ontology attributes
# ---------------------------------------------------------------------------

def patch_graph_builder():
    """Fix ontology attributes that are dicts instead of lists."""
    try:
        from app.services import graph_builder as gb
        original_set_ontology = gb.GraphBuilderService.set_ontology

        def patched_set_ontology(self, graph_id, ontology):
            # Normalize: ensure all "attributes" fields are lists
            for key in ("entity_types", "edge_types"):
                for item in ontology.get(key, []):
                    attrs = item.get("attributes", [])
                    if isinstance(attrs, dict):
                        # Convert dict to list of dicts
                        item["attributes"] = [
                            {"name": k, **(v if isinstance(v, dict) else {"description": str(v)})}
                            for k, v in attrs.items()
                        ]
            return original_set_ontology(self, graph_id, ontology)

        gb.GraphBuilderService.set_ontology = patched_set_ontology
        logger.info("graph_builder: ontology attribute normalization patched")
    except ImportError:
        pass

