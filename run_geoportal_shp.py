"""Run only the Geoportal SHP scraper."""
import logging
import sys

from scrapers.geoportal_shp import GeoportalShpScraper


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    logger = logging.getLogger(__name__)

    logger.info("Starting GeoportalShpScraper")
    try:
        result = GeoportalShpScraper().scrape()
        logger.info("Done. Result: %s", result)
    except Exception as exc:
        logger.error("Scraper failed: %s", exc, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
