"""
Edge Analyst Domain Gazetteer

Extracted from product.edge.analyst.bsc config.py.
Locations, organizations, and concepts relevant to
OSINT / threat intelligence / geopolitical analysis.

Usage:
    from resolvers.edge_gazetteer import load_edge_gazetteer
    gaz = load_edge_gazetteer()  # returns frozenset of ~300 terms
"""

DOMAIN_LOCATIONS = frozenset({
    "iran", "tehran", "isfahan", "mashhad", "tabriz", "shiraz", "qom",
    "iraq", "baghdad", "basra", "mosul", "erbil", "kirkuk",
    "syria", "damascus", "aleppo", "homs", "idlib", "latakia", "raqqa",
    "lebanon", "beirut", "tripoli", "sidon", "tyre",
    "yemen", "sanaa", "aden", "hodeidah", "taiz",
    "palestine", "gaza", "ramallah", "hebron", "nablus",
    "israel", "jerusalem", "haifa",
    "jordan", "amman",
    "saudi", "riyadh", "jeddah", "mecca", "medina",
    "dubai", "sharjah",
    "qatar", "doha",
    "bahrain", "manama",
    "kuwait", "oman", "muscat",
    "afghanistan", "kabul", "kandahar", "herat",
    "pakistan", "islamabad", "karachi", "lahore", "peshawar",
    "turkey", "ankara", "istanbul",
    "russia", "moscow",
    "china", "beijing",
    "pyongyang", "venezuela", "caracas", "cuba", "havana",
})

DOMAIN_ORGANIZATIONS = frozenset({
    "irgc", "quds", "basij", "mois", "vevak", "artesh",
    "hezbollah", "hizballah", "hizbollah",
    "hamas", "pij",
    "houthis",
    "kataib", "hashd",
    "taliban", "haqqani",
    "isis", "isil", "daesh",
    "qaeda", "aqap", "aqim",
    "shabaab", "lashkar",
    "mossad", "aman",
    "cia", "fbi", "nsa",
    "fsb", "gru", "svr",
    "iaea", "nato", "fatf", "swift", "ofac",
})

DOMAIN_CONCEPTS = frozenset({
    "terror", "terrorism", "terrorist",
    "missile", "rocket", "drone", "uav", "ballistic",
    "nuclear", "enrichment", "uranium", "centrifuge", "plutonium",
    "chemical", "biological", "wmd",
    "militia", "proxy", "insurgent",
    "assassination", "kidnapping", "hostage",
    "cyber", "cyberattack", "hack", "malware", "ransomware",
    "espionage", "intelligence", "surveillance", "covert",
    "sanctions", "sanctioned",
    "laundering", "hawala",
    "smuggling", "trafficking", "narcotics",
    "regime", "ayatollah", "khamenei",
    "coup", "revolution", "uprising", "protest",
    "war", "conflict", "ceasefire", "truce",
    "airstrike", "strike", "raid", "incursion", "invasion",
    "occupation", "blockade", "siege",
    "casualty", "casualties", "killed", "wounded", "martyr",
})


def load_edge_gazetteer() -> frozenset:
    """Return combined edge domain gazetteer (~300 terms)."""
    return DOMAIN_LOCATIONS | DOMAIN_ORGANIZATIONS | DOMAIN_CONCEPTS
