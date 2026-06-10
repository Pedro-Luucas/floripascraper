"""Scraper for transparencia.e-publica.net.

Scrapes government transparency data including bidding processes (licitacoes),
contracts (contratos), and suppliers (fornecedores).
"""

import json
import logging
import os
from datetime import datetime
from typing import Any

from bs4 import BeautifulSoup

from .base_scraper import BaseScraper
from utils.normalizers import (
    normalize_cnpj,
    normalize_data,
    normalize_moeda,
    normalize_preco,
)

# Configure module logger
logger = logging.getLogger(__name__)

# Base paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")

# Ensure data directory exists
os.makedirs(DATA_DIR, exist_ok=True)


class TransparenciaEPublicaScraper(BaseScraper):
    """Scraper for transparencia.e-publica.net.

    Scrapes public transparency data from Florianopolis city government portal,
    including bidding processes, contracts, and supplier information.

    Attributes:
        name: Scraper identifier.
        base_url: Base URL for the transparency portal.
    """

    def __init__(self, rate_limit_delay: float = 1.5) -> None:
        """Initialize the scraper.

        Args:
            rate_limit_delay: Minimum delay between requests in seconds (default: 1.5).
        """
        super().__init__(
            name="transparencia_e-publica",
            base_url="https://transparencia.e-publica.net",
            rate_limit_delay=rate_limit_delay,
        )

        # Data collection timestamp
        self.data_coleta = datetime.now().isoformat()

        # Paths for output files
        self.licitacoes_file = os.path.join(DATA_DIR, "licitacoes.json")
        self.contratos_file = os.path.join(DATA_DIR, "contratos.json")
        self.fornecedores_file = os.path.join(DATA_DIR, "fornecedores.json")

    def _add_metadata(self, record: dict[str, Any], url: str) -> dict[str, Any]:
        """Add standard metadata to a record.

        Args:
            record: The data record to add metadata to.
            url: The source URL for this record.

        Returns:
            dict: Record with metadata added.
        """
        return {
            **record,
            "fonte": self.name,
            "url_origem": url,
            "data_coleta": self.data_coleta,
        }

    def _save_to_json(
        self, data: list[dict[str, Any]], filepath: str
    ) -> bool:
        """Save data to JSON file with metadata.

        Args:
            data: List of records to save.
            filepath: Path to the output JSON file.

        Returns:
            bool: True if save was successful, False otherwise.
        """
        try:
            output = {
                "meta": {
                    "fonte": self.name,
                    "data_coleta": self.data_coleta,
                    "total_registros": len(data),
                },
                "dados": data,
            }

            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(output, f, ensure_ascii=False, indent=2)

            logger.info(f"Saved {len(data)} records to {filepath}")
            return True

        except Exception as e:
            logger.error(f"Failed to save data to {filepath}: {e}")
            return False

    def _check_for_api(self, response_text: str) -> dict[str, Any] | None:
        """Check if the response contains API-style data (JSON).

        Args:
            response_text: The response text to check.

        Returns:
            dict | None: Parsed JSON if found, None otherwise.
        """
        try:
            # Try to find JSON in the response
            return json.loads(response_text)
        except json.JSONDecodeError:
            return None

    def scrape_licitacoes(self) -> list[dict[str, Any]]:
        """Scrape bidding/tender data (licitacoes).

        Returns:
            list[dict]: List of bidding records with metadata.
        """
        logger.info("Starting to scrape licitacoes (bidding data)")
        licitacoes = []

        # Common URL patterns for licitacoes on transparency portals
        urls_to_try = [
            f"{self.base_url}/licitacoes",
            f"{self.base_url}/compras/licitacoes",
            f"{self.base_url}/portal/licitacoes",
        ]

        for url in urls_to_try:
            try:
                logger.debug(f"Fetching licitacoes from {url}")
                response = self._make_request(url)

                if response is None:
                    logger.warning(f"Failed to fetch licitacoes from {url}")
                    continue

                # Check if response is JSON
                api_data = self._check_for_api(response.text)
                if api_data:
                    logger.info(f"Found API data at {url}")
                    licitacoes.extend(self._parse_licitacoes_json(api_data, url))
                    break

                # Parse HTML
                soup = BeautifulSoup(response.text, "lxml")
                parsed = self._parse_licitacoes_html(soup, url)
                if parsed:
                    licitacoes.extend(parsed)
                    break

            except Exception as e:
                logger.error(f"Error scraping licitacoes from {url}: {e}")
                continue

        logger.info(f"Scraped {len(licitacoes)} licitacoes")
        return licitacoes

    def _parse_licitacoes_json(
        self, data: Any, url: str
    ) -> list[dict[str, Any]]:
        """Parse licitacoes from JSON API response.

        Args:
            data: JSON data from API.
            url: Source URL for metadata.

        Returns:
            list[dict]: Parsed licitacao records.
        """
        records = []

        # Handle different JSON structures
        items = []
        if isinstance(data, dict):
            items = data.get("data", data.get("records", data.get("items", [])))
        elif isinstance(data, list):
            items = data

        for item in items:
            try:
                record = {
                    "numero": item.get("numero", item.get("numero_licitacao", "")),
                    "ano": item.get("ano", item.get("exercicio", "")),
                    "objeto": item.get("objeto", item.get("descricao", "")),
                    "modalidade": item.get("modalidade", item.get("tipo", "")),
                    "situacao": item.get("situacao", item.get("status", "")),
                    "data_abertura": normalize_data(
                        item.get("data_abertura", item.get("data_abert", ""))
                    ) if item.get("data_abertura") else "",
                    "data_encerramento": normalize_data(
                        item.get("data_encerramento", item.get("data_homolog", ""))
                    ) if item.get("data_encerramento") else "",
                    "valor_estimado": normalize_moeda(
                        str(item.get("valor_estimado", item.get("valor_global", "0")))
                    ),
                    "cnpj_contratada": normalize_cnpj(
                        str(item.get("cnpj_vencedor", item.get("cpf_cnpj", "")))
                    ) if item.get("cnpj_vencedor") or item.get("cpf_cnpj") else "",
                }
                records.append(self._add_metadata(record, url))

            except Exception as e:
                logger.warning(f"Error parsing licitacao item: {e}")
                continue

        return records

    def _parse_licitacoes_html(
        self, soup: BeautifulSoup, url: str
    ) -> list[dict[str, Any]]:
        """Parse licitacoes from HTML page.

        Args:
            soup: BeautifulSoup object of the page.
            url: Source URL for metadata.

        Returns:
            list[dict]: Parsed licitacao records.
        """
        records = []

        # Try common table structures
        rows = soup.select("table tbody tr, .licitacao-row, .result-item, .item")

        for row in rows:
            try:
                record = self._extract_licitacao_row(row, url)
                if record:
                    records.append(record)
            except Exception as e:
                logger.warning(f"Error parsing licitacao row: {e}")
                continue

        # Try links-based parsing for detail pages
        if not records:
            links = soup.select("a[href*='licitacao'], a[href*='edital']")
            for link in links[:10]:  # Limit to avoid too many requests
                try:
                    detail_url = link.get("href", "")
                    if detail_url and not detail_url.startswith("http"):
                        detail_url = f"{self.base_url}{detail_url}"

                    detail_response = self._make_request(detail_url)
                    if detail_response:
                        detail_soup = BeautifulSoup(detail_response.text, "lxml")
                        record = self._extract_licitacao_detail(detail_soup, detail_url)
                        if record:
                            records.append(record)
                except Exception as e:
                    logger.warning(f"Error getting licitacao detail: {e}")
                    continue

        return records

    def _extract_licitacao_row(
        self, row: Any, url: str
    ) -> dict[str, Any] | None:
        """Extract licitacao data from a table row or list item.

        Args:
            row: BeautifulSoup element representing a row.
            url: Source URL for metadata.

        Returns:
            dict | None: Extracted record or None if not valid.
        """
        # Common field selectors
        numero = (
            row.select_one(".numero, .codigo, [class*='num']")
            .get_text(strip=True)
            if row.select_one(".numero, .codigo, [class*='num']")
            else ""
        )
        objeto = (
            row.select_one(".objeto, .descricao, [class*='desc']")
            .get_text(strip=True)
            if row.select_one(".objeto, .descricao, [class*='desc']")
            else ""
        )
        modalidade = (
            row.select_one(".modalidade, .tipo, [class*='modal']")
            .get_text(strip=True)
            if row.select_one(".modalidade, .tipo, [class*='modal']")
            else ""
        )
        situacao = (
            row.select_one(".situacao, .status, [class*='status']")
            .get_text(strip=True)
            if row.select_one(".situacao, .status, [class*='status']")
            else ""
        )
        valor = (
            row.select_one(".valor, [class*='valor']")
            .get_text(strip=True)
            if row.select_one(".valor, [class*='valor']")
            else "0"
        )

        if not numero and not objeto:
            return None

        return self._add_metadata(
            {
                "numero": numero,
                "objeto": objeto,
                "modalidade": modalidade,
                "situacao": situacao,
                "valor_estimado": normalize_moeda(valor),
            },
            url,
        )

    def _extract_licitacao_detail(
        self, soup: BeautifulSoup, url: str
    ) -> dict[str, Any] | None:
        """Extract detailed licitacao data from a detail page.

        Args:
            soup: BeautifulSoup object of the detail page.
            url: Source URL for metadata.

        Returns:
            dict | None: Extracted record or None if not valid.
        """
        # Extract data from detail page tables or divs
        fields = {}

        for row in soup.select("table tr, .field-row, .detail-row"):
            label_elem = row.select_one("th, .label, [class*='label']")
            value_elem = row.select_one("td, .value, [class*='value']")

            if label_elem and value_elem:
                label = label_elem.get_text(strip=True).lower()
                value = value_elem.get_text(strip=True)

                if "numero" in label:
                    fields["numero"] = value
                elif "objeto" in label or "descricao" in label:
                    fields["objeto"] = value
                elif "modalidade" in label:
                    fields["modalidade"] = value
                elif "data" in label:
                    fields["data"] = value
                elif "valor" in label:
                    fields["valor"] = value
                elif "situacao" in label:
                    fields["situacao"] = value

        if not fields:
            return None

        return self._add_metadata(
            {
                "numero": fields.get("numero", ""),
                "objeto": fields.get("objeto", ""),
                "modalidade": fields.get("modalidade", ""),
                "situacao": fields.get("situacao", ""),
                "data": normalize_data(fields.get("data", "")),
                "valor_estimado": normalize_moeda(fields.get("valor", "0")),
            },
            url,
        )

    def scrape_contratos(self) -> list[dict[str, Any]]:
        """Scrape contract data (contratos).

        Returns:
            list[dict]: List of contract records with metadata.
        """
        logger.info("Starting to scrape contratos (contract data)")
        contratos = []

        # Common URL patterns for contratos
        urls_to_try = [
            f"{self.base_url}/contratos",
            f"{self.base_url}/compras/contratos",
            f"{self.base_url}/portal/contratos",
            f"{self.base_url}/contratos/aditivos",
        ]

        for url in urls_to_try:
            try:
                logger.debug(f"Fetching contratos from {url}")
                response = self._make_request(url)

                if response is None:
                    logger.warning(f"Failed to fetch contratos from {url}")
                    continue

                # Check if response is JSON
                api_data = self._check_for_api(response.text)
                if api_data:
                    logger.info(f"Found API data at {url}")
                    contratos.extend(self._parse_contratos_json(api_data, url))
                    break

                # Parse HTML
                soup = BeautifulSoup(response.text, "lxml")
                parsed = self._parse_contratos_html(soup, url)
                if parsed:
                    contratos.extend(parsed)
                    break

            except Exception as e:
                logger.error(f"Error scraping contratos from {url}: {e}")
                continue

        logger.info(f"Scraped {len(contratos)} contratos")
        return contratos

    def _parse_contratos_json(
        self, data: Any, url: str
    ) -> list[dict[str, Any]]:
        """Parse contratos from JSON API response.

        Args:
            data: JSON data from API.
            url: Source URL for metadata.

        Returns:
            list[dict]: Parsed contrato records.
        """
        records = []

        items = []
        if isinstance(data, dict):
            items = data.get("data", data.get("records", data.get("items", [])))
        elif isinstance(data, list):
            items = data

        for item in items:
            try:
                record = {
                    "numero_contrato": item.get("numero_contrato", item.get("numero", "")),
                    "ano": item.get("ano", item.get("exercicio", "")),
                    "objeto": item.get("objeto", item.get("descricao", "")),
                    "fornecedor": item.get("fornecedor", item.get("contratada", "")),
                    "cnpj_fornecedor": normalize_cnpj(
                        str(item.get("cnpj_fornecedor", item.get("cnpj", "")))
                    ) if item.get("cnpj_fornecedor") or item.get("cnpj") else "",
                    "valor_contrato": normalize_moeda(
                        str(item.get("valor_contrato", item.get("valor", "0")))
                    ),
                    "data_inicio": normalize_data(
                        item.get("data_inicio", item.get("data_assinatura", ""))
                    ) if item.get("data_inicio") else "",
                    "data_fim": normalize_data(
                        item.get("data_fim", item.get("data_vencimento", ""))
                    ) if item.get("data_fim") else "",
                    "situacao": item.get("situacao", item.get("status", "")),
                }
                records.append(self._add_metadata(record, url))

            except Exception as e:
                logger.warning(f"Error parsing contrato item: {e}")
                continue

        return records

    def _parse_contratos_html(
        self, soup: BeautifulSoup, url: str
    ) -> list[dict[str, Any]]:
        """Parse contratos from HTML page.

        Args:
            soup: BeautifulSoup object of the page.
            url: Source URL for metadata.

        Returns:
            list[dict]: Parsed contrato records.
        """
        records = []

        rows = soup.select("table tbody tr, .contrato-row, .contract-item, .item")

        for row in rows:
            try:
                record = self._extract_contrato_row(row, url)
                if record:
                    records.append(record)
            except Exception as e:
                logger.warning(f"Error parsing contrato row: {e}")
                continue

        return records

    def _extract_contrato_row(
        self, row: Any, url: str
    ) -> dict[str, Any] | None:
        """Extract contrato data from a table row.

        Args:
            row: BeautifulSoup element representing a row.
            url: Source URL for metadata.

        Returns:
            dict | None: Extracted record or None if not valid.
        """
        numero = (
            row.select_one(".numero, .codigo, [class*='num']")
            .get_text(strip=True)
            if row.select_one(".numero, .codigo, [class*='num']")
            else ""
        )
        objeto = (
            row.select_one(".objeto, .descricao, [class*='desc']")
            .get_text(strip=True)
            if row.select_one(".objeto, .descricao, [class*='desc']")
            else ""
        )
        fornecedor = (
            row.select_one(".fornecedor, .contratada, [class*='fornec']")
            .get_text(strip=True)
            if row.select_one(".fornecedor, .contratada, [class*='fornec']")
            else ""
        )
        valor = (
            row.select_one(".valor, [class*='valor']")
            .get_text(strip=True)
            if row.select_one(".valor, [class*='valor']")
            else "0"
        )
        situacao = (
            row.select_one(".situacao, .status, [class*='status']")
            .get_text(strip=True)
            if row.select_one(".situacao, .status, [class*='status']")
            else ""
        )

        if not numero and not objeto:
            return None

        return self._add_metadata(
            {
                "numero_contrato": numero,
                "objeto": objeto,
                "fornecedor": fornecedor,
                "valor_contrato": normalize_moeda(valor),
                "situacao": situacao,
            },
            url,
        )

    def scrape_fornecedores(self) -> list[dict[str, Any]]:
        """Scrape supplier data (fornecedores).

        Returns:
            list[dict]: List of supplier records with metadata.
        """
        logger.info("Starting to scrape fornecedores (supplier data)")
        fornecedores = []

        # Common URL patterns for fornecedores
        urls_to_try = [
            f"{self.base_url}/fornecedores",
            f"{self.base_url}/cadastro/fornecedores",
            f"{self.base_url}/portal/fornecedores",
        ]

        for url in urls_to_try:
            try:
                logger.debug(f"Fetching fornecedores from {url}")
                response = self._make_request(url)

                if response is None:
                    logger.warning(f"Failed to fetch fornecedores from {url}")
                    continue

                # Check if response is JSON
                api_data = self._check_for_api(response.text)
                if api_data:
                    logger.info(f"Found API data at {url}")
                    fornecedores.extend(self._parse_fornecedores_json(api_data, url))
                    break

                # Parse HTML
                soup = BeautifulSoup(response.text, "lxml")
                parsed = self._parse_fornecedores_html(soup, url)
                if parsed:
                    fornecedores.extend(parsed)
                    break

            except Exception as e:
                logger.error(f"Error scraping fornecedores from {url}: {e}")
                continue

        logger.info(f"Scraped {len(fornecedores)} fornecedores")
        return fornecedores

    def _parse_fornecedores_json(
        self, data: Any, url: str
    ) -> list[dict[str, Any]]:
        """Parse fornecedores from JSON API response.

        Args:
            data: JSON data from API.
            url: Source URL for metadata.

        Returns:
            list[dict]: Parsed fornecedor records.
        """
        records = []

        items = []
        if isinstance(data, dict):
            items = data.get("data", data.get("records", data.get("items", [])))
        elif isinstance(data, list):
            items = data

        for item in items:
            try:
                record = {
                    "razao_social": item.get("razao_social", item.get("nome", "")),
                    "nome_fantasia": item.get("nome_fantasia", item.get("fantasia", "")),
                    "cnpj": normalize_cnpj(
                        str(item.get("cnpj", item.get("cpf_cnpj", "")))
                    ) if item.get("cnpj") or item.get("cpf_cnpj") else "",
                    "endereco": item.get("endereco", item.get("logradouro", "")),
                    "cidade": item.get("cidade", item.get("municipio", "")),
                    "uf": item.get("uf", item.get("estado", "")),
                    "telefone": item.get("telefone", item.get("fone", "")),
                    "email": item.get("email", item.get("e-mail", "")),
                    "situacao": item.get("situacao", item.get("status", "Ativo")),
                }
                records.append(self._add_metadata(record, url))

            except Exception as e:
                logger.warning(f"Error parsing fornecedor item: {e}")
                continue

        return records

    def _parse_fornecedores_html(
        self, soup: BeautifulSoup, url: str
    ) -> list[dict[str, Any]]:
        """Parse fornecedores from HTML page.

        Args:
            soup: BeautifulSoup object of the page.
            url: Source URL for metadata.

        Returns:
            list[dict]: Parsed fornecedor records.
        """
        records = []

        rows = soup.select("table tbody tr, .fornecedor-row, .supplier-item, .item")

        for row in rows:
            try:
                record = self._extract_fornecedor_row(row, url)
                if record:
                    records.append(record)
            except Exception as e:
                logger.warning(f"Error parsing fornecedor row: {e}")
                continue

        return records

    def _extract_fornecedor_row(
        self, row: Any, url: str
    ) -> dict[str, Any] | None:
        """Extract fornecedor data from a table row.

        Args:
            row: BeautifulSoup element representing a row.
            url: Source URL for metadata.

        Returns:
            dict | None: Extracted record or None if not valid.
        """
        nome = (
            row.select_one(".razao-social, .nome, .fornecedor, [class*='nome']")
            .get_text(strip=True)
            if row.select_one(".razao-social, .nome, .fornecedor, [class*='nome']")
            else ""
        )
        cnpj = (
            row.select_one(".cnpj, [class*='cnpj'], [class*='cpf']")
            .get_text(strip=True)
            if row.select_one(".cnpj, [class*='cnpj'], [class*='cpf']")
            else ""
        )
        cidade = (
            row.select_one(".cidade, .municipio, [class*='cidade']")
            .get_text(strip=True)
            if row.select_one(".cidade, .municipio, [class*='cidade']")
            else ""
        )
        situacao = (
            row.select_one(".situacao, .status, [class*='status']")
            .get_text(strip=True)
            if row.select_one(".situacao, .status, [class*='status']")
            else "Ativo"
        )

        if not nome:
            return None

        return self._add_metadata(
            {
                "razao_social": nome,
                "cnpj": normalize_cnpj(cnpj) if cnpj else "",
                "cidade": cidade,
                "situacao": situacao,
            },
            url,
        )

    def scrape(self) -> dict[str, Any]:
        """Run all scrapers and return summary.

        Executes scraping for licitacoes, contratos, and fornecedores,
        saving each to its own JSON file.

        Returns:
            dict: Summary with counts of items scraped and any errors.
        """
        logger.info(f"Starting full scrape for {self.name}")
        summary = {
            "scraper": self.name,
            "data_coleta": self.data_coleta,
            "resultados": {
                "licitacoes": {"total": 0, "arquivo": self.licitacoes_file},
                "contratos": {"total": 0, "arquivo": self.contratos_file},
                "fornecedores": {"total": 0, "arquivo": self.fornecedores_file},
            },
            "erros": [],
        }

        # Scrape licitacoes
        try:
            licitacoes = self.scrape_licitacoes()
            summary["resultados"]["licitacoes"]["total"] = len(licitacoes)
            if licitacoes:
                self._save_to_json(licitacoes, self.licitacoes_file)
                logger.info(f"Saved {len(licitacoes)} licitacoes to {self.licitacoes_file}")
        except Exception as e:
            error_msg = f"Error scraping licitacoes: {e}"
            logger.error(error_msg)
            summary["erros"].append(error_msg)

        # Scrape contratos
        try:
            contratos = self.scrape_contratos()
            summary["resultados"]["contratos"]["total"] = len(contratos)
            if contratos:
                self._save_to_json(contratos, self.contratos_file)
                logger.info(f"Saved {len(contratos)} contratos to {self.contratos_file}")
        except Exception as e:
            error_msg = f"Error scraping contratos: {e}"
            logger.error(error_msg)
            summary["erros"].append(error_msg)

        # Scrape fornecedores
        try:
            fornecedores = self.scrape_fornecedores()
            summary["resultados"]["fornecedores"]["total"] = len(fornecedores)
            if fornecedores:
                self._save_to_json(fornecedores, self.fornecedores_file)
                logger.info(f"Saved {len(fornecedores)} fornecedores to {self.fornecedores_file}")
        except Exception as e:
            error_msg = f"Error scraping fornecedores: {e}"
            logger.error(error_msg)
            summary["erros"].append(error_msg)

        # Calculate totals
        summary["total_geral"] = sum(
            r["total"] for r in summary["resultados"].values()
        )

        logger.info(
            f"Completed scrape for {self.name}: "
            f"{summary['total_geral']} total records, "
            f"{len(summary['erros'])} errors"
        )

        return summary