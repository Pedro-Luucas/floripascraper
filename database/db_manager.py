"""JSON-based database manager for FloripaScraper.

Provides simple JSON file storage for scraper data without SQLite dependencies.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def get_data_dir() -> Path:
    """Return the path to the database directory.

    Returns:
        Path: Absolute path to the database/ directory.
    """
    base_dir = Path(__file__).parent.parent.resolve()
    data_dir = base_dir / "database"
    logger.debug("Data directory path: %s", data_dir)
    return data_dir


def load_json(table_name: str) -> list[dict]:
    """Load existing data from a JSON file.

    Args:
        table_name: Name of the table/file (without .json extension).

    Returns:
        List of records loaded from the file, or empty list if file doesn't exist.
    """
    file_path = get_data_dir() / f"{table_name}.json"
    logger.debug("Loading JSON from: %s", file_path)

    if not file_path.exists():
        logger.info("JSON file does not exist, returning empty list: %s", table_name)
        return []

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        records = data.get("records", [])
        logger.info("Loaded %d records from %s", len(records), table_name)
        return records
    except json.JSONDecodeError as e:
        logger.error("Failed to decode JSON from %s: %s", file_path, e)
        return []
    except IOError as e:
        logger.error("Failed to read JSON file %s: %s", file_path, e)
        return []


def save_json(table_name: str, data: list[dict]) -> None:
    """Save data to a JSON file.

    Creates or overwrites the JSON file with the provided data.

    Args:
        table_name: Name of the table/file (without .json extension).
        data: List of records to save.
    """
    data_dir = get_data_dir()

    # Ensure database directory exists
    data_dir.mkdir(parents=True, exist_ok=True)

    file_path = data_dir / f"{table_name}.json"
    logger.debug("Saving JSON to: %s", file_path)

    # Load existing metadata if file exists
    metadata = {
        "created": datetime.now(timezone.utc).isoformat(),
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "record_count": len(data)
    }

    # Try to preserve created timestamp if file exists
    try:
        if file_path.exists():
            with open(file_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
            if "metadata" in existing and "created" in existing["metadata"]:
                metadata["created"] = existing["metadata"]["created"]
    except Exception as e:
        logger.warning("Could not read existing metadata: %s", e)

    payload = {
        "metadata": metadata,
        "records": data
    }

    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        logger.info("Saved %d records to %s", len(data), table_name)
    except IOError as e:
        logger.error("Failed to write JSON file %s: %s", file_path, e)
        raise


def append_data(
    table_name: str,
    data: dict | list[dict],
    metadata: dict | None = None
) -> int:
    """Append new records to a JSON file.

    Args:
        table_name: Name of the table/file (without .json extension).
        data: Single record dict or list of records to append.
        metadata: Optional metadata dict to merge with existing metadata.

    Returns:
        Number of records actually appended.
    """
    # Normalize input to list
    if isinstance(data, dict):
        records_to_add = [data]
    else:
        records_to_add = data

    count = len(records_to_add)
    logger.debug("Appending %d records to %s", count, table_name)

    # Load existing records
    existing_records = load_json(table_name)

    # Append new records
    existing_records.extend(records_to_add)

    # Update metadata
    data_dir = get_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)

    file_path = data_dir / f"{table_name}.json"

    # Get created timestamp if file exists
    created = None
    if file_path.exists():
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
            if "metadata" in existing and "created" in existing["metadata"]:
                created = existing["metadata"]["created"]
        except Exception as e:
            logger.warning("Could not read existing metadata: %s", e)

    new_metadata = {
        "created": created or datetime.now(timezone.utc).isoformat(),
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "record_count": len(existing_records)
    }

    # Merge additional metadata if provided
    if metadata:
        new_metadata.update(metadata)

    payload = {
        "metadata": new_metadata,
        "records": existing_records
    }

    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        logger.info("Appended %d records to %s (total: %d)", count, table_name, len(existing_records))
        return count
    except IOError as e:
        logger.error("Failed to append to JSON file %s: %s", file_path, e)
        raise


def get_record_count(table_name: str) -> int:
    """Get the count of records in a table.

    Args:
        table_name: Name of the table/file (without .json extension).

    Returns:
        Number of records in the table, or 0 if file doesn't exist.
    """
    file_path = get_data_dir() / f"{table_name}.json"
    logger.debug("Getting record count for: %s", table_name)

    if not file_path.exists():
        logger.debug("File does not exist, returning 0 for: %s", table_name)
        return 0

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        count = len(data.get("records", []))
        logger.debug("Record count for %s: %d", table_name, count)
        return count
    except json.JSONDecodeError as e:
        logger.error("Failed to decode JSON from %s: %s", file_path, e)
        return 0
    except IOError as e:
        logger.error("Failed to read JSON file %s: %s", file_path, e)
        return 0