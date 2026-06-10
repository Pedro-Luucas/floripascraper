"""Main script to run all scrapers."""
import logging
import sys
import traceback
from typing import Any

from scrapers.transparencia_epublica import TransparenciaEPublicaScraper
from scrapers.pmf_sc import PmfScScraper
from scrapers.cigaobras import CigaObrasScraper
from scrapers.geoportal_shp import GeoportalShpScraper


def main() -> None:
    """Run all scrapers and report results."""
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    logger = logging.getLogger(__name__)

    logger.info("=" * 60)
    logger.info("Starting FloripaScraper - Running all scrapers")
    logger.info("=" * 60)

    results = run_all()

    # Print final summary
    print("\n" + "=" * 60)
    print("FINAL SUMMARY - All Scrapers Complete")
    print("=" * 60)

    total_records = 0
    total_errors = 0
    total_files = 0

    for scraper_name, scraper_results in results.items():
        print(f"\n{scraper_name.upper().replace('_', ' ')}:")
        print(f"  Status: {scraper_results.get('status', 'unknown')}")

        if scraper_name == "transparencia":
            results_data = scraper_results.get("results", {})
            for data_type, data_info in results_data.items():
                count = data_info.get("total", 0)
                print(f"    - {data_type}: {count} records")
                total_records += count
            files_created = scraper_results.get("files_created", [])
            for f in files_created:
                print(f"    - File: {f}")
                total_files += 1

        elif scraper_name == "pmf_sc":
            for key in ["noticias", "secretarias", "servicos"]:
                if key in scraper_results:
                    count = scraper_results[key].get("count", 0)
                    status = scraper_results[key].get("status", "unknown")
                    print(f"    - {key}: {count} records ({status})")
                    total_records += count
            total_files += 3  # noticias.json, secretarias.json, servicos.json

        elif scraper_name == "cigaobras":
            for key in ["obras", "empresas"]:
                if key in scraper_results:
                    count = scraper_results[key].get("count", 0)
                    status = scraper_results[key].get("status", "unknown")
                    print(f"    - {key}: {count} records ({status})")
                    total_records += count
            total_files += 2  # obras.json, empresas.json

        errors = scraper_results.get("errors", [])
        if errors:
            print(f"  Errors ({len(errors)}):")
            for err in errors:
                print(f"    - {err}")
                total_errors += 1

    print("\n" + "-" * 60)
    print(f"TOTAL RECORDS COLLECTED: {total_records}")
    print(f"TOTAL ERRORS: {total_errors}")
    print(f"FILES CREATED: {total_files}")
    print("=" * 60)

    # Exit with error code if any errors occurred
    if total_errors > 0:
        sys.exit(1)


def run_all() -> dict[str, dict[str, Any]]:
    """Execute all scrapers and return summary.

    Runs each scraper sequentially. If one scraper fails,
    execution continues with the next scraper.

    Returns:
        dict: Summary dictionary with results from all scrapers.
    """
    logger = logging.getLogger(__name__)

    results: dict[str, dict[str, Any]] = {}

    scrapers = [
        ("transparencia", lambda: TransparenciaEPublicaScraper()),
        ("pmf_sc", lambda: PmfScScraper()),
        ("cigaobras", lambda: CigaObrasScraper()),
        ("geoportal_shp", lambda: GeoportalShpScraper()),
    ]

    for scraper_key, scraper_factory in scrapers:
        logger.info(f"\n{'=' * 50}")
        logger.info(f"Running scraper: {scraper_key}")
        logger.info(f"{'=' * 50}")

        try:
            scraper = scraper_factory()
            scraper_result = scraper.scrape()

            results[scraper_key] = {
                "status": "success",
                "results": scraper_result,
                "errors": [],
            }

            # Track files created for transparencia scraper
            if scraper_key == "transparencia":
                files = []
                if scraper_result.get("resultados", {}).get("licitacoes", {}).get("arquivo"):
                    files.append(scraper_result["resultados"]["licitacoes"]["arquivo"])
                if scraper_result.get("resultados", {}).get("contratos", {}).get("arquivo"):
                    files.append(scraper_result["resultados"]["contratos"]["arquivo"])
                if scraper_result.get("resultados", {}).get("fornecedores", {}).get("arquivo"):
                    files.append(scraper_result["resultados"]["fornecedores"]["arquivo"])
                results[scraper_key]["files_created"] = files
                results[scraper_key]["results"] = scraper_result.get("resultados", {})

            elif scraper_key == "pmf_sc":
                results[scraper_key]["results"] = {
                    "noticias": {"total": scraper_result.get("noticias", {}).get("count", 0)},
                    "secretarias": {"total": scraper_result.get("secretarias", {}).get("count", 0)},
                    "servicos": {"total": scraper_result.get("servicos", {}).get("count", 0)},
                }

            elif scraper_key == "cigaobras":
                results[scraper_key]["results"] = {
                    "obras": {"total": scraper_result.get("obras", {}).get("count", 0)},
                    "empresas": {"total": scraper_result.get("empresas", {}).get("count", 0)},
                }

            logger.info(f"Scraper '{scraper_key}' completed successfully")

        except Exception as e:
            error_msg = f"Scraper '{scraper_key}' failed: {e}"
            logger.error(error_msg)
            logger.debug(traceback.format_exc())

            results[scraper_key] = {
                "status": "failed",
                "results": {},
                "errors": [str(e)],
            }

    return results


if __name__ == "__main__":
    main()
