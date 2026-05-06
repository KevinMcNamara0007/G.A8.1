"""
G.A8.1 — M2 Edge DC bundle exporter.

Reads INDEX_PATH, computes per-file SHA-256, builds a signed manifest,
writes everything as a tar archive at BUNDLE_PATH.

Usage:
    python3 -m tools.bundle_export
    A81_BUNDLE_PATH=/tmp/bundle.tar python3 -m tools.bundle_export

Required config when invoked:
    A81_INDEX_PATH               source directory
    A81_BUNDLE_PATH              destination tar path
    A81_BUNDLE_SIGNING_KEY_REF   KMS ref for HMAC key derivation
    A81_KMS_PROVIDER             must not be 'none'
"""

from __future__ import annotations

import io
import sys
import tarfile
from pathlib import Path

# config + kms are at the package root; let this run as a script too.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import cfg, ConfigError, EDGE_DC                     # noqa: E402
from kms import get_kms                                           # noqa: E402
from tools.bundle_manifest import (                               # noqa: E402
    Manifest, PROFILE_FILENAME, collect_files,
    has_profile, random_bundle_id, sign_manifest, utc_now_iso,
)


SIGNING_KEY_LENGTH = 32   # HMAC-SHA-256 prefers ≥ 32 bytes


def export_bundle(
    *,
    index_path: Path,
    bundle_path: Path,
    signing_key_ref: str,
    require_profile: bool,
    delta_base: str = "",
) -> Manifest:
    """Build manifest, optionally KMS-sign it, write the tar.

    When `signing_key_ref` is empty the bundle is UNSIGNED: per-file
    SHA-256 still travels in the manifest and is enforced on import,
    but no manifest.sig is written. Caller is responsible for trusted
    transport (e.g., SSH) — the M1→edge ship path uses this mode.
    """
    if not index_path.is_dir():
        raise ConfigError(f"INDEX_PATH does not exist or is not a directory: {index_path}")

    files = collect_files(index_path)
    if not files:
        raise ConfigError(f"INDEX_PATH is empty: {index_path}")

    profile_present = has_profile(files)
    if require_profile and not profile_present:
        raise ConfigError(
            f"{PROFILE_FILENAME} is required in the bundle but is not present "
            f"under {index_path}. Run the corpus profiler before export, or set "
            "A81_BUNDLE_INCLUDE_PROFILE=false to override (not recommended — "
            "edge has no corpus to re-profile)."
        )

    manifest = Manifest(
        created_at=utc_now_iso(),
        bundle_id=random_bundle_id(),
        delta_base=delta_base,
        source_index_path=str(index_path),
        signing_key_ref=signing_key_ref,
        profile_present=profile_present,
        files=files,
    )

    manifest_json = manifest.to_json()
    signature: bytes = b""
    if signing_key_ref:
        kms = get_kms()
        signing_key = kms.key_for(signing_key_ref, SIGNING_KEY_LENGTH, context="bundle-signing")
        signature = sign_manifest(manifest_json, signing_key)

    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(bundle_path, "w") as tar:
        # Manifest first so importers can stream-verify before extracting payload.
        manifest_bytes = manifest_json.encode("utf-8")
        info = tarfile.TarInfo("manifest.json")
        info.size = len(manifest_bytes)
        info.mode = 0o644
        tar.addfile(info, io.BytesIO(manifest_bytes))

        if signature:
            info = tarfile.TarInfo("manifest.sig")
            info.size = len(signature)
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(signature))

        for entry in files:
            src = index_path / entry.path
            info = tarfile.TarInfo(f"payload/{entry.path}")
            info.size = entry.size
            info.mode = entry.mode
            with src.open("rb") as fh:
                tar.addfile(info, fh)

    return manifest


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Export an Edge DC bundle.")
    parser.add_argument(
        "--unsigned", action="store_true",
        help="Skip KMS signing. Per-file SHA-256 still enforced on import. "
             "Use only when transport is independently authenticated (e.g., SSH).",
    )
    args = parser.parse_args()

    # Honor INDEX_PATH-only deployments: assert_ready_for would fail because
    # bundle export is the very thing being run. We do a thinner check here.
    if not cfg.INDEX_PATH:
        raise ConfigError("A81_INDEX_PATH is required for bundle export")
    if not cfg.BUNDLE_PATH:
        raise ConfigError("A81_BUNDLE_PATH is required for bundle export")

    signing_key_ref = "" if args.unsigned else cfg.BUNDLE_SIGNING_KEY_REF
    if signing_key_ref and cfg.KMS_PROVIDER == "none":
        raise ConfigError(
            "bundle signing requested but A81_KMS_PROVIDER=none. "
            "Either set a KMS provider or pass --unsigned."
        )

    manifest = export_bundle(
        index_path=Path(cfg.INDEX_PATH),
        bundle_path=Path(cfg.BUNDLE_PATH),
        signing_key_ref=signing_key_ref,
        require_profile=cfg.BUNDLE_INCLUDE_PROFILE,
        delta_base=cfg.BUNDLE_DELTA_BASE,
    )
    sig_state = "unsigned" if not signing_key_ref else f"signed:{signing_key_ref}"
    print(f"exported bundle_id={manifest.bundle_id} files={len(manifest.files)} "
          f"profile={'yes' if manifest.profile_present else 'no'} "
          f"{sig_state} -> {cfg.BUNDLE_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
