"""
M2 bundle round-trip + tamper-detection + profile-gate tests.
"""

from __future__ import annotations

import json
import os
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

# Resolve imports relative to the G.A8.1 package root.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _reset_modules():
    for m in ("config", "kms", "tools.bundle_export",
              "tools.bundle_import", "tools.bundle_manifest"):
        sys.modules.pop(m, None)


def _set_env(env: dict) -> None:
    for k in list(os.environ):
        if k.startswith("A81_"):
            del os.environ[k]
    os.environ.update(env)


def _write_corpus(root: Path, *, with_profile: bool = True) -> None:
    """Lay down a tiny synthetic INDEX_PATH."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "centroids.json").write_text(json.dumps({"k": 4}))
    (root / "_global_idf.json").write_text(json.dumps({"the": 0.1}))
    (root / "structural_v13").mkdir(exist_ok=True)
    (root / "structural_v13" / "lsh.bin").write_bytes(os.urandom(256))
    (root / "structural_v13" / "structural_v13.cfg").write_text("dim=16384\nk=128\n")
    if with_profile:
        (root / "corpus_profile.json").write_text(json.dumps({
            "recommended_dim": 4096,
            "recommended_k": 64,
            "source_hash": "deadbeef" * 8,
        }))


class BundleRoundTripTest(unittest.TestCase):

    def test_roundtrip_with_local_kms(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            src = d / "src_index"
            dst = d / "dst_index"
            kms_dir = d / "kms"
            bundle = d / "bundle.tar"
            _write_corpus(src)

            _set_env({
                "A81_MODALITY": "edge_dc",
                "A81_ROLE": "encoder",
                "A81_INDEX_PATH": str(src),
                "A81_BUNDLE_PATH": str(bundle),
                "A81_BUNDLE_SIGNING_KEY_REF": "test/signing/v1",
                "A81_KMS_PROVIDER": "local",
                "A81_KMS_LOCAL_DIR": str(kms_dir),
            })
            _reset_modules()
            from tools.bundle_export import export_bundle
            from tools.bundle_import import import_bundle
            from config import cfg

            mf_export = export_bundle(
                index_path=src,
                bundle_path=bundle,
                signing_key_ref=cfg.BUNDLE_SIGNING_KEY_REF,
                require_profile=True,
            )
            self.assertTrue(bundle.is_file())
            self.assertTrue(mf_export.profile_present)
            self.assertGreaterEqual(len(mf_export.files), 4)

            # Importer side — verify-and-extract.
            mf_import = import_bundle(
                bundle_path=bundle,
                target_dir=dst,
                require_profile=True,
                verify_signature=True,
            )
            self.assertEqual(mf_import.bundle_id, mf_export.bundle_id)

            # Every source file appears in dst with identical bytes.
            for entry in mf_export.files:
                self.assertEqual(
                    (src / entry.path).read_bytes(),
                    (dst / entry.path).read_bytes(),
                    f"mismatch for {entry.path}",
                )

    def test_tampered_bundle_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            src, dst, kms_dir = d / "src", d / "dst", d / "kms"
            bundle, tampered = d / "ok.tar", d / "bad.tar"
            _write_corpus(src)

            _set_env({
                "A81_MODALITY": "edge_dc",
                "A81_INDEX_PATH": str(src),
                "A81_BUNDLE_PATH": str(bundle),
                "A81_BUNDLE_SIGNING_KEY_REF": "test/signing/v1",
                "A81_KMS_PROVIDER": "local",
                "A81_KMS_LOCAL_DIR": str(kms_dir),
            })
            _reset_modules()
            from tools.bundle_export import export_bundle
            from tools.bundle_import import import_bundle
            from config import cfg, ConfigError

            export_bundle(
                index_path=src,
                bundle_path=bundle,
                signing_key_ref=cfg.BUNDLE_SIGNING_KEY_REF,
                require_profile=True,
            )

            # Tamper a payload byte in-place (preserve length so the hash check
            # — not the size check — is what catches it).
            import io
            with tarfile.open(bundle, "r") as src_tar, tarfile.open(tampered, "w") as out_tar:
                for member in src_tar.getmembers():
                    f = src_tar.extractfile(member)
                    data = f.read() if f is not None else b""
                    if member.name == "payload/centroids.json":
                        data = b"X" + data[1:]   # flip first byte; same length
                    out_tar.addfile(member, io.BytesIO(data))

            with self.assertRaises(ConfigError) as ctx:
                import_bundle(
                    bundle_path=tampered,
                    target_dir=dst,
                    require_profile=True,
                    verify_signature=True,
                )
            self.assertIn("hash mismatch", str(ctx.exception))

    def test_signature_mismatch_rejected(self):
        """If we re-sign with a different key, import should refuse."""
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            src, dst, kms_dir = d / "src", d / "dst", d / "kms"
            bundle = d / "ok.tar"
            _write_corpus(src)

            _set_env({
                "A81_MODALITY": "edge_dc",
                "A81_INDEX_PATH": str(src),
                "A81_BUNDLE_PATH": str(bundle),
                "A81_BUNDLE_SIGNING_KEY_REF": "test/signing/v1",
                "A81_KMS_PROVIDER": "local",
                "A81_KMS_LOCAL_DIR": str(kms_dir),
            })
            _reset_modules()
            from tools.bundle_export import export_bundle
            from tools.bundle_import import import_bundle
            from config import cfg, ConfigError

            export_bundle(
                index_path=src,
                bundle_path=bundle,
                signing_key_ref=cfg.BUNDLE_SIGNING_KEY_REF,
                require_profile=True,
            )

            # Wipe the local KMS dir so a fresh signing key is generated.
            for p in kms_dir.iterdir():
                p.unlink()

            with self.assertRaises(ConfigError) as ctx:
                import_bundle(
                    bundle_path=bundle,
                    target_dir=dst,
                    require_profile=True,
                    verify_signature=True,
                )
            self.assertIn("signature verification FAILED", str(ctx.exception))

    def test_unsigned_roundtrip(self):
        """M1→edge over SSH: signing optional, hashes still mandatory."""
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            src, dst = d / "src", d / "dst"
            bundle = d / "ok.tar"
            _write_corpus(src)

            _set_env({
                "A81_MODALITY": "edge_dc",
                "A81_INDEX_PATH": str(src),
                "A81_BUNDLE_PATH": str(bundle),
                # No KMS, no signing key — pure unsigned ship.
                "A81_KMS_PROVIDER": "none",
            })
            _reset_modules()
            from tools.bundle_export import export_bundle
            from tools.bundle_import import import_bundle

            mf = export_bundle(
                index_path=src, bundle_path=bundle,
                signing_key_ref="",   # unsigned
                require_profile=True,
            )
            self.assertEqual(mf.signing_key_ref, "")

            # Verify-on-load=False is required for unsigned bundles.
            mf2 = import_bundle(
                bundle_path=bundle, target_dir=dst,
                require_profile=True, verify_signature=False,
            )
            self.assertEqual(mf2.bundle_id, mf.bundle_id)
            for entry in mf.files:
                self.assertEqual(
                    (src / entry.path).read_bytes(),
                    (dst / entry.path).read_bytes(),
                )

    def test_unsigned_with_verify_on_load_rejected(self):
        """Unsigned bundle + verify-on-load=true → refuse, don't auto-downgrade."""
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            src, dst = d / "src", d / "dst"
            bundle = d / "ok.tar"
            _write_corpus(src)

            _set_env({
                "A81_MODALITY": "edge_dc",
                "A81_INDEX_PATH": str(src),
                "A81_BUNDLE_PATH": str(bundle),
                "A81_KMS_PROVIDER": "none",
            })
            _reset_modules()
            from tools.bundle_export import export_bundle
            from tools.bundle_import import import_bundle
            from config import ConfigError

            export_bundle(
                index_path=src, bundle_path=bundle,
                signing_key_ref="",
                require_profile=True,
            )
            with self.assertRaises(ConfigError) as ctx:
                import_bundle(
                    bundle_path=bundle, target_dir=dst,
                    require_profile=True, verify_signature=True,
                )
            self.assertIn("unsigned", str(ctx.exception))

    def test_unsigned_bundle_still_hash_checks_files(self):
        """Tampering an unsigned bundle is still caught by per-file hashes."""
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            src, dst = d / "src", d / "dst"
            bundle, tampered = d / "ok.tar", d / "bad.tar"
            _write_corpus(src)

            _set_env({
                "A81_MODALITY": "edge_dc",
                "A81_INDEX_PATH": str(src),
                "A81_BUNDLE_PATH": str(bundle),
                "A81_KMS_PROVIDER": "none",
            })
            _reset_modules()
            from tools.bundle_export import export_bundle
            from tools.bundle_import import import_bundle
            from config import ConfigError

            export_bundle(
                index_path=src, bundle_path=bundle,
                signing_key_ref="",
                require_profile=True,
            )

            import io
            with tarfile.open(bundle, "r") as src_tar, tarfile.open(tampered, "w") as out_tar:
                for member in src_tar.getmembers():
                    f = src_tar.extractfile(member)
                    data = f.read() if f is not None else b""
                    if member.name == "payload/centroids.json":
                        data = b"X" + data[1:]
                    out_tar.addfile(member, io.BytesIO(data))

            with self.assertRaises(ConfigError) as ctx:
                import_bundle(
                    bundle_path=tampered, target_dir=dst,
                    require_profile=True, verify_signature=False,
                )
            self.assertIn("hash mismatch", str(ctx.exception))

    def test_profile_gate_export(self):
        """Export must abort when profile is missing and gate is on."""
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            src, kms_dir = d / "src", d / "kms"
            bundle = d / "x.tar"
            _write_corpus(src, with_profile=False)

            _set_env({
                "A81_MODALITY": "edge_dc",
                "A81_INDEX_PATH": str(src),
                "A81_BUNDLE_PATH": str(bundle),
                "A81_BUNDLE_SIGNING_KEY_REF": "test/signing/v1",
                "A81_KMS_PROVIDER": "local",
                "A81_KMS_LOCAL_DIR": str(kms_dir),
            })
            _reset_modules()
            from tools.bundle_export import export_bundle
            from config import cfg, ConfigError

            with self.assertRaises(ConfigError) as ctx:
                export_bundle(
                    index_path=src,
                    bundle_path=bundle,
                    signing_key_ref=cfg.BUNDLE_SIGNING_KEY_REF,
                    require_profile=True,
                )
            self.assertIn("corpus_profile.json", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
