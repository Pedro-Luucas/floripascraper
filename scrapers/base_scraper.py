"""Base scraper module for FloripaScraper.

Provides a base class with common functionality for all scrapers,
including HTTP requests with retry logic, rate limiting, and database operations.
"""

import logging
import time
from typing import Any

import fake_useragent
import requests

from database.db_manager import append_data
from utils.retry_handler import FailedUrlTracker, DEFAULT_MAX_RETRIES

# Configure module logger
logger = logging.getLogger(__name__)

# Rate limiting: minimum seconds between requests
DEFAULT_RATE_LIMIT_DELAY = 1.0


class BaseScraper:
    """Base class for all scrapers.

    Provides common functionality for web scraping including:
    - Realistic HTTP headers with rotating User-Agent
    - Exponential backoff retry logic
    - Rate limiting between requests
    - Database operations via db_manager

    Attributes:
        name: Identifier for this scraper.
        base_url: Base URL for the target website.
        rate_limit_delay: Minimum delay between HTTP requests in seconds.
        _last_request_time: Timestamp of the last request for rate limiting.
        _user_agent: Cached User-Agent string.
    """

    def __init__(self, name: str, base_url: str, rate_limit_delay: float = DEFAULT_RATE_LIMIT_DELAY) -> None:
        """Initialize scraper with name and base URL.

        Args:
            name: Identifier for this scraper (e.g., "imovelweb", "zap").
            base_url: Base URL for the target website.
            rate_limit_delay: Minimum delay between requests in seconds (default: 1.0).
        """
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.rate_limit_delay = rate_limit_delay
        self._last_request_time: float = 0.0
        self._user_agent: str | None = None
        logger.info(f"Initialized {self.__class__.__name__}: name={name}, base_url={self.base_url}")

    def _get_headers(self) -> dict[str, str]:
        """Return realistic HTTP headers with User-Agent.

        Uses fake-useragent to generate a realistic browser User-Agent string.
        The User-Agent is cached for the lifetime of the scraper instance.

        Returns:
            dict: Dictionary of HTTP headers including User-Agent.
        """
        if self._user_agent is None:
            try:
                ua = fake_useragent.UserAgent(fallback="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
                self._user_agent = ua.random
            except Exception as e:
                logger.warning(f"Failed to generate User-Agent: {e}. Using fallback.")
                self._user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

        return {
            "User-Agent": self._user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Cache-Control": "max-age=0",
        }

    def _apply_rate_limit(self) -> None:
        """Apply rate limiting by sleeping if necessary.

        Ensures minimum time between requests to avoid overloading servers.
        Calculates time since last request and sleeps if needed.
        """
        current_time = time.time()
        elapsed = current_time - self._last_request_time

        if elapsed < self.rate_limit_delay:
            sleep_duration = self.rate_limit_delay - elapsed
            logger.debug(f"Rate limiting: sleeping {sleep_duration:.2f}s")
            time.sleep(sleep_duration)

        self._last_request_time = time.time()

    def _make_request(
        self,
        url: str,
        retries: int = 3,
        backoff: float = 1.0,
        method: str = "GET",
        **kwargs: Any
    ) -> requests.Response | None:
        """Make HTTP request with exponential backoff retry.

        Applies rate limiting before the request. Retries failed requests
        with exponential backoff: waits backoff * 2^i seconds on retry i.

        Args:
            url: Full URL to request.
            retries: Maximum number of retry attempts (default: 3).
            backoff: Initial backoff factor in seconds (default: 1.0).
            method: HTTP method to use (default: "GET").
            **kwargs: Additional arguments passed to requests.request().

        Returns:
            requests.Response | None: Response object if successful, None if all retries failed.
        """
        self._apply_rate_limit()

        headers = kwargs.pop("headers", None) or self._get_headers()

        for attempt in range(retries):
            try:
                logger.debug(f"Requesting {method} {url} (attempt {attempt + 1}/{retries})")
                response = requests.request(
                    method=method,
                    url=url,
                    headers=headers,
                    timeout=30,
                    **kwargs
                )

                # Handle common HTTP errors
                if response.status_code == 429:
                    # Too many requests - increase backoff and retry
                    wait_time = backoff * (2 ** (attempt + 1))
                    logger.warning(f"Rate limited (429). Retrying in {wait_time:.2f}s")
                    time.sleep(wait_time)
                    continue

                if response.status_code >= 500:
                    # Server error - retry
                    if attempt < retries - 1:
                        wait_time = backoff * (2 ** attempt)
                        logger.warning(
                            f"Server error {response.status_code}. Retrying in {wait_time:.2f}s"
                        )
                        time.sleep(wait_time)
                        continue
                    else:
                        logger.error(f"Server error {response.status_code} after {retries} attempts")
                        return None

                response.raise_for_status()
                logger.debug(f"Successfully fetched {url} (status: {response.status_code})")
                return response

            except requests.exceptions.Timeout:
                if attempt < retries - 1:
                    wait_time = backoff * (2 ** attempt)
                    logger.warning(f"Request timeout. Retrying in {wait_time:.2f}s")
                    time.sleep(wait_time)
                else:
                    logger.error(f"Request timeout after {retries} attempts for {url}")

            except requests.exceptions.ConnectionError as e:
                if attempt < retries - 1:
                    wait_time = backoff * (2 ** attempt)
                    logger.warning(f"Connection error: {e}. Retrying in {wait_time:.2f}s")
                    time.sleep(wait_time)
                else:
                    logger.error(f"Connection error after {retries} attempts for {url}: {e}")

            except requests.exceptions.RequestException as e:
                logger.error(f"Request failed for {url}: {e}")
                return None

        return None

    def _save_to_db(self, table_name: str, data: list[dict[str, Any]]) -> int:
        """Save data to database using db_manager.

        Uses the insert_many function from db_manager to batch insert
        records with metadata (fonte, url_origem, data_coleta).

        Args:
            table_name: Name of the database table to insert into.
            data: List of dictionaries, each representing a record.

        Returns:
            int: Number of records successfully inserted.
        """
        if not data:
            logger.warning(f"No data provided to save to table '{table_name}'")
            return 0

        metadata = {
            "fonte": self.name,
        }

        try:
            inserted_count = append_data(table_name, data, metadata)
            logger.info(f"Saved {inserted_count}/{len(data)} records to '{table_name}'")
            return inserted_count
        except Exception as e:
            logger.error(f"Failed to save data to '{table_name}': {e}")
            return 0

    def retry_failed(self) -> dict[str, Any]:
        """Retry previously failed URLs for this scraper.

        Loads failed URLs from the tracker and attempts to retry each one
        up to the maximum retry count. URLs that succeed are removed from
        the failed list.

        Returns:
            dict: Dictionary containing retry results:
                - 'retried': Number of URLs retried
                - 'succeeded': Number of URLs that succeeded
                - 'failed': Number of URLs that failed again
                - 'urls': List of URL results with status

        Note:
            Subclasses should override _process_retry_result() to handle
            the successful response and return processed data.
        """
        tracker = FailedUrlTracker()
        failed_urls = tracker.get_urls_for_retry(self.name)

        if not failed_urls:
            logger.info(f"No failed URLs to retry for scraper '{self.name}'")
            return {"retried": 0, "succeeded": 0, "failed": 0, "urls": []}

        logger.info(f"Retrying {len(failed_urls)} failed URLs for scraper '{self.name}'")

        results: list[dict[str, Any]] = []
        succeeded = 0
        failed = 0

        for url_record in failed_urls:
            url = url_record.get("url", "")
            original_error = url_record.get("error", "Unknown error")

            logger.info(f"Retrying URL: {url} (retry #{url_record.get('retry_count', 0) + 1})")

            try:
                response = self._make_request(url, retries=2, backoff=0.5)

                if response is not None and response.status_code == 200:
                    # Success - process the result and remove from failed list
                    process_result = self._process_retry_result(url, response)

                    if process_result:
                        tracker.remove_url(url, self.name)
                        succeeded += 1
                        logger.info(f"Successfully retried URL: {url}")
                    else:
                        # Processing returned False but request succeeded
                        tracker.mark_url_retried(url, self.name)
                        failed += 1
                        logger.warning(f"Failed to process retry result for: {url}")
                else:
                    # Request failed
                    tracker.mark_url_retried(url, self.name)
                    failed += 1
                    status = response.status_code if response else "No response"
                    logger.warning(f"Retry failed for {url} (status: {status})")

            except Exception as e:
                tracker.mark_url_retried(url, self.name)
                failed += 1
                logger.error(f"Exception during retry of {url}: {e}")

            results.append({
                "url": url,
                "status": "succeeded" if succeeded else "failed"
            })

        logger.info(
            f"Retry complete for '{self.name}': {succeeded} succeeded, "
            f"{failed} failed out of {len(failed_urls)} retried"
        )

        return {
            "retried": len(failed_urls),
            "succeeded": succeeded,
            "failed": failed,
            "urls": results
        }

    def _process_retry_result(self, url: str, response: requests.Response) -> bool:
        """Process a successful retry response.

        Override this method in subclasses to handle the response data
        when a retry succeeds. Default implementation just returns True.

        Args:
            url: The URL that was successfully retried.
            response: The successful response object.

        Returns:
            bool: True if processing was successful, False otherwise.
        """
        return True

    def scrape(self) -> dict[str, Any]:
        """Main scraping method - override in subclasses.

        This method should be implemented by subclasses to perform
        the actual scraping logic for specific websites.

        Returns:
            dict: Dictionary containing scraping results with keys like
                  'items', 'count', 'errors', etc.

        Raises:
            NotImplementedError: Always raised unless overridden by subclass.
        """
        raise NotImplementedError(f"{self.__class__.__name__} must implement scrape() method")
