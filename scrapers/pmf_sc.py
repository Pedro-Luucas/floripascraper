"""PMF SC (Prefeitura Municipal de Florianopolis) scraper module.

Scrapes official government data from pmf.sc.gov.br including:
- Noticias (news articles)
- Secretarias (government departments)
- Servicos (public services)
"""

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

from .base_scraper import BaseScraper
from utils.normalizers import normalize_data, normalize_telefone, normalize_cep

# Configure module logger
logger = logging.getLogger(__name__)

# Output directory for JSON files
OUTPUT_DIR = Path(__file__).parent.parent / "data"
REQUEST_DELAY = 1.5  # Seconds between requests


class PmfScScraper(BaseScraper):
    """Scraper for pmf.sc.gov.br (Prefeitura Municipal de Florianopolis).

    Inherits from BaseScraper which provides:
    - Realistic HTTP headers with rotating User-Agent
    - Exponential backoff retry logic
    - Rate limiting between requests

    Scrapes three types of data:
    - Noticias: News articles and announcements
    - Secretarias: Government departments and their info
    - Servicos: Public services available to citizens
    """

    def __init__(self, rate_limit_delay: float = REQUEST_DELAY) -> None:
        """Initialize PMF SC scraper.

        Args:
            rate_limit_delay: Minimum delay between HTTP requests in seconds.
        """
        super().__init__(
            name="pmf_sc",
            base_url="https://pmf.sc.gov.br",
            rate_limit_delay=rate_limit_delay
        )
        self.output_dir = OUTPUT_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"PmfScScraper initialized with output dir: {self.output_dir}")

    def _fetch_page(self, path: str = "") -> BeautifulSoup | None:
        """Fetch and parse a page from pmf.sc.gov.br.

        Args:
            path: URL path to fetch (relative to base_url).

        Returns:
            BeautifulSoup object if successful, None otherwise.
        """
        url = f"{self.base_url}/{path}".rstrip("/")
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

    def _save_to_json(
        self,
        data: list[dict[str, Any]],
        filename: str
    ) -> bool:
        """Save scraped data to JSON file with metadata.

        Args:
            data: List of scraped records.
            filename: Name of the output file (without path).

        Returns:
            True if save was successful, False otherwise.
        """
        filepath = self.output_dir / filename

        output = {
            "metadata": {
                "source": self.name,
                "base_url": self.base_url,
                "collected_at": datetime.now(timezone.utc).isoformat(),
                "count": len(data)
            },
            "data": data
        }

        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(output, f, ensure_ascii=False, indent=2)

            logger.info(f"Saved {len(data)} records to {filepath}")
            return True

        except Exception as e:
            logger.error(f"Failed to save data to {filepath}: {e}")
            return False

    def scrape_noticias(self) -> list[dict[str, Any]]:
        """Scrape news articles from pmf.sc.gov.br.

        Scrapes the news section which typically includes:
        - Title
        - Publication date
        - Summary/excerpt
        - Full content
        - Category

        Returns:
            List of dictionaries containing news article data.
        """
        logger.info("Starting news articles scraping")
        noticias: list[dict[str, Any]] = []

        try:
            # Try common news paths
            news_paths = [
                "servicos/noticias",
                "noticias",
                "ultimas-noticias",
                "paginas/noticias",
                "api/noticias"
            ]

            soup = None
            for path in news_paths:
                soup = self._fetch_page(path)
                if soup is not None:
                    # Verify we got actual news content
                    news_items = soup.select("article, .noticia, .news-item, .post")
                    if news_items:
                        logger.info(f"Found news page at: {path}")
                        break
                    soup = None

            if soup is None:
                # Try the main page for news links
                logger.info("Trying main page for news links")
                soup = self._fetch_page("")
                if soup:
                    # Look for news-related links
                    news_links = soup.select("a[href*='noticia'], a[href*='news']")
                    logger.info(f"Found {len(news_links)} potential news links on main page")

            if soup is None:
                logger.warning("Could not find news section, using fallback structure")
                # Create empty entry with error info
                return [{
                    "titulo": "",
                    "data_publicacao": "",
                    "resumo": "",
                    "conteudo": "",
                    "categoria": "",
                    "url": f"{self.base_url}/noticias",
                    "erro": "News section not found"
                }]

            # Parse news articles from the page
            # Try multiple selectors commonly used in Brazilian government sites
            news_items = (
                soup.select("article") or
                soup.select(".noticia") or
                soup.select(".news-item") or
                soup.select(".post") or
                soup.select(".article") or
                soup.select(".list-item") or
                soup.select(".noticias-item")
            )

            if not news_items:
                # Try to find news in list format
                news_items = soup.select("ul li") or []

            logger.info(f"Found {len(news_items)} potential news items")

            for idx, item in enumerate(news_items[:50]):  # Limit to 50 items
                try:
                    # Try to extract title from various common elements
                    title_elem = (
                        item.select_one("h1, h2, h3, h4, .title, .titulo, a") or
                        item if item.name in ("h1", "h2", "h3", "h4", "a") else None
                    )
                    title = title_elem.get_text(strip=True) if title_elem else ""

                    if not title:
                        continue

                    # Try to extract date
                    date_elem = (
                        item.select_one("time, .date, .data, [datetime], .published") or
                        item.select_one("span, div")
                    )
                    date_text = date_elem.get_text(strip=True) if date_elem else ""

                    # Try to normalize the date
                    data_publicacao = ""
                    if date_text:
                        try:
                            data_publicacao = normalize_data(date_text)
                        except Exception:
                            data_publicacao = date_text

                    # Try to extract summary
                    summary_elem = (
                        item.select_one("p, .summary, .resumo, .excerpt, .description") or
                        item.select_one("span")
                    )
                    resumo = summary_elem.get_text(strip=True) if summary_elem else ""

                    # Try to extract link
                    link_elem = item.select_one("a") if item.select_one("a") else item
                    href = link_elem.get("href", "") if link_elem else ""
                    url_noticia = href if href.startswith("http") else f"{self.base_url}{href}"

                    # Try to extract category
                    category_elem = (
                        item.select_one(".category, .categoria, .tag") or
                        item.select_one("span")
                    )
                    categoria = category_elem.get_text(strip=True) if category_elem else ""

                    noticia = {
                        "titulo": title,
                        "data_publicacao": data_publicacao,
                        "resumo": resumo[:500] if resumo else "",  # Limit summary length
                        "categoria": categoria,
                        "url": url_noticia
                    }

                    noticias.append(noticia)
                    logger.debug(f"Scraped news: {title[:50]}...")

                    # Rate limiting between items
                    time.sleep(self.rate_limit_delay)

                except Exception as e:
                    logger.warning(f"Error parsing news item {idx}: {e}")
                    continue

            logger.info(f"Successfully scraped {len(noticias)} news articles")

        except Exception as e:
            logger.error(f"Error during news scraping: {e}")

        # Save to JSON
        self._save_to_json(noticias, "noticias.json")

        return noticias

    def scrape_secretarias(self) -> list[dict[str, Any]]:
        """Scrape government departments (secretarias) from pmf.sc.gov.br.

        Scrapes the secretarias section which typically includes:
        - Department name
        - Description
        - Contact information
        - Address
        - Services offered

        Returns:
            List of dictionaries containing department data.
        """
        logger.info("Starting secretarias (departments) scraping")
        secretarias: list[dict[str, Any]] = []

        try:
            # Try common secretarias paths
            secretarias_paths = [
                "secretarias",
                "servicos/secretarias",
                "paginas/secretarias",
                "governo/secretarias"
            ]

            soup = None
            for path in secretarias_paths:
                soup = self._fetch_page(path)
                if soup is not None:
                    # Verify we got actual secretarias content
                    dept_items = soup.select(".secretaria, .depto, .department, .orgao")
                    if dept_items:
                        logger.info(f"Found secretarias page at: {path}")
                        break
                    soup = None

            if soup is None:
                # Try the main page
                logger.info("Trying main page for secretarias links")
                soup = self._fetch_page("")

            if soup is None:
                logger.warning("Could not find secretarias section")
                return [{
                    "nome": "",
                    "sigla": "",
                    "descricao": "",
                    "endereco": "",
                    "telefone": "",
                    "email": "",
                    "site": "",
                    "url": f"{self.base_url}/secretarias",
                    "erro": "Secretarias section not found"
                }]

            # Parse department items
            dept_items = (
                soup.select(".secretaria") or
                soup.select(".depto") or
                soup.select(".department") or
                soup.select(".orgao") or
                soup.select("article") or
                soup.select(".card") or
                soup.select(".list-item")
            )

            if not dept_items:
                dept_items = soup.select("ul li") or []

            logger.info(f"Found {len(dept_items)} potential department items")

            for idx, item in enumerate(dept_items[:30]):  # Limit to 30 items
                try:
                    # Extract name
                    name_elem = (
                        item.select_one("h1, h2, h3, h4, .title, .nome, .name, strong") or
                        item if item.name in ("h1", "h2", "h3", "h4") else None
                    )
                    nome = name_elem.get_text(strip=True) if name_elem else ""

                    if not nome or len(nome) < 2:
                        continue

                    # Try to extract acronym (sigla)
                    sigla_elem = item.select_one(".sigla, .acronym, span")
                    sigla = sigla_elem.get_text(strip=True) if sigla_elem else ""

                    # Try to extract description
                    desc_elem = (
                        item.select_one("p, .description, .descricao, .resumo") or
                        item.select_one("span")
                    )
                    descricao = desc_elem.get_text(strip=True) if desc_elem else ""

                    # Try to extract address
                    address_elem = (
                        item.select_one(".address, .endereco, [itemprop='address']") or
                        item.select_one("p")
                    )
                    endereco = address_elem.get_text(strip=True) if address_elem else ""

                    # Normalize CEP in address if found
                    if endereco:
                        try:
                            # Look for CEP pattern in address
                            import re
                            cep_match = re.search(r'\d{5}-?\d{3}', endereco)
                            if cep_match:
                                cep_normalized = normalize_cep(cep_match.group())
                                endereco = endereco.replace(cep_match.group(), cep_normalized)
                        except Exception:
                            pass

                    # Try to extract phone
                    phone_elem = (
                        item.select_one(".phone, .telefone, [itemprop='telephone']") or
                        item.select_one("a[href^='tel:']")
                    )
                    telefone = ""
                    if phone_elem:
                        if phone_elem.name == "a":
                            telefone = phone_elem.get("href", "").replace("tel:", "")
                        else:
                            telefone = phone_elem.get_text(strip=True)

                    # Normalize phone if found
                    if telefone:
                        try:
                            telefone = normalize_telefone(telefone)
                        except Exception:
                            pass

                    # Try to extract email
                    email_elem = (
                        item.select_one(".email, [itemprop='email']") or
                        item.select_one("a[href^='mailto:']")
                    )
                    email = ""
                    if email_elem:
                        if email_elem.name == "a":
                            email = email_elem.get("href", "").replace("mailto:", "")
                        else:
                            email = email_elem.get_text(strip=True)

                    # Try to extract website
                    site_elem = (
                        item.select_one(".website, a[target='_blank']") or
                        item.select_one("a.external")
                    )
                    site = site_elem.get("href", "") if site_elem else ""

                    # Get department URL
                    link_elem = item.select_one("a")
                    href = link_elem.get("href", "") if link_elem else ""
                    url_secretaria = href if href.startswith("http") else f"{self.base_url}{href}"

                    secretaria = {
                        "nome": nome,
                        "sigla": sigla,
                        "descricao": descricao[:500] if descricao else "",
                        "endereco": endereco,
                        "telefone": telefone,
                        "email": email,
                        "site": site,
                        "url": url_secretaria
                    }

                    secretarias.append(secretaria)
                    logger.debug(f"Scraped secretaria: {nome}")

                    # Rate limiting between items
                    time.sleep(self.rate_limit_delay)

                except Exception as e:
                    logger.warning(f"Error parsing secretaria item {idx}: {e}")
                    continue

            logger.info(f"Successfully scraped {len(secretarias)} secretarias")

        except Exception as e:
            logger.error(f"Error during secretarias scraping: {e}")

        # Save to JSON
        self._save_to_json(secretarias, "secretarias.json")

        return secretarias

    def scrape_servicos(self) -> list[dict[str, Any]]:
        """Scrape public services from pmf.sc.gov.br.

        Scrapes the servicos section which typically includes:
        - Service name
        - Description
        - Requirements
        - Required documents
        - Service location
        - Processing time

        Returns:
            List of dictionaries containing service data.
        """
        logger.info("Starting servicos (services) scraping")
        servicos: list[dict[str, Any]] = []

        try:
            # Try common servicos paths
            servicos_paths = [
                "servicos",
                "cidadao/servicos",
                "servicos-publicos",
                "transparencia/servicos"
            ]

            soup = None
            for path in servicos_paths:
                soup = self._fetch_page(path)
                if soup is not None:
                    # Verify we got actual servicos content
                    service_items = soup.select(".servico, .service, .servicos-item")
                    if service_items:
                        logger.info(f"Found servicos page at: {path}")
                        break
                    soup = None

            if soup is None:
                # Try the main page
                logger.info("Trying main page for servicos links")
                soup = self._fetch_page("")

            if soup is None:
                logger.warning("Could not find servicos section")
                return [{
                    "nome": "",
                    "descricao": "",
                    "requisitos": "",
                    "documentos": "",
                    "local": "",
                    "prazo": "",
                    "url": f"{self.base_url}/servicos",
                    "erro": "Servicos section not found"
                }]

            # Parse service items
            service_items = (
                soup.select(".servico") or
                soup.select(".service") or
                soup.select(".servicos-item") or
                soup.select(".service-item") or
                soup.select("article") or
                soup.select(".card") or
                soup.select(".list-item")
            )

            if not service_items:
                service_items = soup.select("ul li") or []

            logger.info(f"Found {len(service_items)} potential service items")

            for idx, item in enumerate(service_items[:50]):  # Limit to 50 items
                try:
                    # Extract service name
                    name_elem = (
                        item.select_one("h1, h2, h3, h4, .title, .nome, .name") or
                        item if item.name in ("h1", "h2", "h3", "h4") else None
                    )
                    nome = name_elem.get_text(strip=True) if name_elem else ""

                    if not nome or len(nome) < 2:
                        continue

                    # Try to extract description
                    desc_elem = (
                        item.select_one("p, .description, .descricao, .resumo") or
                        item.select_one("span")
                    )
                    descricao = desc_elem.get_text(strip=True) if desc_elem else ""

                    # Try to extract requirements (requisitos)
                    req_elem = (
                        item.select_one(".requirements, .requisitos, .exigencias") or
                        item.select_one("ul")
                    )
                    requisitos = req_elem.get_text(strip=True) if req_elem else ""

                    # Try to extract required documents
                    docs_elem = (
                        item.select_one(".documents, .documentos, .docs") or
                        item.select_one("ul:nth-of-type(2)")
                    )
                    documentos = docs_elem.get_text(strip=True) if docs_elem else ""

                    # Try to extract service location
                    local_elem = (
                        item.select_one(".location, .local, .endereco, [itemprop='address']") or
                        item.select_one("p")
                    )
                    local = local_elem.get_text(strip=True) if local_elem else ""

                    # Normalize CEP in location if found
                    if local:
                        try:
                            import re
                            cep_match = re.search(r'\d{5}-?\d{3}', local)
                            if cep_match:
                                cep_normalized = normalize_cep(cep_match.group())
                                local = local.replace(cep_match.group(), cep_normalized)
                        except Exception:
                            pass

                    # Try to extract processing time
                    prazo_elem = (
                        item.select_one(".deadline, .prazo, .tempo, .processing-time") or
                        item.select_one("span")
                    )
                    prazo = prazo_elem.get_text(strip=True) if prazo_elem else ""

                    # Get service URL
                    link_elem = item.select_one("a")
                    href = link_elem.get("href", "") if link_elem else ""
                    url_servico = href if href.startswith("http") else f"{self.base_url}{href}"

                    servico = {
                        "nome": nome,
                        "descricao": descricao[:500] if descricao else "",
                        "requisitos": requisitos[:500] if requisitos else "",
                        "documentos": documentos[:500] if documentos else "",
                        "local": local,
                        "prazo": prazo,
                        "url": url_servico
                    }

                    servicos.append(servico)
                    logger.debug(f"Scraped servico: {nome}")

                    # Rate limiting between items
                    time.sleep(self.rate_limit_delay)

                except Exception as e:
                    logger.warning(f"Error parsing servico item {idx}: {e}")
                    continue

            logger.info(f"Successfully scraped {len(servicos)} servicos")

        except Exception as e:
            logger.error(f"Error during servicos scraping: {e}")

        # Save to JSON
        self._save_to_json(servicos, "servicos.json")

        return servicos

    def scrape(self) -> dict[str, Any]:
        """Run all scrapers and return summary.

        Executes scraping for noticias, secretarias, and servicos.
        Each data type is saved to its own JSON file.

        Returns:
            Dictionary containing counts and status for each data type:
            {
                "noticias": {"count": int, "status": str},
                "secretarias": {"count": int, "status": str},
                "servicos": {"count": int, "status": str},
                "total": int,
                "errors": list[str]
            }
        """
        logger.info("Starting PMF SC full scrape")
        summary: dict[str, Any] = {
            "noticias": {"count": 0, "status": "pending"},
            "secretarias": {"count": 0, "status": "pending"},
            "servicos": {"count": 0, "status": "pending"},
            "total": 0,
            "errors": []
        }

        start_time = time.time()

        # Scrape news
        try:
            logger.info("=" * 50)
            logger.info("Phase 1: Scraping noticias")
            noticias = self.scrape_noticias()
            summary["noticias"]["count"] = len(noticias)
            summary["noticias"]["status"] = "success"
            summary["total"] += len(noticias)
            logger.info(f"Noticias scraping complete: {len(noticias)} items")
        except Exception as e:
            error_msg = f"Noticias scraping failed: {e}"
            logger.error(error_msg)
            summary["noticias"]["status"] = "error"
            summary["errors"].append(error_msg)

        # Delay between major sections
        time.sleep(self.rate_limit_delay * 2)

        # Scrape secretarias
        try:
            logger.info("=" * 50)
            logger.info("Phase 2: Scraping secretarias")
            secretarias = self.scrape_secretarias()
            summary["secretarias"]["count"] = len(secretarias)
            summary["secretarias"]["status"] = "success"
            summary["total"] += len(secretarias)
            logger.info(f"Secretarias scraping complete: {len(secretarias)} items")
        except Exception as e:
            error_msg = f"Secretarias scraping failed: {e}"
            logger.error(error_msg)
            summary["secretarias"]["status"] = "error"
            summary["errors"].append(error_msg)

        # Delay between major sections
        time.sleep(self.rate_limit_delay * 2)

        # Scrape servicos
        try:
            logger.info("=" * 50)
            logger.info("Phase 3: Scraping servicos")
            servicos = self.scrape_servicos()
            summary["servicos"]["count"] = len(servicos)
            summary["servicos"]["status"] = "success"
            summary["total"] += len(servicos)
            logger.info(f"Servicos scraping complete: {len(servicos)} items")
        except Exception as e:
            error_msg = f"Servicos scraping failed: {e}"
            logger.error(error_msg)
            summary["servicos"]["status"] = "error"
            summary["errors"].append(error_msg)

        elapsed_time = time.time() - start_time

        logger.info("=" * 50)
        logger.info("PMF SC scraping complete")
        logger.info(f"Total items scraped: {summary['total']}")
        logger.info(f"Time elapsed: {elapsed_time:.2f} seconds")
        logger.info(f"Summary: {summary}")

        return summary


if __name__ == "__main__":
    # Configure logging for direct execution
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    scraper = PmfScScraper()
    result = scraper.scrape()
    print(f"\nScraping complete. Result: {result}")