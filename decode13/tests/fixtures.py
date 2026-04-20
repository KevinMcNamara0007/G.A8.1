"""Test fixtures — Wikidata-style triples + narrative sentences.

The structured triples mirror the shape that Phase 1 used (PlanB §1.1).
The unstructured text is modeled on the plan's §2 example and includes
sentences that should produce multiple triples each.
"""

# Wikidata-shape structured triples. The "subject" and "relation" fields
# contain the exact compound tokens that Phase 1's canonical pipeline
# shattered: joe_misiti, member_of_sports_team, etc. Tier 1 must preserve
# them verbatim.
STRUCTURED_TRIPLES = [
    {"subject": "joe_misiti", "relation": "member_of_sports_team",
     "object": "melbourne_football_club"},
    {"subject": "ayrton_senna", "relation": "member_of_sports_team",
     "object": "team_lotus"},
    {"subject": "paris", "relation": "instance_of",
     "object": "capital_city"},
    {"subject": "eiffel_tower", "relation": "located_in_the_administrative_territorial_entity",
     "object": "paris"},
    {"subject": "chinese_odd_fellows_building", "relation": "instance_of",
     "object": "historic_building"},
    {"subject": "france", "relation": "capital",
     "object": "paris"},
    {"subject": "france", "relation": "official_language",
     "object": "french"},
    {"subject": "marie_curie", "relation": "occupation",
     "object": "physicist"},
    {"subject": "albert_einstein", "relation": "occupation",
     "object": "theoretical_physicist"},
    {"subject": "japan", "relation": "shares_border_with",
     "object": "none_island_nation"},
    # A triple with underscored R where naive canonicalization would
    # produce tokens "member", "sports", "team" — indistinguishable from
    # any other record containing those generic words.
    {"subject": "derek_jeter", "relation": "member_of_sports_team",
     "object": "new_york_yankees"},
    {"subject": "wikidata", "relation": "instance_of",
     "object": "knowledge_graph"},
]

# Queries mirror the shape at §1.3 of the plan. The "gold_record" is the
# index into STRUCTURED_TRIPLES (above) that the query should retrieve
# at rank 1.
STRUCTURED_QUERIES = [
    # (query_subject, query_relation, gold_record_index)
    ("joe_misiti", "member_of_sports_team", 0),
    ("ayrton_senna", "member_of_sports_team", 1),
    ("eiffel_tower", "located_in_the_administrative_territorial_entity", 3),
    ("chinese_odd_fellows_building", "instance_of", 4),
    ("france", "capital", 5),
    ("france", "official_language", 6),
    ("marie_curie", "occupation", 7),
    ("derek_jeter", "member_of_sports_team", 10),
]


# Unstructured narrative text — each entry should produce at least one
# validated atomic triple via Tier 2. The "expected_triples" list is
# what a reasonable extractor produces; the dual-extractor gate may
# tag only a subset as gate_agreement=True.
UNSTRUCTURED_TEXTS = [
    {
        "id": "france_profile",
        "text": (
            "The capital of France is Paris. "
            "The official language of France is French. "
            "The population of France is 67000000."
        ),
        "expected_triples": [
            ("france", "capital", "paris"),
            ("france", "language", "french"),
            ("france", "population", "67000000"),
        ],
    },
    {
        "id": "einstein_profile",
        "text": (
            "Albert Einstein was a theoretical physicist. "
            "Einstein's birthplace is Ulm."
        ),
        "expected_triples": [
            ("albert_einstein", "is_a", "theoretical_physicist"),
            ("einstein", "birthplace", "ulm"),
        ],
    },
    {
        "id": "moon_profile",
        "text": (
            "The Moon is a natural satellite. "
            "The diameter of the Moon is 3474."
        ),
        "expected_triples": [
            ("moon", "is_a", "natural_satellite"),
            ("moon", "diameter", "3474"),
        ],
    },
]

# Free-text queries that should hit the corresponding unstructured entries.
UNSTRUCTURED_QUERIES = [
    # (query_text, gold_unstructured_id, expected_s, expected_r, expected_o)
    ("What is the capital of France?", "france_profile",
     "france", "capital", "paris"),
    ("Is the official language of France French?", "france_profile",
     "france", "language", "french"),
    ("Was Albert Einstein a theoretical physicist?", "einstein_profile",
     "albert_einstein", "is_a", "theoretical_physicist"),
    ("The Moon is a what?", "moon_profile",
     "moon", "is_a", "natural_satellite"),
]
