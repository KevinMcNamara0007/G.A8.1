"""
G.A8.1 — M2 Edge DC bundle importer.

Reads a tar bundle produced by bundle_export, verifies the signature
against the configured KMS-derived key, and extracts the payload to
INDEX_PATH only after every file's hash matches the manifest.

Usage:
    python3 -m tools.bundle_import
    A81_BUNDLE_PATH=/tmp/bundle.tar python3 -m tools.bundle_import
"""

from __future__ import annotations

import hashlib
import sys
import tarfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import cfg, ConfigError, EDGE_DC                     # noqa: E402
from kms import get_kms                                           # noqa: E402
from tools.bundle_manifest import (                               # noqa: E402
    Manifest, PROFILE_FILENAME, hash_file, has_profile, verify_manifest,
)
from tools.bundle_export import SIGNING_KEY_LENGTH                # noqa: E402


def import_bundle(
    *,
    bundle_path: Path,
    target_dir: Path,
    require_profile: bool,
    verify_signature: bool,
) -> Manifest:
    """Verify and extract a bundle.

    Order:
      1. Open tar; locate manifest.json + manifest.sig.
      2. Derive signing key via KMS using manifest.signing_key_ref.
      3. Verify signature. Bail on failure when verify_signature=True.
      4. Profile gate: bail if require_profile and manifest lacks corpus_profile.json.
      5. Extract payload/* into target_dir.
      6. Re-hash every extracted file; bail on any mismatch.
    """
    if not bundle_path.is_file():
        raise ConfigError(f"bundle not found: {bundle_path}")

    with tarfile.open(bundle_path, "r") as tar:
        try:
            mf_member = tar.getmember("manifest.json")
        except KeyError as e:
            raise ConfigError(f"bundle is missing required member: {e}") from e

        mf_bytes = _read_member(tar, mf_member)
        manifest_json = mf_bytes.decode("utf-8")
        manifest = Manifest.from_json(manifest_json)

        # Signature handling: empty signing_key_ref means unsigned bundle
        # (M1 ship-over-SSH path). Per-file SHA-256 below still enforced.
        unsigned = not manifest.signing_key_ref
        if unsigned:
            try:
                tar.getmember("manifest.sig")
                # Bundle claims unsigned but carries a sig file — refuse rather
                # than silently ignore.
                raise ConfigError(
                    "bundle has empty signing_key_ref but a manifest.sig is "
                    "present. Refusing to import: provenance is ambiguous."
                )
            except KeyError:
                pass
            if verify_signature:
                # The runtime asked us to verify, but the bundle is unsigned.
                # Surface this as an explicit operator decision rather than
                # auto-downgrading.
                raise ConfigError(
                    "A81_BUNDLE_VERIFY_ON_LOAD=true but bundle is unsigned "
                    "(empty signing_key_ref). Set A81_BUNDLE_VERIFY_ON_LOAD=false "
                    "to import unsigned bundles, or re-export with a signing key."
                )
        else:
            try:
                sig_member = tar.getmember("manifest.sig")
            except KeyError as e:
                raise ConfigError(
                    f"bundle declares signing_key_ref={manifest.signing_key_ref!r} "
                    "but manifest.sig is missing"
                ) from e
            sig_bytes = _read_member(tar, sig_member)
            if verify_signature:
                kms = get_kms()
                key = kms.key_for(
                    manifest.signing_key_ref, SIGNING_KEY_LENGTH, context="bundle-signing"
                )
                if not verify_manifest(manifest_json, sig_bytes, key):
                    raise ConfigError(
                        f"bundle signature verification FAILED for bundle_id={manifest.bundle_id} "
                        f"signing_key_ref={manifest.signing_key_ref!r}. Refusing to extract."
                    )

        if require_profile and not (manifest.profile_present and has_profile(manifest.files)):
            raise ConfigError(
                f"bundle does not contain {PROFILE_FILENAME} but A81_BUNDLE_INCLUDE_PROFILE=true. "
                "Edge cannot proceed without a corpus profile."
            )

        target_dir.mkdir(parents=True, exist_ok=True)
        for entry in manifest.files:
            member_name = f"payload/{entry.path}"
            try:
                member = tar.getmember(member_name)
            except KeyError as e:
                raise ConfigError(
                    f"manifest references {entry.path} but bundle is missing {member_name}"
                ) from e
            dest = target_dir / entry.path
            dest.parent.mkdir(parents=True, exist_ok=True)
            with tar.extractfile(member) as src, dest.open("wb") as out:
                _copy_with_hash_check(src, out, entry.size, entry.sha256, entry.path)
            try:
                dest.chmod(entry.mode)
            except OSError:
                pass

    return manifest


def _read_member(tar: tarfile.TarFile, member: tarfile.TarInfo) -> bytes:
    f = tar.extractfile(member)
    if f is None:
        raise ConfigError(f"failed to read tar member: {member.name}")
    try:
        return f.read()
    finally:
        f.close()


def _copy_with_hash_check(src, out, expected_size: int, expected_sha: str, name: str) -> None:
    h = hashlib.sha256()
    written = 0
    while True:
        buf = src.read(1 << 20)
        if not buf:
            break
        h.update(buf)
        out.write(buf)
        written += len(buf)
    if written != expected_size:
        raise ConfigError(
            f"size mismatch for {name}: manifest={expected_size} extracted={written}"
        )
    actual = h.hexdigest()
    if actual != expected_sha:
        raise ConfigError(
            f"hash mismatch for {name}: manifest={expected_sha} extracted={actual}"
        )


def main() -> int:
    if not cfg.BUNDLE_PATH:
        raise ConfigError("A81_BUNDLE_PATH is required for bundle import")
    if not cfg.INDEX_PATH:
        raise ConfigError("A81_INDEX_PATH is required for bundle import")

    manifest = import_bundle(
        bundle_path=Path(cfg.BUNDLE_PATH),
        target_dir=Path(cfg.INDEX_PATH),
        require_profile=cfg.BUNDLE_INCLUDE_PROFILE,
        verify_signature=cfg.BUNDLE_VERIFY_ON_LOAD,
    )
    sig_state = "unsigned" if not manifest.signing_key_ref else f"signed:{manifest.signing_key_ref}"
    print(f"imported bundle_id={manifest.bundle_id} files={len(manifest.files)} "
          f"profile={'yes' if manifest.profile_present else 'no'} "
          f"{sig_state} -> {cfg.INDEX_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
