"""Build or install the small runtime-artifact bundle used by the public demo."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import tarfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "artifacts"
RUNTIME_FILES = (
    "permit_delay_model.joblib",
    "comparables.duckdb",
    "model_metadata.json",
)


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def add_bytes(archive: tarfile.TarFile, name: str, content: bytes) -> None:
    info = tarfile.TarInfo(name=name)
    info.size = len(content)
    info.mtime = 0
    info.mode = 0o644
    archive.addfile(info, io.BytesIO(content))


def build(output: Path) -> dict:
    missing = [name for name in RUNTIME_FILES if not (ARTIFACTS / name).exists()]
    if missing:
        raise FileNotFoundError(
            f"Missing runtime artifacts {missing}. Train the model and build the index first."
        )
    files = {}
    contents = {}
    for name in RUNTIME_FILES:
        content = (ARTIFACTS / name).read_bytes()
        contents[name] = content
        files[name] = {"size_bytes": len(content), "sha256": sha256_bytes(content)}
    manifest = {
        "format_version": 1,
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "Reproducible PermitPulse Stage 1-3 pipeline",
        "files": files,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output, "w:gz") as archive:
        add_bytes(
            archive,
            "artifact_manifest.json",
            json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8"),
        )
        for name, content in contents.items():
            add_bytes(archive, f"artifacts/{name}", content)
    return manifest


def install(bundle: Path) -> dict:
    with tarfile.open(bundle, "r:gz") as archive:
        names = set(archive.getnames())
        expected = {"artifact_manifest.json", *(f"artifacts/{name}" for name in RUNTIME_FILES)}
        if names != expected:
            raise ValueError("Bundle contains unexpected or missing files.")
        manifest_file = archive.extractfile("artifact_manifest.json")
        if manifest_file is None:
            raise ValueError("Artifact manifest is missing.")
        manifest = json.load(manifest_file)
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        for name in RUNTIME_FILES:
            member = archive.extractfile(f"artifacts/{name}")
            if member is None:
                raise ValueError(f"Bundle is missing {name}.")
            content = member.read()
            expected_hash = manifest["files"][name]["sha256"]
            if sha256_bytes(content) != expected_hash:
                raise ValueError(f"Hash verification failed for {name}.")
            (ARTIFACTS / name).write_bytes(content)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    build_parser = subparsers.add_parser("build")
    build_parser.add_argument("bundle", type=Path)
    install_parser = subparsers.add_parser("install")
    install_parser.add_argument("bundle", type=Path)
    args = parser.parse_args()
    result = build(args.bundle) if args.command == "build" else install(args.bundle)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
