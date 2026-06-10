"""Upload JSON files to CragAncoraCitys API.

This script sends locally saved JSON files to the API endpoint
for indexing in the chatbot and data-wall.

Usage:
    python upload_to_api.py              # Upload all JSON files
    python upload_to_api.py --file licitacoes.json
    python upload_to_api.py --file obras.json --check-status
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path

import requests

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# API Configuration
API_BASE = "https://ancora.craggroup.com"
API_UPLOAD_ENDPOINT = f"{API_BASE}/entry/documents"
API_STATUS_ENDPOINT = f"{API_BASE}/api/documents"


def upload_json_file(file_path: Path, delay: float = 1.0) -> dict | None:
    """Upload a single JSON file to the API.

    Args:
        file_path: Path to the JSON file.
        delay: Delay in seconds between requests.

    Returns:
        dict with response data or None if failed.
    """
    try:
        # Load the JSON file
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Extract metadata and records
        metadata = data.get("metadata", {})
        records = data.get("records", [])
        record_count = len(records)

        # Build title from filename
        title = file_path.stem.replace("_", " ").title()
        if record_count > 0:
            title = f"{title} ({record_count} registros)"

        # Get source from metadata if available
        fonte = metadata.get("source", metadata.get("fonte", file_path.stem))
        origin_url = metadata.get("url", metadata.get("origin_url", ""))

        # Prepare payload for API
        payload = {
            "title": title,
            "format": "json",
            "content": {
                "metadata": metadata,
                "records": records
            },
            "origin_url": origin_url
        }

        logger.info(f"Uploading: {file_path.name} ({record_count} records)")

        # Make request
        response = requests.post(
            API_UPLOAD_ENDPOINT,
            json=payload,
            timeout=60
        )

        if response.status_code == 200:
            result = response.json()
            doc_id = result.get("id", "unknown")
            logger.info(f"✓ Success: {file_path.name} -> id={doc_id}")
            return result
        else:
            logger.error(f"✗ Failed: {file_path.name} (HTTP {response.status_code})")
            logger.error(f"  Response: {response.text[:200]}")
            return None

    except json.JSONDecodeError as e:
        logger.error(f"✗ Invalid JSON in {file_path.name}: {e}")
        return None
    except requests.RequestException as e:
        logger.error(f"✗ Request failed for {file_path.name}: {e}")
        return None
    except Exception as e:
        logger.error(f"✗ Error processing {file_path.name}: {e}")
        return None


def check_document_status(doc_id: str) -> dict | None:
    """Check the status of an uploaded document.

    Args:
        doc_id: Document ID returned from upload.

    Returns:
        dict with status info or None if failed.
    """
    try:
        response = requests.get(
            f"{API_STATUS_ENDPOINT}/{doc_id}",
            timeout=30
        )

        if response.status_code == 200:
            return response.json()
        else:
            logger.error(f"Failed to check status for {doc_id}: HTTP {response.status_code}")
            return None

    except requests.RequestException as e:
        logger.error(f"Request failed checking status for {doc_id}: {e}")
        return None


def upload_all_jsons(
    data_dir: Path | None = None,
    delay: float = 1.5,
    wait_for_done: bool = False
) -> dict:
    """Upload all JSON files from the data directory.

    Args:
        data_dir: Path to data directory (default: ./data)
        delay: Delay between uploads in seconds.
        wait_for_done: If True, poll until all documents show 'done' status.

    Returns:
        Summary dict with upload results.
    """
    if data_dir is None:
        data_dir = Path(__file__).parent / "data"

    if not data_dir.exists():
        logger.error(f"Data directory not found: {data_dir}")
        return {"success": 0, "failed": 0, "documents": []}

    # Find all JSON files
    json_files = sorted(data_dir.glob("*.json"))

    if not json_files:
        logger.warning(f"No JSON files found in {data_dir}")
        return {"success": 0, "failed": 0, "documents": []}

    logger.info(f"Found {len(json_files)} JSON files to upload")
    logger.info(f"Data directory: {data_dir}")
    print()

    results = []
    success_count = 0
    failed_count = 0

    for i, file_path in enumerate(json_files, 1):
        logger.info(f"[{i}/{len(json_files)}] Processing {file_path.name}")

        result = upload_json_file(file_path, delay)

        if result:
            results.append({
                "file": file_path.name,
                "id": result.get("id"),
                "status": result.get("status"),
                "success": True
            })
            success_count += 1
        else:
            results.append({
                "file": file_path.name,
                "success": False
            })
            failed_count += 1

        # Rate limiting between uploads
        if i < len(json_files):
            time.sleep(delay)

    print()
    logger.info("=" * 60)
    logger.info("UPLOAD SUMMARY")
    logger.info("=" * 60)
    logger.info(f"Total files: {len(json_files)}")
    logger.info(f"Successful:  {success_count}")
    logger.info(f"Failed:      {failed_count}")

    # Wait for processing if requested
    if wait_for_done and success_count > 0:
        print()
        logger.info("Waiting for documents to be processed...")

        doc_ids = [r["id"] for r in results if r.get("id")]
        check_all_status(doc_ids, max_wait_minutes=5)

    return {
        "success": success_count,
        "failed": failed_count,
        "documents": results
    }


def check_all_status(doc_ids: list[str], max_wait_minutes: int = 5) -> None:
    """Poll document statuses until all are 'done' or timeout.

    Args:
        doc_ids: List of document IDs to check.
        max_wait_minutes: Maximum time to wait in minutes.
    """
    max_wait_seconds = max_wait_minutes * 60
    start_time = time.time()
    check_interval = 10  # seconds

    while time.time() - start_time < max_wait_seconds:
        statuses = {}
        all_done = True
        any_error = False

        for doc_id in doc_ids:
            status_info = check_document_status(doc_id)
            if status_info:
                status = status_info.get("status", "unknown")
                statuses[doc_id] = status
                if status == "error":
                    any_error = True
                elif status not in ("done", "processing", "pending"):
                    all_done = False
            else:
                statuses[doc_id] = "unknown"
                all_done = False

        # Log current status
        status_summary = ", ".join([f"{s}" for s in statuses.values()])
        elapsed = int(time.time() - start_time)
        logger.info(f"[{elapsed}s] Status: {status_summary}")

        if all_done and not any_error:
            logger.info("✓ All documents processed successfully!")
            return

        if any_error:
            logger.warning("Some documents have errors. Stopping wait.")
            return

        time.sleep(check_interval)

    logger.warning(f"Timeout waiting for documents after {max_wait_minutes} minutes")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Upload JSON files to CragAncoraCitys API"
    )
    parser.add_argument(
        "--file",
        "-f",
        help="Upload a specific file (default: upload all in data/)"
    )
    parser.add_argument(
        "--data-dir",
        "-d",
        type=Path,
        help="Data directory path (default: ./data)"
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.5,
        help="Delay between uploads in seconds (default: 1.5)"
    )
    parser.add_argument(
        "--check-status",
        "-c",
        action="store_true",
        help="Wait and poll status until all documents are 'done'"
    )
    parser.add_argument(
        "--status",
        "-s",
        help="Check status of a specific document by ID"
    )

    args = parser.parse_args()

    # Check specific document status
    if args.status:
        logger.info(f"Checking status for document: {args.status}")
        result = check_document_status(args.status)
        if result:
            print()
            print(json.dumps(result, indent=2, ensure_ascii=False))
        return

    # Upload specific file
    if args.file:
        file_path = Path(args.file)
        if not file_path.is_absolute():
            file_path = Path("data") / file_path

        logger.info(f"Uploading single file: {file_path}")
        result = upload_json_file(file_path, args.delay)
        if result:
            print()
            print(json.dumps(result, indent=2, ensure_ascii=False))
            logger.info("Upload successful!")
        else:
            logger.error("Upload failed!")
            sys.exit(1)
        return

    # Upload all files
    upload_all_jsons(args.data_dir, args.delay, args.check_status)


if __name__ == "__main__":
    main()