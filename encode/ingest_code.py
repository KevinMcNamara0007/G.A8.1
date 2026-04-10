"""
G.A8.1 — Code Ingester

Crawls a codebase and extracts (subject, relation, object) triples from:
  - Python: functions, classes, imports, docstrings, decorators
  - C++: functions, classes, includes
  - Markdown: headers, links
  - Shell: functions, commands

Output: triples JSON compatible with A8.1 encode pipeline.
No domain-specific schema. The code IS the data.

Usage:
    python ingest_code.py --root /path/to/codebase --output code_triples.json
"""

import argparse
import ast
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import List, Dict


def _clean(text: str) -> str:
    """Normalize to lowercase underscored token."""
    return text.strip().lower().replace(" ", "_").replace("/", "_").replace(".", "_")


def extract_python(filepath: str) -> List[Dict]:
    """Extract triples from a Python file."""
    triples = []
    rel_path = os.path.basename(filepath).replace(".py", "")
    module = _clean(rel_path)

    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            source = f.read()
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return triples

    for node in ast.walk(tree):
        # Functions
        if isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
            func_name = _clean(node.name)
            triples.append({
                "subject": module,
                "relation": "defines_function",
                "object": func_name,
            })
            # Docstring
            docstring = ast.get_docstring(node)
            if docstring and len(docstring) > 10:
                first_line = docstring.split("\n")[0].strip()[:100]
                triples.append({
                    "subject": func_name,
                    "relation": "described_as",
                    "object": _clean(first_line),
                })
            # Arguments
            for arg in node.args.args:
                if arg.arg != "self":
                    triples.append({
                        "subject": func_name,
                        "relation": "has_parameter",
                        "object": _clean(arg.arg),
                    })
            # Decorators
            for dec in node.decorator_list:
                if isinstance(dec, ast.Name):
                    triples.append({
                        "subject": func_name,
                        "relation": "decorated_by",
                        "object": _clean(dec.id),
                    })

        # Classes
        elif isinstance(node, ast.ClassDef):
            class_name = _clean(node.name)
            triples.append({
                "subject": module,
                "relation": "defines_class",
                "object": class_name,
            })
            # Bases
            for base in node.bases:
                if isinstance(base, ast.Name):
                    triples.append({
                        "subject": class_name,
                        "relation": "extends",
                        "object": _clean(base.id),
                    })
                elif isinstance(base, ast.Attribute):
                    triples.append({
                        "subject": class_name,
                        "relation": "extends",
                        "object": _clean(base.attr),
                    })
            # Docstring
            docstring = ast.get_docstring(node)
            if docstring and len(docstring) > 10:
                first_line = docstring.split("\n")[0].strip()[:100]
                triples.append({
                    "subject": class_name,
                    "relation": "described_as",
                    "object": _clean(first_line),
                })

        # Imports
        elif isinstance(node, ast.Import):
            for alias in node.names:
                triples.append({
                    "subject": module,
                    "relation": "imports",
                    "object": _clean(alias.name),
                })
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                triples.append({
                    "subject": module,
                    "relation": "imports_from",
                    "object": _clean(node.module),
                })

    return triples


def extract_cpp(filepath: str) -> List[Dict]:
    """Extract triples from a C++/H file."""
    triples = []
    module = _clean(os.path.basename(filepath).split(".")[0])

    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            source = f.read()
    except Exception:
        return triples

    # Includes
    for m in re.finditer(r'#include\s*[<"](.+?)[>"]', source):
        triples.append({
            "subject": module,
            "relation": "includes",
            "object": _clean(m.group(1).split("/")[-1].split(".")[0]),
        })

    # Functions (simplified regex)
    for m in re.finditer(r'(?:[\w:]+\s+)?([\w]+)\s*\([^)]*\)\s*(?:const)?\s*\{', source):
        func = m.group(1)
        if func not in ("if", "for", "while", "switch", "catch", "else"):
            triples.append({
                "subject": module,
                "relation": "defines_function",
                "object": _clean(func),
            })

    # Classes/structs
    for m in re.finditer(r'(?:class|struct)\s+(\w+)', source):
        triples.append({
            "subject": module,
            "relation": "defines_class",
            "object": _clean(m.group(1)),
        })

    # Namespaces
    for m in re.finditer(r'namespace\s+(\w+)', source):
        triples.append({
            "subject": module,
            "relation": "in_namespace",
            "object": _clean(m.group(1)),
        })

    return triples


