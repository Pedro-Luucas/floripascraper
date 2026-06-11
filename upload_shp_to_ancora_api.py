"""Upload SHP files from shp_camadas subfolders to ancora.craggroup.com via REST API.

POST /entry/mapas/upload?name=<subfolder_name>
Multipart: one "files" field per file in the subfolder.

Usage:
    python upload_shp_to_ancora_api.py                    # dry run (list only)
    python upload_shp_to_ancora_api.py --run # actually upload
    python upload_shp_to_ancora_api.py --run --folder "zona azul"  # specific subfolder
    python upload_shp_to_ancora_api.py --run --base-url http://localhost:8000  # local dev
"""

import argparse
import logging
import time
from pathlib import Path
from collections import defaultdict
from urllib.parse import quote

import subprocess

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

SHP_CAMADAS_DIR = Path(__file__).parent / "data" / "shp_camadas"
BASE_URL = "https://ancora.craggroup.com/api/mapas"

# Required SHP sidecar extensions (all must be present for a valid upload)
SHP_REQUIRED = {".shp", ".shx", ".dbf", ".prj"}
SHP_OPTIONAL = {".cst", ".cpg", ".sbn", ".sbx", ".shp.xml"}
ALL_SHP_EXTENSIONS = SHP_REQUIRED | SHP_OPTIONAL


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------

def find_subfolders(shp_dir: Path, folder_filter: str | None = None) -> list[tuple[Path, str]]:
    """Return (subfolder_path, subfolder_name) for all subfolders that have SHP files."""
    results = []
    for subfolder in sorted(shp_dir.iterdir()):
        if not subfolder.is_dir():
            continue
        if folder_filter and folder_filter.lower() not in subfolder.name.lower():
            continue

        shp_files = [f for f in subfolder.iterdir() if f.suffix.lower() == ".shp"]
        if not shp_files:
            continue

        results.append((subfolder, subfolder.name))
    return results


def get_shapefile_files(folder: Path) -> tuple[list[Path], list[Path]]:
    """Return (required_files, optional_files) for all .shp sets in a folder.

    Groups by .shp stem so multi-shapefile folders are handled correctly.
    Returns flat lists of all unique required + optional files.
    """
    required: list[Path] = []
    optional: list[Path] = []

    for f in sorted(folder.iterdir()):
        if not f.is_file():
            continue
        ext = f.suffix.lower()
        if ext in SHP_REQUIRED:
            required.append(f)
        elif ext in SHP_OPTIONAL:
            optional.append(f)

    return required, optional


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------

def upload_folder(base_url: str, folder_name: str,
                   required: list[Path], optional: list[Path],
                   dry_run: bool = False) -> dict | None:
    """Upload one subfolder as a single layer via REST API.

    Returns the JSON response dict on success, None on failure.
    """
    all_files = required + optional
    stem = required[0].stem if required else Path(all_files[0].name).stem

    print(f"  URL: {base_url}/upload?name={quote(folder_name, safe='')}")
    print(f"  Files: {[f.name for f in all_files]}")

    if dry_run:
        logger.info(f"  [DRY] POST {base_url}/upload?name={quote(folder_name, safe='')}")
        logger.info(f"  [DRY]   files: {[f.name for f in all_files]}")
        return {}

    try:
        curl_cmd = [
            "curl", "-s", "-X", "POST",
            f"{base_url}/upload?name={quote(folder_name, safe='')}",
        ]
        for f in all_files:
            curl_cmd += ["-F", f"files=@{f}"]
        curl_cmd += ["--max-time", "300"]

        print(f"  CMD: {' '.join(curl_cmd[:5])} ... +{len(all_files)} files")
        result = subprocess.run(curl_cmd, capture_output=True, text=True, timeout=320)
        print(f"  stdout: {result.stdout[:300]}")
        print(f"  stderr: {result.stderr[:300]}")
        print(f"  returncode: {result.returncode}")

        if result.returncode != 0:
            logger.error(f"  ✗ curl failed (code {result.returncode}): {result.stderr[:200]}")
            return None

        import json
        resp_data = json.loads(result.stdout)
        layer_id = resp_data.get("layer_id", "?")
        feature_count = resp_data.get("feature_count", "?")
        status = resp_data.get("status", "?")
        logger.info(
            f"  ✓ {folder_name} → layer_id={layer_id}, "
            f"features={feature_count}, status={status}"
        )
        return resp_data
    except subprocess.TimeoutExpired as e:
        logger.error(f"  ✗ timeout: {e}")
        return None
    except Exception as e:
        logger.error(f"  ✗ {folder_name}: {e}")
        return None


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Upload SHP subfolders to ancora.craggroup.com via REST API"
    )
    parser.add_argument("--run", action="store_true",
                        help="Actually upload (default is dry-run)")
    parser.add_argument("--folder", "-f", type=str, default=None,
                        help="Only subfolders matching this string")
    parser.add_argument("--shp-dir", type=Path, default=SHP_CAMADAS_DIR)
    parser.add_argument("--base-url", type=str, default=BASE_URL)

    args = parser.parse_args()
    dry_run = not args.run

    if not args.shp_dir.exists():
        logger.error(f"Directory not found: {args.shp_dir}")
        return

    subfolders = find_subfolders(args.shp_dir, args.folder)
    if not subfolders:
        logger.warning("No subfolders with .shp files found!")
        return

    logger.info(f"Found {len(subfolders)} subfolders:")
    for folder, name in subfolders:
        req, opt = get_shapefile_files(folder)
        logger.info(f"  [{len(req)} req + {len(opt)} opt] {name}")

    print()

    if dry_run:
        logger.info("=== DRY RUN — run with --run to actually upload ===")
        return

    logger.info("=== Starting uploads ===")
    success = 0
    failed = 0

    for idx, (folder, folder_name) in enumerate(subfolders, start=1):
        logger.info(f"[{idx}/{len(subfolders)}] {folder_name}")
        req, opt = get_shapefile_files(folder)

        result = upload_folder(args.base_url, folder_name, req, opt, dry_run=False)
        if result:
            success += 1
        else:
            failed += 1

        # Be polite — small delay between requests
        time.sleep(0.5)

    print()
    logger.info("=" * 60)
    logger.info("UPLOAD SUMMARY")
    logger.info("=" * 60)
    logger.info(f"Total subfolders: {len(subfolders)}")
    logger.info(f"Successful:      {success}")
    logger.info(f"Failed:          {failed}")


if __name__ == "__main__":
    main()
