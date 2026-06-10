"""Retry handler module for FloripaScraper.

Provides functionality for tracking and retrying failed URLs,
including the FailedUrlTracker class and integration with BaseScraper.
"""

import json
import logging
import os
from datetime import datetime
from typing import Any

# Configure module logger
logger = logging.getLogger(__name__)

# Default path for failed URLs storage
DEFAULT_FAILED_URLS_PATH = os.path.join(
    os.path.dirname(__file__), "..", "database", "failed_urls.json"
)

# Default maximum retry attempts
DEFAULT_MAX_RETRIES = 3


class FailedUrlTracker:
    """Track and manage failed URLs for retry operations.

    Manages a JSON file containing failed URL records with metadata
    including scraper name, error message, timestamp, and retry count.

    Attributes:
        file_path: Path to the JSON file storing failed URLs.
        max_retries: Maximum number of retry attempts before giving up.
    """

    def __init__(self, file_path: str = DEFAULT_FAILED_URLS_PATH, max_retries: int = DEFAULT_MAX_RETRIES) -> None:
        """Initialize the FailedUrlTracker.

        Args:
            file_path: Path to the JSON file for storing failed URLs.
                       Defaults to database/failed_urls.json.
            max_retries: Maximum number of retry attempts for any URL.
                        Defaults to 3.
        """
        self.file_path = file_path
        self.max_retries = max_retries
        logger.info(f"Initialized FailedUrlTracker with file_path={self.file_path}, max_retries={self.max_retries}")

    def _load_data(self) -> dict[str, list[dict[str, Any]]]:
        """Load failed URLs data from JSON file.

        Returns:
            dict: Dictionary with 'failed_urls' key containing list of failed URL records.
                  Returns empty structure if file doesn't exist or is invalid.
        """
        if not os.path.exists(self.file_path):
            logger.debug(f"Failed URLs file not found at {self.file_path}, returning empty structure")
            return {"failed_urls": []}

        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                logger.debug(f"Loaded {len(data.get('failed_urls', []))} failed URLs from {self.file_path}")
                return data
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON from {self.file_path}: {e}. Returning empty structure.")
            return {"failed_urls": []}
        except IOError as e:
            logger.error(f"Failed to read {self.file_path}: {e}. Returning empty structure.")
            return {"failed_urls": []}

    def _save_data(self, data: dict[str, list[dict[str, Any]]]) -> bool:
        """Save failed URLs data to JSON file.

        Args:
            data: Dictionary with 'failed_urls' key containing list of failed URL records.

        Returns:
            bool: True if save was successful, False otherwise.
        """
        try:
            # Ensure directory exists
            os.makedirs(os.path.dirname(self.file_path), exist_ok=True)

            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            logger.debug(f"Saved {len(data.get('failed_urls', []))} failed URLs to {self.file_path}")
            return True
        except IOError as e:
            logger.error(f"Failed to write to {self.file_path}: {e}")
            return False

    def add_failed_url(
        self,
        url: str,
        scraper_name: str,
        error_message: str
    ) -> bool:
        """Add a new failed URL to the tracker.

        If the URL already exists for the same scraper, updates the error message
        and resets the retry count.

        Args:
            url: The URL that failed.
            scraper_name: Name of the scraper that attempted the URL.
            error_message: Description of the error that occurred.

        Returns:
            bool: True if URL was added/updated successfully, False otherwise.
        """
        data = self._load_data()
        failed_urls = data.get("failed_urls", [])

        # Check if URL already exists for this scraper
        existing_index = None
        for i, record in enumerate(failed_urls):
            if record.get("url") == url and record.get("scraper") == scraper_name:
                existing_index = i
                break

        timestamp = datetime.now().isoformat()

        if existing_index is not None:
            # Update existing record
            failed_urls[existing_index] = {
                "url": url,
                "scraper": scraper_name,
                "error": error_message,
                "first_failed": failed_urls[existing_index].get("first_failed", timestamp),
                "retry_count": 0  # Reset retry count on new failure
            }
            logger.info(f"Updated existing failed URL: {url} (scraper: {scraper_name})")
        else:
            # Add new record
            new_record = {
                "url": url,
                "scraper": scraper_name,
                "error": error_message,
                "first_failed": timestamp,
                "retry_count": 0
            }
            failed_urls.append(new_record)
            logger.info(f"Added new failed URL: {url} (scraper: {scraper_name})")

        data["failed_urls"] = failed_urls
        return self._save_data(data)

    def mark_url_retried(self, url: str, scraper_name: str) -> bool:
        """Mark a URL as retried by incrementing its retry count.

        Args:
            url: The URL that was retried.
            scraper_name: Name of the scraper that retried the URL.

        Returns:
            bool: True if URL was found and updated, False otherwise.
        """
        data = self._load_data()
        failed_urls = data.get("failed_urls", [])

        for record in failed_urls:
            if record.get("url") == url and record.get("scraper") == scraper_name:
                record["retry_count"] = record.get("retry_count", 0) + 1
                logger.debug(
                    f"Incremented retry count for {url} (scraper: {scraper_name}): "
                    f"now {record['retry_count']}"
                )
                data["failed_urls"] = failed_urls
                return self._save_data(data)

        logger.warning(f"URL not found for marking as retried: {url} (scraper: {scraper_name})")
        return False

    def remove_url(self, url: str, scraper_name: str) -> bool:
        """Remove a URL from the failed list (typically after successful retry).

        Args:
            url: The URL to remove.
            scraper_name: Name of the scraper associated with the URL.

        Returns:
            bool: True if URL was found and removed, False otherwise.
        """
        data = self._load_data()
        failed_urls = data.get("failed_urls", [])

        original_count = len(failed_urls)
        failed_urls = [
            record for record in failed_urls
            if not (record.get("url") == url and record.get("scraper") == scraper_name)
        ]

        if len(failed_urls) < original_count:
            data["failed_urls"] = failed_urls
            success = self._save_data(data)
            if success:
                logger.info(f"Removed URL from failed list: {url} (scraper: {scraper_name})")
            return success

        logger.warning(f"URL not found for removal: {url} (scraper: {scraper_name})")
        return False

    def get_urls_for_retry(self, scraper_name: str) -> list[dict[str, Any]]:
        """Get URLs that need retry for a specific scraper.

        Args:
            scraper_name: Name of the scraper to get failed URLs for.

        Returns:
            list: List of failed URL records with retry_count < max_retries.
        """
        data = self._load_data()
        failed_urls = data.get("failed_urls", [])

        urls_to_retry = [
            record for record in failed_urls
            if record.get("scraper") == scraper_name
            and record.get("retry_count", 0) < self.max_retries
        ]

        logger.debug(
            f"Found {len(urls_to_retry)} URLs needing retry for scraper '{scraper_name}' "
            f"(max_retries={self.max_retries})"
        )
        return urls_to_retry

    def get_failed_count(self, scraper_name: str | None = None) -> int:
        """Get count of failed URLs, optionally filtered by scraper.

        Args:
            scraper_name: Optional scraper name to filter by. If None,
                         returns total count of all failed URLs.

        Returns:
            int: Number of failed URLs matching the filter.
        """
        data = self._load_data()
        failed_urls = data.get("failed_urls", [])

        if scraper_name is None:
            return len(failed_urls)

        return len([r for r in failed_urls if r.get("scraper") == scraper_name])