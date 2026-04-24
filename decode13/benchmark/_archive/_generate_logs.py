"""Generate a synthetic application-logs corpus for v13.1 sweep testing.

Realistic structure: multiple services × event types × parameterized
templates. The vocabulary shape matches what production log ingest
benchmarks look like — short lines with mixed structured fields and
free-text payload.

Output: corpus JSONL + query JSONL.

Corpus: N records of shape
    {"doc_id": int, "text": "...", "service": "...", "level": "...",
     "event": "..."}

Queries: for the given corpus, the task is "find the source log given
a paraphrase." We mask 2-3 tokens from each gold record to build the
query; gold_ids = [source doc_id]. This mirrors the edge-benchmark
methodology.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path


SERVICES = ["auth", "api", "db", "worker", "frontend", "cache", "scheduler",
            "billing", "search", "analytics", "inventory", "notification"]
LEVELS = ["INFO", "INFO", "INFO", "WARN", "ERROR", "DEBUG"]  # weighted
USERNAMES = ["alice", "bob", "carol", "dave", "eve", "frank", "gina",
              "hector", "ivana", "jorge", "kira", "lynn", "manny", "nora"]
ENDPOINTS = ["users", "orders", "payments", "products", "sessions",
              "tokens", "metrics", "reports", "webhooks", "notifications"]
STATUSES = ["ok", "timeout", "rejected", "retry", "cancelled", "pending"]
ENV = ["prod", "staging", "canary", "dev"]


TEMPLATES = [
    # format string, structured params
    ("{svc} {lvl} GET /api/{ep}/{user_id} status={status} latency_ms={lat}",
     ["svc", "lvl", "ep", "user_id", "status", "lat"]),
    ("{svc} {lvl} POST /api/{ep} user={un} status={status} bytes={nb}",
     ["svc", "lvl", "ep", "un", "status", "nb"]),
    ("{svc} {lvl} auth login user={un} result={status} src_ip={ip}",
     ["svc", "lvl", "un", "status", "ip"]),
    ("{svc} {lvl} db query took {lat}ms rows={nr} shard={sh}",
     ["svc", "lvl", "lat", "nr", "sh"]),
    ("{svc} {lvl} worker job_id={jid} status={status} duration_ms={lat}",
     ["svc", "lvl", "jid", "status", "lat"]),
    ("{svc} {lvl} cache hit={hit} miss={miss} key_prefix={pfx}",
     ["svc", "lvl", "hit", "miss", "pfx"]),
    ("{svc} {lvl} scheduler task={task} enqueued delay={delay}s",
     ["svc", "lvl", "task", "delay"]),
    ("{svc} {lvl} billing charge user={un} amount={amt} currency={cur}",
     ["svc", "lvl", "un", "amt", "cur"]),
    ("{svc} {lvl} search query_len={qlen} results={nr} latency_ms={lat}",
     ["svc", "lvl", "qlen", "nr", "lat"]),
    ("{svc} {lvl} analytics event={evt} user={un} session={sid}",
     ["svc", "lvl", "evt", "un", "sid"]),
    ("{svc} {lvl} healthcheck svc={dep} status={status} rtt_ms={lat}",
     ["svc", "lvl", "dep", "status", "lat"]),
    ("{svc} {lvl} request_id={rid} user={un} endpoint={ep} status={status}",
     ["svc", "lvl", "rid", "un", "ep", "status"]),
]


def _rand_ip(rng):
    return f"{rng.randint(10,192)}.{rng.randint(0,255)}.{rng.randint(0,255)}.{rng.randint(1,254)}"


def _sample(rng):
    tpl, keys = rng.choice(TEMPLATES)
    params = {
        "svc":    rng.choice(SERVICES),
        "lvl":    rng.choice(LEVELS),
        "ep":     rng.choice(ENDPOINTS),
        "user_id": rng.randint(100, 99_999),
        "status": rng.choice(STATUSES),
        "lat":    rng.randint(1, 4000),
        "un":     rng.choice(USERNAMES),
        "nb":     rng.randint(50, 65_000),
        "ip":     _rand_ip(rng),
        "nr":     rng.randint(0, 5000),
        "sh":     f"shard_{rng.randint(0, 63):02d}",
        "jid":    f"job_{rng.randint(10_000, 9_999_999)}",
        "hit":    rng.randint(0, 1000),
        "miss":   rng.randint(0, 500),
        "pfx":    rng.choice(["session:", "user:", "prod:", "item:", "tenant:"]),
        "task":   rng.choice(["reindex", "digest", "cleanup", "backup",
                              "replicate", "rotate_keys", "flush_cache"]),
        "delay":  rng.randint(5, 86400),
        "amt":    round(rng.uniform(0.5, 2500.0), 2),
        "cur":    rng.choice(["USD", "EUR", "GBP", "JPY", "CAD"]),
        "qlen":   rng.randint(2, 120),
        "evt":    rng.choice(["page_view", "click", "add_to_cart", "checkout",
                              "signup", "logout", "settings_changed"]),
        "sid":    f"sess_{rng.randint(1_000_000, 9_999_999)}",
        "dep":    rng.choice(SERVICES),
        "rid":    f"req_{rng.randint(10_000_000, 99_999_999)}",
    }
    text = tpl.format(**params)
    evt = tpl.split()[2] if len(tpl.split()) > 2 else "generic"
    return text, params["svc"], params["lvl"], evt


def mask_tokens(text: str, rng, n_mask: int = 2) -> str:
    """Produce a query variant by dropping/replacing n tokens."""
    toks = text.split()
    if len(toks) <= 2:
        return text
    idx = rng.sample(range(len(toks)), min(n_mask, len(toks) - 1))
    kept = [t for i, t in enumerate(toks) if i not in idx]
    return " ".join(kept)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-records", type=int, default=100_000)
    ap.add_argument("--n-queries", type=int, default=500)
    ap.add_argument("--out-dir", type=str, required=True)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(args.seed)

    t0 = time.perf_counter()
    corpus_path = out / "logs_corpus.jsonl"
    records = []
    with open(corpus_path, "w") as f:
        for i in range(args.n_records):
            text, svc, lvl, evt = _sample(rng)
            rec = {
                "doc_id": i, "text": text,
                "service": svc, "level": lvl, "event": evt,
            }
            records.append(rec)
            f.write(json.dumps(rec) + "\n")
    print(f"wrote {args.n_records:,} logs to {corpus_path} in "
          f"{time.perf_counter()-t0:.1f}s", file=sys.stderr)

    # Queries: sample gold records, mask 2-3 tokens for the query text.
    # Use records that are unlikely to collide — i.e. contain distinctive
    # numeric fields (user_id, request_id, job_id) that make the query
    # near-unique after masking.
    t0 = time.perf_counter()
    query_path = out / "logs_queries.jsonl"
    qrng = random.Random(args.seed + 1)
    gold_indices = qrng.sample(range(args.n_records), args.n_queries)
    with open(query_path, "w") as f:
        for idx in gold_indices:
            rec = records[idx]
            qtext = mask_tokens(rec["text"], qrng,
                                 n_mask=qrng.choice([2, 3]))
            f.write(json.dumps({
                "query_text": qtext,
                "gold_ids": [idx],
                "full_gold_text": rec["text"],
            }) + "\n")
    print(f"wrote {args.n_queries} queries to {query_path} in "
          f"{time.perf_counter()-t0:.1f}s", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
