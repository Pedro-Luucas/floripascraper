"""CigaObras scraper for cigaobras.pmf.sc.gov.br.

Scrapes data about public works (obras) and contractor companies (empresas)
from the Municipality of Florianopolis (PMF) CigaObras system.
"""

import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

from .base_scraper import BaseScraper
from utils.normalizers import (
    normalize_cnpj,
    normalize_data,
    normalize_moeda,
    normalize_cep,
    normalize_telefone,
)

# Configure module logger
logger = logging.getLogger(__name__)

# Directory for output files
OUTPUT_DIR = Path(__file__).parent.parent / "data"
RATE_LIMIT_DELAY = 1.5  # 1.5 seconds between requests


class CigaObrasScraper(BaseScraper):
    """Scraper for CigaObras public works data.

    Scrapes information about public works and contractor companies
    from the Florianopolis municipality system.
    """

    def __init__(self, rate_limit_delay: float = RATE_LIMIT_DELAY):
        """Initialize CigaObras scraper.

        Args:
            rate_limit_delay: Minimum delay between requests in seconds (default: 1.5).
        """
        super().__init__(
            name="cigaobras",
            base_url="https://cigaobras.pmf.sc.gov.br",
            rate_limit_delay=rate_limit_delay,
        )
        self._output_dir = OUTPUT_DIR
        self._output_dir.mkdir(parents=True, exist_ok=True)

    def _fetch_page(self, path: str = "") -> BeautifulSoup | None:
        """Fetch a page and parse with BeautifulSoup.

        Args:
            path: URL path to fetch (appended to base_url).

        Returns:
            BeautifulSoup object if successful, None otherwise.
        """
        url = f"{self.base_url}/{path.lstrip('/')}" if path else self.base_url
        logger.info(f"Fetching page: {url}")

        response = self._make_request(url)
        if response is None:
            logger.error(f"Failed to fetch page: {url}")
            return None

        try:
            soup = BeautifulSoup(response.text, "html.parser")
            logger.debug(f"Successfully parsed HTML from {url}")
            return soup
        except Exception as e:
            logger.error(f"Failed to parse HTML from {url}: {e}")
            return None

    def _save_json(self, data: list[dict], filename: str) -> int:
        """Save data to JSON file with metadata.

        Args:
            data: List of dictionaries to save.
            filename: Name of the output file (without path).

        Returns:
            int: Number of records saved.
        """
        if not data:
            logger.warning(f"No data to save to {filename}")
            return 0

        output_path = self._output_dir / filename

        output_data = {
            "metadata": {
                "fonte": self.name,
                "data_coleta": datetime.now(timezone.utc).isoformat(),
                "total_registros": len(data),
            },
            "dados": data,
        }

        try:
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(output_data, f, ensure_ascii=False, indent=2)

            logger.info(f"Saved {len(data)} records to {output_path}")
            return len(data)

        except Exception as e:
            logger.error(f"Failed to save {filename}: {e}")
            return 0

    def _extract_text(self, element: Any, default: str = "") -> str:
        """Extract clean text from BeautifulSoup element.

        Args:
            element: BeautifulSoup element or None.
            default: Default value if element is None or has no text.

        Returns:
            str: Extracted and stripped text, or default value.
        """
        if element is None:
            return default
        text = element.get_text(strip=True)
        return text if text else default

    def _extract_value_by_label(self, soup: BeautifulSoup, label: str) -> str:
        """Extract value by searching for a label and getting adjacent text.

        Args:
            soup: BeautifulSoup object to search.
            label: Label text to search for.

        Returns:
            str: Extracted value or empty string if not found.
        """
        # Try different patterns for finding label-value pairs
        patterns = [
            # Pattern: <label>text:</label><value>text</value>
            lambda: soup.find(string=re.compile(f"{re.escape(label)}:", re.IGNORECASE)),
            # Pattern: <td>label</td><td>value</td>
            lambda: soup.find("td", string=re.compile(f"^{re.escape(label)}$", re.I)),
        ]

        for pattern_func in patterns:
            try:
                match = pattern_func()
                if match:
                    # Try to find the next sibling element
                    parent = match.find_parent(["tr", "div", "span"])
                    if parent:
                        next_elem = parent.find_next_sibling()
                        if next_elem:
                            return self._extract_text(next_elem)
                    # Try parent with value
                    return self._extract_text(match.find_parent())
            except Exception:
                pass

        return ""

    def scrape_obras(self) -> list[dict]:
        """Scrape public works (obras) data.

        Fetches the list of public works and detailed information
        for each one.

        Returns:
            list[dict]: List of obra records with all extracted fields.
        """
        logger.info("Starting obras scraping")
        obras = []

        try:
            # Try to find the obras listing page
            # Common patterns for public works systems
            paths_to_try = [
                "obras",
                "obras/lista",
                "obras/listagem",
                "consulta/obras",
                "obras/consulta",
            ]

            soup = None
            for path in paths_to_try:
                logger.debug(f"Trying path: {path}")
                test_soup = self._fetch_page(path)
                if test_soup and test_soup.find(["table", "div", "ul"]):
                    soup = test_soup
                    logger.info(f"Found obras page at: {path}")
                    break

            if soup is None:
                # Try the main page
                soup = self._fetch_page("")
                if soup is None:
                    logger.warning("Could not access CigaObras website")
                    return obras

            # Try to extract obra records from tables or lists
            obra_records = []

            # Look for tables with obra data
            tables = soup.find_all("table")
            for table in tables:
                rows = table.find_all("tr")
                for row in rows:
                    cells = row.find_all(["td", "th"])
                    if len(cells) >= 2:
                        # Try to extract obra info from table row
                        record = self._parse_table_row(cells)
                        if record:
                            obra_records.append(record)

            # Also look for cards/list items with obra data
            cards = soup.find_all(["div", "li"], class_=re.compile(r"obra|item|result", re.I))
            for card in cards:
                record = self._parse_card(card)
                if record:
                    obra_records.append(record)

            # Deduplicate records
            seen = set()
            for record in obra_records:
                key = record.get("nome", "") + record.get("codigo", "")
                if key and key not in seen:
                    seen.add(key)
                    obras.append(record)

            logger.info(f"Extracted {len(obras)} obra records")

        except Exception as e:
            logger.error(f"Error during obras scraping: {e}")

        # Save to JSON
        self._save_json(obras, "obras.json")

        return obras

    def _parse_table_row(self, cells: list) -> dict | None:
        """Parse a table row into an obra record.

        Args:
            cells: List of BeautifulSoup td/th elements.

        Returns:
            dict or None: Parsed obra record if successful.
        """
        if len(cells) < 2:
            return None

        record = {}

        try:
            # Try to identify columns by header or position
            for i, cell in enumerate(cells):
                text = self._extract_text(cell)

                # Skip empty or header cells
                if not text or text.lower() in ["acao", "opcoes", "detalhes"]:
                    continue

                # Try to detect field type by content patterns
                if re.search(r"obra|contrato|licitacao", text, re.I):
                    record["nome"] = text
                elif re.search(r"empresa|responsavel|contratada", text, re.I):
                    record["empresa_responsavel"] = text
                elif re.search(r"valor|valor total|contrato", text, re.I):
                    # Check next cell for value
                    if i + 1 < len(cells):
                        value_text = self._extract_text(cells[i + 1])
                        try:
                            record["valor_total"] = normalize_moeda(value_text)
                        except Exception:
                            pass
                elif re.search(r"status|situacao", text, re.I):
                    record["status"] = text
                elif re.search(r"inicio|inici?o", text, re.I):
                    if i + 1 < len(cells):
                        date_text = self._extract_text(cells[i + 1])
                        try:
                            record["data_inicio"] = normalize_data(date_text)
                        except Exception:
                            pass
                elif re.search(r"fim|termino|conclusao", text, re.I):
                    if i + 1 < len(cells):
                        date_text = self._extract_text(cells[i + 1])
                        try:
                            record["data_fim"] = normalize_data(date_text)
                        except Exception:
                            pass

        except Exception as e:
            logger.debug(f"Error parsing table row: {e}")

        # Only return if we found meaningful data
        if record.get("nome"):
            return record

        return None

    def _parse_card(self, element: BeautifulSoup) -> dict | None:
        """Parse a card/div element into an obra record.

        Args:
            element: BeautifulSoup element to parse.

        Returns:
            dict or None: Parsed obra record if successful.
        """
        record = {}

        try:
            # Look for title/name
            title_elem = element.find(["h1", "h2", "h3", "h4", "a", "strong", "span"],
                                      class_=re.compile(r"titulo|title|nome|obra", re.I))
            if title_elem:
                record["nome"] = self._extract_text(title_elem)

            # Look for value
            value_elem = element.find(["span", "div", "p"],
                                      class_=re.compile(r"valor|preco|amount", re.I))
            if value_elem:
                try:
                    record["valor_total"] = normalize_moeda(self._extract_text(value_elem))
                except Exception:
                    pass

            # Look for status
            status_elem = element.find(["span", "div", "badge"],
                                       class_=re.compile(r"status|situacao|estado", re.I))
            if status_elem:
                record["status"] = self._extract_text(status_elem)

            # Look for address/location
            addr_elem = element.find(["span", "div", "p"],
                                     class_=re.compile(r"endereco|local|location|cep", re.I))
            if addr_elem:
                addr_text = self._extract_text(addr_elem)
                record["localizacao"] = addr_text
                # Try to extract CEP
                cep_match = re.search(r"\d{5}-?\d{3}", addr_text)
                if cep_match:
                    try:
                        record["cep"] = normalize_cep(cep_match.group())
                    except Exception:
                        pass

        except Exception as e:
            logger.debug(f"Error parsing card: {e}")

        # Only return if we found meaningful data
        if record.get("nome"):
            return record

        return None

    def scrape_empresas(self) -> list[dict]:
        """Scrape contractor company (empresa) data.

        Fetches the list of contractor companies registered
        in the CigaObras system.

        Returns:
            list[dict]: List of empresa records with all extracted fields.
        """
        logger.info("Starting empresas scraping")
        empresas = []

        try:
            # Try to find the empresas listing page
            paths_to_try = [
                "empresas",
                "empresas/lista",
                "consulta/empresas",
                "fornecedores",
                "contratadas",
            ]

            soup = None
            for path in paths_to_try:
                logger.debug(f"Trying path: {path}")
                test_soup = self._fetch_page(path)
                if test_soup and test_soup.find(["table", "div", "ul"]):
                    soup = test_soup
                    logger.info(f"Found empresas page at: {path}")
                    break

            if soup is None:
                logger.info("No separate empresas page found, extracting from other pages")
                # Try to extract empresa data from the main page or obra details
                soup = self._fetch_page("")

            if soup is None:
                logger.warning("Could not access CigaObras website")
                return empresas

            # Extract empresa records from tables
            empresa_records = []

            tables = soup.find_all("table")
            for table in tables:
                rows = table.find_all("tr")
                for row in rows:
                    cells = row.find_all(["td", "th"])
                    if len(cells) >= 2:
                        record = self._parse_empresa_row(cells)
                        if record:
                            empresa_records.append(record)

            # Also look for cards/list items
            cards = soup.find_all(["div", "li"], class_=re.compile(r"empresa|fornecedor|company", re.I))
            for card in cards:
                record = self._parse_empresa_card(card)
                if record:
                    empresa_records.append(record)

            # Deduplicate records
            seen = set()
            for record in empresa_records:
                key = record.get("nome", "") + record.get("cnpj", "")
                if key and key not in seen:
                    seen.add(key)
                    empresas.append(record)

            logger.info(f"Extracted {len(empresas)} empresa records")

        except Exception as e:
            logger.error(f"Error during empresas scraping: {e}")

        # Save to JSON
        self._save_json(empresas, "empresas.json")

        return empresas

    def _parse_empresa_row(self, cells: list) -> dict | None:
        """Parse a table row into an empresa record.

        Args:
            cells: List of BeautifulSoup td/th elements.

        Returns:
            dict or None: Parsed empresa record if successful.
        """
        if len(cells) < 2:
            return None

        record = {}

        try:
            for i, cell in enumerate(cells):
                text = self._extract_text(cell)

                if not text or text.lower() in ["acao", "opcoes", "detalhes"]:
                    continue

                # Try to detect field type
                if re.search(r"empresa|razao social|fornecedor", text, re.I):
                    record["nome"] = text
                elif re.search(r"cnpj|cpf", text, re.I):
                    if i + 1 < len(cells):
                        cnpj_text = self._extract_text(cells[i + 1])
                        try:
                            if "cnpj" in text.lower():
                                record["cnpj"] = normalize_cnpj(cnpj_text)
                            else:
                                pass  # CPF normalization not stored separately
                        except Exception:
                            record["cnpj"] = cnpj_text
                elif re.search(r"telefone|fone|contato", text, re.I):
                    if i + 1 < len(cells):
                        tel_text = self._extract_text(cells[i + 1])
                        try:
                            record["telefone"] = normalize_telefone(tel_text)
                        except Exception:
                            pass
                elif re.search(r"endereco|cep", text, re.I):
                    if i + 1 < len(cells):
                        addr_text = self._extract_text(cells[i + 1])
                        record["endereco"] = addr_text
                        cep_match = re.search(r"\d{5}-?\d{3}", addr_text)
                        if cep_match:
                            try:
                                record["cep"] = normalize_cep(cep_match.group())
                            except Exception:
                                pass

        except Exception as e:
            logger.debug(f"Error parsing empresa row: {e}")

        if record.get("nome"):
            return record

        return None

    def _parse_empresa_card(self, element: BeautifulSoup) -> dict | None:
        """Parse a card/div element into an empresa record.

        Args:
            element: BeautifulSoup element to parse.

        Returns:
            dict or None: Parsed empresa record if successful.
        """
        record = {}

        try:
            # Look for company name
            name_elem = element.find(["h1", "h2", "h3", "h4", "a", "strong"],
                                     class_=re.compile(r"empresa|razao|company|name", re.I))
            if name_elem:
                record["nome"] = self._extract_text(name_elem)

            # Look for CNPJ
            cnpj_elem = element.find(["span", "div", "p"],
                                    class_=re.compile(r"cnpj|documento", re.I))
            if cnpj_elem:
                cnpj_text = self._extract_text(cnpj_elem)
                try:
                    record["cnpj"] = normalize_cnpj(cnpj_text)
                except Exception:
                    pass

            # Look for phone
            tel_elem = element.find(["span", "div"],
                                    class_=re.compile(r"telefone|fone|phone", re.I))
            if tel_elem:
                try:
                    record["telefone"] = normalize_telefone(self._extract_text(tel_elem))
                except Exception:
                    pass

            # Look for address
            addr_elem = element.find(["span", "div"],
                                    class_=re.compile(r"endereco|address|location", re.I))
            if addr_elem:
                record["endereco"] = self._extract_text(addr_elem)

        except Exception as e:
            logger.debug(f"Error parsing empresa card: {e}")

        if record.get("nome"):
            return record

        return None

    def scrape(self) -> dict:
        """Run all scrapers and return summary.

        Executes both obras and empresas scraping operations
        and returns a summary with counts and status.

        Returns:
            dict: Summary containing scraping results with counts and errors.
        """
        logger.info("Starting CigaObras full scrape")
        start_time = time.time()

        summary = {
            "scraper": self.name,
            "base_url": self.base_url,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "obras": {"count": 0, "status": "pending"},
            "empresas": {"count": 0, "status": "pending"},
            "duration_seconds": 0,
            "errors": [],
        }

        try:
            # Scrape obras
            logger.info("Scraping obras...")
            obras = self.scrape_obras()
            summary["obras"]["count"] = len(obras)
            summary["obras"]["status"] = "success"

        except Exception as e:
            error_msg = f"Obras scraping failed: {e}"
            logger.error(error_msg)
            summary["obras"]["status"] = "failed"
            summary["errors"].append(error_msg)

        # Add delay between scrapers
        time.sleep(self.rate_limit_delay)

        try:
            # Scrape empresas
            logger.info("Scraping empresas...")
            empresas = self.scrape_empresas()
            summary["empresas"]["count"] = len(empresas)
            summary["empresas"]["status"] = "success"

        except Exception as e:
            error_msg = f"Empresas scraping failed: {e}"
            logger.error(error_msg)
            summary["empresas"]["status"] = "failed"
            summary["errors"].append(error_msg)

        # Calculate duration
        summary["duration_seconds"] = round(time.time() - start_time, 2)

        # Log summary
        logger.info(
            f"CigaObras scrape completed in {summary['duration_seconds']}s: "
            f"obras={summary['obras']['count']}, empresas={summary['empresas']['count']}, "
            f"errors={len(summary['errors'])}"
        )

        return summary


def main():
    """Main entry point for running the scraper directly."""
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    scraper = CigaObrasScraper()
    result = scraper.scrape()

    print(f"\nScraping Summary:")
    print(f"  Obras: {result['obras']['count']} ({result['obras']['status']})")
    print(f"  Empresas: {result['empresas']['count']} ({result['empresas']['status']})")
    print(f"  Duration: {result['duration_seconds']}s")
    if result["errors"]:
        print(f"  Errors: {len(result['errors'])}")


if __name__ == "__main__":
    main()