def extract_markdown(filepath: str) -> List[Dict]:
    """Extract triples from Markdown."""
    triples = []
    module = _clean(os.path.basename(filepath).replace(".md", ""))

    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            source = f.read()
    except Exception:
        return triples

    # Headers
    for m in re.finditer(r'^(#{1,4})\s+(.+)$', source, re.MULTILINE):
        level = len(m.group(1))
        heading = _clean(m.group(2)[:80])
        rel = ["", "has_title", "has_section", "has_subsection", "has_detail"][min(level, 4)]
        triples.append({
            "subject": module,
            "relation": rel,
            "object": heading,
        })

    return triples


def extract_shell(filepath: str) -> List[Dict]:
    """Extract triples from shell scripts."""
    triples = []
    module = _clean(os.path.basename(filepath).replace(".sh", ""))

    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            source = f.read()
    except Exception:
        return triples

    # Functions
    for m in re.finditer(r'(\w+)\s*\(\)\s*\{', source):
        triples.append({
            "subject": module,
            "relation": "defines_function",
            "object": _clean(m.group(1)),
        })

    return triples


EXTRACTORS = {
    ".py": extract_python,
    ".cpp": extract_cpp,
    ".hpp": extract_cpp,
    ".h": extract_cpp,
    ".c": extract_cpp,
    ".md": extract_markdown,
    ".sh": extract_shell,
}

# Skip directories
SKIP_DIRS = {
    "__pycache__", ".git", "node_modules", ".cache", "build",
    ".eggs", "dist", "venv", ".venv", ".tox",
}


def crawl(root: str) -> List[Dict]:
    """Crawl codebase and extract triples."""
    root = Path(root)
    all_triples = []
    file_count = 0

    for dirpath, dirnames, filenames in os.walk(root):
        # Skip build/cache dirs
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]

        for fname in filenames:
            ext = os.path.splitext(fname)[1].lower()
            if ext not in EXTRACTORS:
                continue

            filepath = os.path.join(dirpath, fname)
            # Skip very large files
            try:
                if os.path.getsize(filepath) > 500_000:
                    continue
            except OSError:
                continue

            extractor = EXTRACTORS[ext]
            triples = extractor(filepath)

            # Add file-level triple
            rel_path = os.path.relpath(filepath, root)
            module = _clean(os.path.basename(fname).split(".")[0])
            parent_dir = _clean(os.path.basename(dirpath))
            all_triples.append({
                "subject": module,
                "relation": "part_of",
                "object": parent_dir,
            })
            all_triples.append({
                "subject": module,
                "relation": "file_type",
                "object": ext.lstrip("."),
            })

            all_triples.extend(triples)
            file_count += 1

            if file_count % 500 == 0:
                print(f"  {file_count} files, {len(all_triples):,} triples...", flush=True)

    return all_triples, file_count


def main():
    p = argparse.ArgumentParser(description="A8.1 Code Ingester")
    p.add_argument("--root", required=True, help="Root directory to crawl")
    p.add_argument("--output", default="code_triples.json", help="Output JSON")
    args = p.parse_args()

    print("=" * 60)
    print("  G.A8.1 — Code Ingester")
    print("=" * 60)
    print(f"  Root: {args.root}")
    t0 = time.perf_counter()

    triples, file_count = crawl(args.root)

    elapsed = time.perf_counter() - t0
    print(f"\n  {file_count:,} files → {len(triples):,} triples in {elapsed:.1f}s")

    # Relation distribution
    from collections import Counter
    rels = Counter(t["relation"] for t in triples)
    print(f"\n  Relation types ({len(rels)}):")
    for r, c in rels.most_common(15):
        print(f"    {r:25s} {c:>8,}")

    with open(args.output, "w") as f:
        json.dump(triples, f)
    print(f"\n  Saved: {args.output}")
    print("=" * 60)


if __name__ == "__main__":
    main()
