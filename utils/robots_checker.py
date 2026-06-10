"""
Robots.txt checker module for FloripaScraper.

This module provides functionality to check if URLs are allowed to be scraped
according to the site's robots.txt file. It includes caching, crawl delay
handling, and utilities for respecting robots.txt rules.
"""

import logging
import time
import urllib.parse
from contextlib import contextmanager
from functools import lru_cache
from typing import Optional, Tuple

import requests

# Configure module logger
logger = logging.getLogger(__name__)

# Default crawl delay if not specified in robots.txt (in seconds)
DEFAULT_CRAWL_DELAY = 1.0

# Cache TTL in seconds (1 hour)
CACHE_TTL_SECONDS = 3600

# Default User-Agent for robots.txt requests
DEFAULT_USER_AGENT = "FloripaScraper/1.0 (+https://github.com/floripascraper)"


class RobotsCheckerError(Exception):
    """Custom exception raised when robots.txt checking fails."""
    pass


class RobotsChecker:
    """
    A class to check URL accessibility according to robots.txt rules.

    This class fetches and parses robots.txt files, caches the results
    for efficiency, and provides methods to check if URLs are allowed
    for scraping.

    Attributes:
        user_agent: The User-Agent string to use for robots.txt requests.
        cache_ttl: Time-to-live for cached robots.txt content in seconds.
        default_delay: Default crawl delay if not specified in robots.txt.

    Example:
        >>> checker = RobotsChecker()
        >>> if checker.check("https://example.com/page"):
        ...     print("URL is allowed")
        ... else:
        ...     print("URL is disallowed by robots.txt")
    """

    def __init__(
        self,
        user_agent: str = DEFAULT_USER_AGENT,
        cache_ttl: int = CACHE_TTL_SECONDS,
        default_delay: float = DEFAULT_CRAWL_DELAY
    ):
        """
        Initialize the RobotsChecker.

        Args:
            user_agent: The User-Agent string to use for requests.
                        Defaults to FloripaScraper's User-Agent.
            cache_ttl: Time-to-live for cached robots.txt content in seconds.
                      Defaults to 3600 (1 hour).
            default_delay: Default crawl delay in seconds if not specified
 in robots.txt. Defaults to 1.0.
        """
        self.user_agent = user_agent
        self.cache_ttl = cache_ttl
        self.default_delay = default_delay
        self._cache: dict[str, Tuple[Optional[str], float]] = {}
        logger.debug(
            f"RobotsChecker initialized with user_agent='{user_agent}', "
            f"cache_ttl={cache_ttl}s, default_delay={default_delay}s"
        )

    def _get_cache_key(self, base_url: str) -> str:
        """
        Generate a cache key for a given base URL.

        Args:
            base_url: The base URL of the site.

        Returns:
            A normalized cache key string.
        """
        # Normalize URL by removing trailing slash
        return base_url.rstrip('/')

    def _is_cache_valid(self, base_url: str) -> bool:
        """
        Check if the cached robots.txt for a base URL is still valid.

        Args:
            base_url: The base URL of the site.

        Returns:
            True if cache exists and is not expired, False otherwise.
        """
        cache_key = self._get_cache_key(base_url)
        if cache_key not in self._cache:
            return False

        _, timestamp = self._cache[cache_key]
        return (time.time() - timestamp) < self.cache_ttl

    def _get_robots_url(self, base_url: str) -> str:
        """
        Construct the robots.txt URL for a given base URL.

        Args:
            base_url: The base URL of the site.

        Returns:
            The full URL to the robots.txt file.
        """
        parsed = urllib.parse.urlparse(base_url)
        return f"{parsed.scheme}://{parsed.netloc}/robots.txt"

    def _fetch_robots_txt(self, base_url: str) -> Optional[str]:
        """
        Fetch the robots.txt content for a given base URL.

        Fetches from cache if available and valid, otherwise makes a request.

        Args:
            base_url: The base URL of the site.

        Returns:
            The robots.txt content as a string, or None if not found/error.
        """
        cache_key = self._get_cache_key(base_url)

        # Check cache first
        if self._is_cache_valid(base_url):
            cached_content, _ = self._cache[cache_key]
            logger.debug(f"Cache hit for robots.txt at {base_url}")
            return cached_content

        # Fetch from network
        robots_url = self._get_robots_url(base_url)
        logger.info(f"Fetching robots.txt from {robots_url}")

        try:
            response = requests.get(
                robots_url,
                headers={"User-Agent": self.user_agent},
                timeout=10
            )

            if response.status_code == 200:
                content = response.text
                self._cache[cache_key] = (content, time.time())
                logger.debug(
                    f"Successfully fetched robots.txt for {base_url}, "
                    f"cached until {time.time() + self.cache_ttl}"
                )
                return content
            elif response.status_code == 404:
                logger.warning(
                    f"robots.txt not found at {robots_url} (HTTP 404)"
                )
                # Cache the None result to avoid repeated requests
                self._cache[cache_key] = (None, time.time())
                return None
            else:
                logger.warning(
                    f"Unexpected status code {response.status_code} "
                    f"for robots.txt at {robots_url}"
                )
                return None

        except requests.RequestException as e:
            logger.error(f"Failed to fetch robots.txt from {robots_url}: {e}")
            return None

    def _parse_robots_txt(self, content: str) -> dict:
        """
        Parse robots.txt content into a structured format.

        Args:
            content: The raw robots.txt content.

        Returns:
            A dictionary with parsed rules, crawl delay, and sitemaps.
        """
        result = {
            "rules": {},
            "crawl_delay": None,
            "sitemaps": []
        }

        current_user_agent = None

        for line in content.splitlines():
            line = line.strip()

            # Skip empty lines and comments
            if not line or line.startswith('#'):
                continue

            # Split on first colon (respecting URLs with colons)
            if ':' not in line:
                continue

            key, _, value = line.partition(':')
            key = key.strip().lower()
            value = value.strip()

            if key == 'user-agent':
                current_user_agent = value
                if current_user_agent not in result["rules"]:
                    result["rules"][current_user_agent] = []

            elif key == 'disallow' and current_user_agent:
                result["rules"][current_user_agent].append({
                    "type": "disallow",
                    "path": value
                })

            elif key == 'allow' and current_user_agent:
                result["rules"][current_user_agent].append({
                    "type": "allow",
                    "path": value
                })

            elif key == 'crawl-delay' and current_user_agent:
                try:
                    result["crawl_delay"] = float(value)
                    logger.debug(
                        f"Found crawl-delay: {result['crawl_delay']} "
                        f"for user-agent: {current_user_agent}"
                    )
                except ValueError:
                    logger.warning(
                        f"Invalid crawl-delay value: {value}"
                    )

            elif key == 'sitemap':
                result["sitemaps"].append(value)

        return result

    def _match_path(self, path: str, pattern: str) -> bool:
        """
        Check if a path matches a robots.txt pattern.

        Supports:
        - Exact matches
        - Directory matches (ending with /)
        - Wildcard matches (ending with *)

        Args:
            path: The URL path to check.
            pattern: The robots.txt pattern to match against.

        Returns:
            True if the path matches the pattern, False otherwise.
        """
        if not pattern:
            return False

        # Exact match
        if pattern == path:
            return True

        # Directory match (pattern ends with /)
        if pattern.endswith('/'):
            return path.startswith(pattern)

        # Wildcard match (pattern ends with *)
        if pattern.endswith('*'):
            prefix = pattern[:-1]
            return path.startswith(prefix)

        # Partial match for patterns without special characters
        return path.startswith(pattern)

    def _is_url_allowed(
        self,
        path: str,
        rules: list[dict]
    ) -> Tuple[bool, str]:
        """
        Check if a path is allowed based on parsed robots.txt rules.

        Args:
            path: The URL path to check.
            rules: List of allow/disallow rules.

        Returns:
            A tuple of (allowed: bool, reason: str).
        """
        if not rules:
            return True, "No rules defined, allowing by default"

        # Find the most specific matching rule
        # More specific rules (longer patterns) take precedence
        matching_rule = None
        max_specificity = -1

        for rule in rules:
            pattern = rule["path"]
            if self._match_path(path, pattern):
                specificity = len(pattern)
                if specificity > max_specificity:
                    max_specificity = specificity
                    matching_rule = rule

        if matching_rule:
            if matching_rule["type"] == "disallow":
                return False, f"Path '{path}' is disallowed by rule '{matching_rule['path']}'"
            else:
                return True, f"Path '{path}' is explicitly allowed by rule '{matching_rule['path']}'"

        # No matching rule found, allow by default
        return True, f"No matching rule for '{path}', allowing by default"

    def check(self, url: str) -> bool:
        """
        Check if a URL is allowed to be scraped according to robots.txt.

        Args:
            url: The full URL to check.

        Returns:
            True if the URL is allowed, False if disallowed.
        """
        parsed = urllib.parse.urlparse(url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"
        path = parsed.path

        if not path:
            path = "/"

        return self.can_scrape(path, base_url)

    def can_scrape(self, path: str, base_url: str) -> bool:
        """
        Check if a specific path can be scraped for a given base URL.

        Args:
            path: The URL path to check (e.g., "/api/data").
            base_url: The base URL of the site (e.g., "https://example.com").

        Returns:
            True if the path is allowed for scraping, False otherwise.
        """
        content = self._fetch_robots_txt(base_url)

        if content is None:
            # No robots.txt found, assume allowed
            logger.debug(
                f"No robots.txt found for {base_url}, assuming allowed"
            )
            return True

        parsed = self._parse_robots_txt(content)

        # Check rules for our User-Agent first
        # Try full user agent, then try "*"
        rules = None

        # Check for specific user agent rules
        for ua in [self.user_agent, "*"]:
            if ua in parsed["rules"]:
                rules = parsed["rules"][ua]
                logger.debug(f"Using rules for user-agent: {ua}")
                break

        if rules is None:
            logger.debug(
                f"No rules found for user-agent '{self.user_agent}' or '*', "
                f"allowing by default"
            )
            return True

        allowed, reason = self._is_url_allowed(path, rules)
        logger.debug(f"can_scrape('{path}', '{base_url}'): {reason}")
        return allowed

    def get_crawl_delay(self, base_url: str) -> float:
        """
        Get the configured crawl delay for a site from robots.txt.

        Args:
            base_url: The base URL of the site.

        Returns:
            The crawl delay in seconds, or the default delay if not specified.
        """
        content = self._fetch_robots_txt(base_url)

        if content is None:
            logger.debug(
                f"No robots.txt found for {base_url}, "
                f"returning default delay: {self.default_delay}"
            )
            return self.default_delay

        parsed = self._parse_robots_txt(content)

        if parsed["crawl_delay"] is not None:
            delay = parsed["crawl_delay"]
            logger.debug(
                f"Crawl delay for {base_url}: {delay}s"
            )
            return delay

        logger.debug(
            f"No crawl-delay directive found for {base_url}, "
            f"returning default: {self.default_delay}"
        )
        return self.default_delay

    def clear_cache(self) -> None:
        """Clear all cached robots.txt content."""
        self._cache.clear()
        logger.info("Robots.txt cache cleared")

    def clear_cache_for(self, base_url: str) -> None:
        """
        Clear cached robots.txt content for a specific base URL.

        Args:
            base_url: The base URL to clear from cache.
        """
        cache_key = self._get_cache_key(base_url)
        if cache_key in self._cache:
            del self._cache[cache_key]
            logger.info(f"Cache cleared for {base_url}")


# Module-level singleton instance for convenience functions
_default_checker: Optional[RobotsChecker] = None


def _get_checker() -> RobotsChecker:
    """
    Get or create the default RobotsChecker instance.

    Returns:
        The default RobotsChecker instance.
    """
    global _default_checker
    if _default_checker is None:
        _default_checker = RobotsChecker()
    return _default_checker


def can_scrape_url(url: str) -> Tuple[bool, str]:
    """
    Check if a URL can be scraped according to robots.txt.

    This is a convenience function that uses the default RobotsChecker.

    Args:
        url: The full URL to check.

    Returns:
        A tuple of (allowed: bool, reason: str) indicating whether
        the URL is allowed and why.
    """
    checker = _get_checker()
    parsed = urllib.parse.urlparse(url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    path = parsed.path

    if not path:
        path = "/"

    content = checker._fetch_robots_txt(base_url)

    if content is None:
        return True, "No robots.txt found, assuming allowed"

    parsed_rules = checker._parse_robots_txt(content)

    rules = None
    for ua in [checker.user_agent, "*"]:
        if ua in parsed_rules["rules"]:
            rules = parsed_rules["rules"][ua]
            break

    if rules is None:
        return True, "No rules found for this user-agent, allowing by default"

    return checker._is_url_allowed(path, rules)


def get_delay_for_url(url: str) -> float:
    """
    Get the crawl delay for a URL based on its site's robots.txt.

    This is a convenience function that uses the default RobotsChecker.

    Args:
        url: The full URL to get the delay for.

    Returns:
        The crawl delay in seconds, or1.0 if not specified.
    """
    checker = _get_checker()
    parsed = urllib.parse.urlparse(url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    return checker.get_crawl_delay(base_url)


@contextmanager
def respect_robots():
    """
    Context manager to ensure scraper waits appropriate delay.

    This context manager checks if scraping is allowed and enforces
    the crawl delay specified in robots.txt. It yields a dictionary
    with information about the crawl delay.

    The context manager:
    1. Checks if the session is allowed to scrape (via robots.txt)
    2. Tracks the last request time
    3. Enforces the crawl delay between requests

    Yields:
        A dictionary with 'delay' key containing the crawl delay in seconds.

    Example:
        >>> with respect_robots() as ctx:
        ...     delay = ctx['delay']
        ...     # Make request
        ...     time.sleep(delay)
    """
    checker = _get_checker()
    last_request_time: list[float] = [0.0]

    class DelayContext:
        """Context object for crawl delay management."""
        delay: float = DEFAULT_CRAWL_DELAY
        last_request_time = last_request_time

        def wait_if_needed(self, base_url: str) -> None:
            """
            Wait if necessary to respect crawl delay.

            Args:
                base_url: The base URL being scraped.
            """
            delay = checker.get_crawl_delay(base_url)
            self.delay = delay

            elapsed = time.time() - self.last_request_time[0]
            if elapsed < delay:
                wait_time = delay - elapsed
                logger.debug(
                    f"Respecting crawl delay: waiting {wait_time:.2f}s "
                    f"(elapsed: {elapsed:.2f}s, required: {delay}s)"
                )
                time.sleep(wait_time)

            self.last_request_time[0] = time.time()

    ctx = DelayContext()
    logger.debug("respect_robots context manager entered")
    yield ctx
    logger.debug("respect_robots context manager exited")


def respect_robots_decorator(url_param: str = "url"):
    """
    Decorator to ensure a function respects robots.txt crawl delays.

    This decorator wraps an async or sync function that takes a URL
    parameter and automatically enforces the crawl delay.

    Args:
        url_param: The name of the URL parameter in the decorated function.
                   Defaults to "url".

    Returns:
        A decorator function.

    Example:
        >>> @respect_robots_decorator("url")
        ... def scrape_page(url: str) -> str:
        ...     response = requests.get(url)
        ...     return response.text
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            # Get the URL from args or kwargs
            url = kwargs.get(url_param)
            if url is None:
                # Try to find URL in positional args
                import inspect
                sig = inspect.signature(func)
                params = list(sig.parameters.keys())
                if url_param in params:
                    idx = params.index(url_param)
                    if idx < len(args):
                        url = args[idx]

            if url is None:
                logger.warning(
                    f"Could not find URL parameter '{url_param}' in function call"
                )
                return func(*args, **kwargs)

            checker = _get_checker()
            delay = checker.get_crawl_delay(urllib.parse.urlparse(url).netloc)

            logger.debug(
                f"respect_robots_decorator: enforcing {delay}s delay for {url}"
            )
            time.sleep(delay)

            return func(*args, **kwargs)

        return wrapper
    return decorator
