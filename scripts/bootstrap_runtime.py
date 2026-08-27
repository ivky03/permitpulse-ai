"""Download and verify the small runtime artifact bundle when needed."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile

import requests

from scripts import manage_demo_artifacts


MAX_BUNDLE_BYTES = 100 * 1024 * 1024


def artifacts_present() -> bool:
    return all(
        (manage_demo_artifacts.ARTIFACTS / name).is_file()
        for name in manage_demo_artifacts.RUNTIME_FILES
    )


def download_bundle(url: str, destination: Path) -> None:
    downloaded = 0
    with requests.get(url, stream=True, timeout=(10, 120)) as response:
        response.raise_for_status()
        declared = int(response.headers.get("content-length", "0") or 0)
        if declared > MAX_BUNDLE_BYTES:
            raise ValueError("Runtime artifact bundle exceeds the 100 MB limit.")
        with destination.open("wb") as output:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                downloaded += len(chunk)
                if downloaded > MAX_BUNDLE_BYTES:
                    raise ValueError("Runtime artifact bundle exceeds the 100 MB limit.")
                output.write(chunk)


def bootstrap() -> str:
    if artifacts_present():
        return "Runtime artifacts already present."
    url = os.getenv("PERMITPULSE_ARTIFACT_BUNDLE_URL", "").strip()
    if not url:
        raise RuntimeError(
            "Runtime artifacts are missing. Set PERMITPULSE_ARTIFACT_BUNDLE_URL "
            "to a verified permitpulse-demo-artifacts.tar.gz release asset."
        )
    with tempfile.TemporaryDirectory() as directory:
        bundle = Path(directory) / "permitpulse-demo-artifacts.tar.gz"
        download_bundle(url, bundle)
        manifest = manage_demo_artifacts.install(bundle)
    return f"Installed {len(manifest['files'])} verified runtime artifacts."


if __name__ == "__main__":
    print(bootstrap())
