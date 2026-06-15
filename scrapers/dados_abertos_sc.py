"""Scraper para o Portal de Dados Abertos de Santa Catarina.

Fonte: https://dados.sc.gov.br/organization
API:   https://dados.sc.gov.br/api/3/action/

Descobre organizações e seus conjuntos de dados via API CKAN (fallback HTML),
baixa um arquivo por dataset na prioridade JSON → CSV → XLSX → outros e salva em:

    data/dados_abertos_sc/<Organizacao sem acentos>/<dataset_slug>/<arquivo>

Datasets com "covid" no identificador ou título são ignorados.
Recursos que retornam erro de servidor ou HTML inválido são pulados e registrados
em ``data/dados_abertos_sc/manifest.json``.
Links externos (formato HTML) disparam tentativa de scrape da página em busca
de arquivos para download.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
import unicodedata
import urllib.parse
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
import urllib3
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scrapers.base_scraper import BaseScraper

logger = logging.getLogger(__name__)

API_BASE = "https://dados.sc.gov.br/api/3/action"
PORTAL_URL = "https://dados.sc.gov.br"
ORG_LIST_URL = f"{PORTAL_URL}/organization"

OUTPUT_ROOT = Path(__file__).parent.parent / "data" / "dados_abertos_sc"
MANIFEST_PATH = OUTPUT_ROOT / "manifest.json"

FORMAT_PRIORITY: dict[str, int] = {
    "JSON": 0,
    "GEOJSON": 0,
    "CSV": 1,
    "XLS": 2,
    "XLSX": 2,
    "XML": 3,
    "PARQUET": 4,
    "ZIP": 5,
    "SHP": 5,
    "PDF": 6,
    "HTML": 99,
}

DOWNLOAD_EXTENSIONS = (".json", ".csv", ".xlsx", ".xls", ".xml", ".zip", ".parquet", ".geojson")

_INVALID_PATH_CHARS = re.compile(r'[<>:"/\\|?*]')
_WS_RE = re.compile(r"\s+")
_COVID_RE = re.compile(r"covid", re.IGNORECASE)


@dataclass
class DownloadResult:
    """Outcome for a single dataset download attempt."""

    organizacao: str
    organizacao_slug: str
    dataset: str
    dataset_title: str
    arquivo: str | None = None
    caminho: str | None = None
    url: str | None = None
    formato: str | None = None
    bytes: int | None = None
    sucesso: bool = False
    erro: str | None = None
    pulado_covid: bool = False


@dataclass
class ScrapeSummary:
    """Aggregate counters returned by ``scrape()``."""

    total_orgs: int = 0
    total_datasets: int = 0
    skipped_covid: int = 0
    downloaded: int = 0
    failed: int = 0
    skipped_existing: int = 0
    manifest_path: str = ""
    output_dir: str = ""
    results: list[DownloadResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class DadosAbertosScScraper(BaseScraper):
    """Downloader for dados.sc.gov.br CKAN datasets grouped by organization."""

    def __init__(self, rate_limit_delay: float = 1.0) -> None:
        """Initialize scraper paths and HTTP defaults."""
        super().__init__(
            name="dados_abertos_sc",
            base_url=PORTAL_URL,
            rate_limit_delay=rate_limit_delay,
        )
        self.output_root = OUTPUT_ROOT
        self.output_root.mkdir(parents=True, exist_ok=True)
        self._session = requests.Session()
        self._session.verify = False
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        # CKAN API is slow; allow longer reads than BaseScraper default.
        self._request_timeout = 120

    # ------------------------------------------------------------------ #
    # Naming helpers                                                      #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _strip_accents(text: str) -> str:
        """Remove diacritics while keeping base letters."""
        normalized = unicodedata.normalize("NFKD", text)
        return "".join(ch for ch in normalized if not unicodedata.combining(ch))

    @classmethod
    def _sanitize_org_folder(cls, title: str) -> str:
        """Build a Windows-safe folder name: spaces ok, no accents."""
        cleaned = cls._strip_accents(title.strip())
        cleaned = _INVALID_PATH_CHARS.sub("", cleaned)
        cleaned = _WS_RE.sub(" ", cleaned).strip()
        return cleaned or "Sem organizacao"

    @staticmethod
    def _format_rank(fmt: str | None) -> int:
        """Lower rank means higher download priority."""
        key = (fmt or "").upper().strip()
        return FORMAT_PRIORITY.get(key, 50)

    @staticmethod
    def _is_covid_dataset(package: dict[str, Any]) -> bool:
        """Return True when the dataset should be skipped (COVID legacy)."""
        for field_name in ("name", "title", "id"):
            value = package.get(field_name) or ""
            if _COVID_RE.search(str(value)):
                return True
        return False

    # ------------------------------------------------------------------ #
    # CKAN API                                                            #
    # ------------------------------------------------------------------ #

    def _api_get(self, action: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
        """Call a CKAN action; return the ``result`` payload or None."""
        url = f"{API_BASE}/{action}"
        self._apply_rate_limit()
        try:
            response = self._session.get(
                url,
                params=params or {},
                headers=self._get_headers(),
                timeout=self._request_timeout,
            )
            if response.status_code >= 500:
                logger.warning("CKAN %s returned %s", action, response.status_code)
                return None
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, json.JSONDecodeError) as exc:
            logger.warning("CKAN %s failed: %s", action, exc)
            return None

        if not payload.get("success"):
            logger.warning("CKAN %s unsuccessful: %s", action, payload.get("error"))
            return None
        return payload.get("result")

    def _list_organizations_api(self) -> list[dict[str, str]]:
        """Return organization slugs and titles from the CKAN API."""
        slugs = self._api_get("organization_list")
        if not isinstance(slugs, list):
            return []

        orgs: list[dict[str, str]] = []
        for slug in slugs:
            detail = self._api_get("organization_show", {"id": slug, "include_datasets": False})
            if not isinstance(detail, dict):
                orgs.append({"name": slug, "title": slug})
                continue
            orgs.append(
                {
                    "name": detail.get("name") or slug,
                    "title": detail.get("title") or slug,
                }
            )
        return orgs

    def _list_datasets_for_org_api(self, org_slug: str) -> tuple[list[dict[str, Any]], bool]:
        """Return package dicts for one organization and whether the API worked."""
        rows = 200
        start = 0
        packages: list[dict[str, Any]] = []
        api_ok = True

        while True:
            result = self._api_get(
                "package_search",
                {
                    "fq": f"organization:{org_slug}",
                    "rows": rows,
                    "start": start,
                },
            )
            if result is None:
                api_ok = False
                break
            if not isinstance(result, dict):
                api_ok = False
                break

            batch = result.get("results") or []
            packages.extend(batch)
            count = int(result.get("count") or 0)
            start += len(batch)
            if start >= count or not batch:
                break

        return packages, api_ok

    def _package_show_api(self, dataset_id: str) -> dict[str, Any] | None:
        """Fetch a single dataset with resources."""
        result = self._api_get("package_show", {"id": dataset_id})
        return result if isinstance(result, dict) else None

    # ------------------------------------------------------------------ #
    # HTML fallback                                                       #
    # ------------------------------------------------------------------ #

    def _fetch_html(self, url: str) -> str | None:
        """GET a portal page and return text, or None on failure."""
        self._apply_rate_limit()
        try:
            response = self._session.get(
                url,
                headers=self._get_headers(),
                timeout=self._request_timeout,
            )
            if response.status_code >= 400:
                return None
            return response.text
        except requests.RequestException as exc:
            logger.warning("HTML fetch failed for %s: %s", url, exc)
            return None

    def _list_organizations_html(self) -> list[dict[str, str]]:
        """Parse /organization when the API is unavailable."""
        html = self._fetch_html(ORG_LIST_URL)
        if not html:
            return []

        soup = BeautifulSoup(html, "lxml")
        orgs: list[dict[str, str]] = []
        seen: set[str] = set()

        for anchor in soup.select("a[href*='/organization/']"):
            href = anchor.get("href") or ""
            match = re.search(r"/organization/([^/?#]+)", href)
            if not match:
                continue
            slug = match.group(1)
            if slug in seen or slug in ("new", "edit"):
                continue
            seen.add(slug)
            title = anchor.get_text(strip=True) or slug
            orgs.append({"name": slug, "title": title})

        return orgs

    def _list_dataset_ids_html(self, org_slug: str) -> list[str]:
        """Parse dataset slugs from an organization page."""
        html = self._fetch_html(f"{PORTAL_URL}/organization/{org_slug}")
        if not html:
            return []

        soup = BeautifulSoup(html, "lxml")
        ids: list[str] = []
        seen: set[str] = set()
        for anchor in soup.select("a[href*='/dataset/']"):
            href = anchor.get("href") or ""
            match = re.search(r"/dataset/([^/?#]+)", href)
            if not match:
                continue
            dataset_id = match.group(1)
            if dataset_id in seen:
                continue
            seen.add(dataset_id)
            ids.append(dataset_id)
        return ids

    # ------------------------------------------------------------------ #
    # Resource selection & validation                                     #
    # ------------------------------------------------------------------ #

    def _sort_resources(self, resources: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Order resources by format priority, then recency (newest first)."""
        by_date = sorted(
            resources,
            key=lambda res: res.get("last_modified") or res.get("created") or "",
            reverse=True,
        )
        return sorted(by_date, key=lambda res: self._format_rank(res.get("format")))

    @staticmethod
    def _guess_filename(url: str, resource: dict[str, Any]) -> str:
        """Derive a safe local filename from resource metadata."""
        name = (resource.get("name") or "").strip()
        if name:
            return re.sub(r'[<>:"/\\|?*]', "_", name)

        parsed = urllib.parse.urlparse(url)
        basename = Path(parsed.path).name
        if basename:
            return re.sub(r'[<>:"/\\|?*]', "_", basename)

        fmt = (resource.get("format") or "bin").lower()
        return f"resource.{fmt}"

    @staticmethod
    def _content_looks_valid(body: bytes, fmt: str, content_type: str) -> bool:
        """Reject HTML error pages masquerading as data files."""
        if not body or len(body) < 16:
            return False

        lowered_type = (content_type or "").lower()
        if "text/html" in lowered_type:
            return False

        head = body[:512].lstrip().lower()
        if head.startswith(b"<!doctype") or head.startswith(b"<html"):
            return False

        fmt_key = fmt.upper()
        if fmt_key in ("JSON", "GEOJSON"):
            try:
                json.loads(body.decode("utf-8-sig"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                return False

        return True

    def _download_bytes(self, url: str) -> tuple[bytes | None, str, str | None]:
        """Download a URL; return body, content-type, and error message."""
        self._apply_rate_limit()
        try:
            response = self._session.get(
                url,
                headers=self._get_headers(),
                timeout=self._request_timeout,
                allow_redirects=True,
            )
        except requests.RequestException as exc:
            return None, "", str(exc)

        if response.status_code >= 500:
            return None, response.headers.get("Content-Type", ""), f"HTTP {response.status_code}"
        if response.status_code >= 400:
            return None, response.headers.get("Content-Type", ""), f"HTTP {response.status_code}"

        content_type = response.headers.get("Content-Type", "")
        return response.content, content_type, None

    def _save_if_valid(
        self,
        body: bytes,
        content_type: str,
        fmt: str,
        dest_path: Path,
    ) -> bool:
        """Validate and persist bytes to disk."""
        if not self._content_looks_valid(body, fmt, content_type):
            return False
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_bytes(body)
        return True

    def _discover_external_links(self, page_url: str) -> list[dict[str, Any]]:
        """Find downloadable file links on an external HTML page."""
        html = self._fetch_html(page_url)
        if not html:
            return []

        soup = BeautifulSoup(html, "lxml")
        found: list[dict[str, Any]] = []
        seen: set[str] = set()

        for anchor in soup.find_all("a", href=True):
            href = anchor["href"].strip()
            if not href or href.startswith("#"):
                continue
            absolute = urllib.parse.urljoin(page_url, href)
            if absolute in seen:
                continue
            lower = absolute.lower()
            if not any(lower.endswith(ext) for ext in DOWNLOAD_EXTENSIONS):
                continue
            seen.add(absolute)
            ext = Path(urllib.parse.urlparse(absolute).path).suffix.lstrip(".").upper()
            found.append(
                {
                    "url": absolute,
                    "format": ext or "BIN",
                    "name": Path(urllib.parse.urlparse(absolute).path).name,
                }
            )

        return self._sort_resources(found)

    # ------------------------------------------------------------------ #
    # Per-dataset download                                                #
    # ------------------------------------------------------------------ #

    def _try_resources(
        self,
        resources: list[dict[str, Any]],
        dest_dir: Path,
    ) -> tuple[Path | None, dict[str, Any] | None, str | None]:
        """Try each resource in priority order until one saves successfully."""
        last_error: str | None = None

        for resource in self._sort_resources(resources):
            url = (resource.get("url") or "").strip()
            if not url:
                continue

            fmt = (resource.get("format") or "").upper()
            filename = self._guess_filename(url, resource)
            dest_path = dest_dir / filename

            if dest_path.exists() and dest_path.stat().st_size > 0:
                return dest_path, resource, "cached"

            if fmt == "HTML" or resource.get("url_type") is None:
                external_files = self._discover_external_links(url)
                for external in external_files:
                    ext_url = external["url"]
                    ext_fmt = external.get("format") or "BIN"
                    ext_name = external.get("name") or self._guess_filename(ext_url, external)
                    ext_dest = dest_dir / ext_name
                    if ext_dest.exists() and ext_dest.stat().st_size > 0:
                        return ext_dest, external, "cached"

                    body, content_type, err = self._download_bytes(ext_url)
                    if err:
                        last_error = err
                        continue
                    if body and self._save_if_valid(body, content_type, ext_fmt, ext_dest):
                        return ext_dest, external, None
                    last_error = "conteudo invalido no link externo"
                if not external_files:
                    last_error = "nenhum arquivo encontrado na pagina externa"
                continue

            body, content_type, err = self._download_bytes(url)
            if err:
                last_error = err
                continue
            if body and self._save_if_valid(body, content_type, fmt, dest_path):
                return dest_path, resource, None
            last_error = "conteudo invalido (provavel HTML ou arquivo corrompido)"

        return None, None, last_error or "nenhum recurso utilizavel"

    def _process_dataset(
        self,
        package: dict[str, Any],
        org_title: str,
        org_slug: str,
    ) -> DownloadResult:
        """Download the best available resource for one dataset."""
        dataset_slug = package.get("name") or package.get("id") or "dataset"
        dataset_title = package.get("title") or dataset_slug
        result = DownloadResult(
            organizacao=org_title,
            organizacao_slug=org_slug,
            dataset=dataset_slug,
            dataset_title=dataset_title,
        )

        if self._is_covid_dataset(package):
            result.pulado_covid = True
            result.erro = "dataset COVID ignorado"
            return result

        org_folder = self._sanitize_org_folder(org_title)
        dest_dir = self.output_root / org_folder / dataset_slug

        resources = package.get("resources") or []
        if not resources:
            full = self._package_show_api(dataset_slug)
            if full:
                resources = full.get("resources") or []
                package = full

        if not resources:
            result.erro = "dataset sem recursos"
            return result

        saved_path, used_resource, error = self._try_resources(resources, dest_dir)
        if saved_path is None:
            result.erro = error
            return result

        existed_before = error == "cached"
        result.sucesso = True
        result.arquivo = saved_path.name
        result.caminho = str(saved_path)
        result.url = used_resource.get("url") if used_resource else None
        result.formato = used_resource.get("format") if used_resource else None
        result.bytes = saved_path.stat().st_size
        if existed_before:
            result.erro = "arquivo ja existia"
        return result

    # ------------------------------------------------------------------ #
    # Manifest & orchestration                                            #
    # ------------------------------------------------------------------ #

    def _write_manifest(self, summary: ScrapeSummary) -> Path:
        """Persist success/failure log for this run."""
        successes = [asdict(r) for r in summary.results if r.sucesso]
        failures = [
            asdict(r)
            for r in summary.results
            if not r.sucesso and not r.pulado_covid
        ]
        skipped_covid = [asdict(r) for r in summary.results if r.pulado_covid]

        payload = {
            "metadata": {
                "fonte": self.name,
                "url_origem": ORG_LIST_URL,
                "data_coleta": datetime.now(timezone.utc).isoformat(),
                "total_orgs": summary.total_orgs,
                "total_datasets": summary.total_datasets,
                "downloaded": summary.downloaded,
                "failed": summary.failed,
                "skipped_covid": summary.skipped_covid,
                "skipped_existing": summary.skipped_existing,
                "output_dir": str(self.output_root),
            },
            "sucessos": successes,
            "falhas": failures,
            "ignorados_covid": skipped_covid,
        }

        with open(MANIFEST_PATH, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        logger.info("Manifest escrito em %s", MANIFEST_PATH)
        return MANIFEST_PATH

    def scrape(self) -> dict[str, Any]:
        """Discover organizations, download datasets, write manifest."""
        start = time.time()
        summary = ScrapeSummary(output_dir=str(self.output_root))

        orgs = self._list_organizations_api()
        if not orgs:
            logger.warning("API de organizacoes indisponivel; tentando HTML")
            orgs = self._list_organizations_html()
        if not orgs:
            summary.errors.append("Nenhuma organizacao encontrada")
            return asdict(summary)

        summary.total_orgs = len(orgs)
        logger.info("Organizacoes encontradas: %d", len(orgs))

        for org in orgs:
            org_slug = org["name"]
            org_title = org["title"]
            logger.info("Organizacao: %s (%s)", org_title, org_slug)

            packages, api_ok = self._list_datasets_for_org_api(org_slug)
            if not api_ok:
                logger.warning("API indisponivel para %s; tentando HTML", org_slug)
                dataset_ids = self._list_dataset_ids_html(org_slug)
                packages = []
                for dataset_id in dataset_ids:
                    pkg = self._package_show_api(dataset_id)
                    if pkg:
                        packages.append(pkg)
                    else:
                        packages.append({"name": dataset_id, "title": dataset_id, "resources": []})

            for package in packages:
                summary.total_datasets += 1
                result = self._process_dataset(package, org_title, org_slug)
                summary.results.append(result)

                if result.pulado_covid:
                    summary.skipped_covid += 1
                    logger.info("  [COVID] %s — ignorado", result.dataset)
                    continue

                if result.sucesso:
                    if result.erro == "arquivo ja existia":
                        summary.skipped_existing += 1
                    else:
                        summary.downloaded += 1
                    logger.info(
                        "  [OK] %s -> %s (%s bytes)%s",
                        result.dataset,
                        result.arquivo,
                        result.bytes,
                        " (cache)" if result.erro == "arquivo ja existia" else "",
                    )
                else:
                    summary.failed += 1
                    logger.warning("  [FAIL] %s — %s", result.dataset, result.erro)

        manifest_path = self._write_manifest(summary)
        summary.manifest_path = str(manifest_path)

        elapsed = time.time() - start
        logger.info(
            "Dados Abertos SC concluido em %.1fs: %d baixados, %d falhas, %d COVID ignorados",
            elapsed,
            summary.downloaded,
            summary.failed,
            summary.skipped_covid,
        )
        return asdict(summary)


if __name__ == "__main__":
    import urllib3

    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    scraper = DadosAbertosScScraper()
    summary = scraper.scrape()
    print(json.dumps(summary, indent=2, ensure_ascii=True))
    print(f"Manifest: {MANIFEST_PATH}")
