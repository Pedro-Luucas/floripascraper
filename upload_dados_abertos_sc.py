"""Upload arquivos de data/dados_abertos_sc para a API CragAncora.

Autenticacao: POST https://ancora.craggroup.com/api/auth/login
Upload:       POST https://ancora.craggroup.com/api/documents/upload

Usa o manifest.json do scraper para titulo, formato e origin_url.
Credenciais e URLs ficam em ``.env`` na raiz do projeto.

Usage:
    python upload_dados_abertos_sc.py --dry-run
    python upload_dados_abertos_sc.py
    python upload_dados_abertos_sc.py --file "Secretaria de Estado da Fazenda/tev/tev.xlsx"
    python upload_dados_abertos_sc.py --check-status
"""

from __future__ import annotations

import argparse
import json
import logging
import mimetypes
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
import urllib3

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

ENV_PATH = Path(__file__).parent / ".env"


def load_env_file(path: Path = ENV_PATH) -> None:
    """Load KEY=VALUE pairs from .env without overwriting existing env vars."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if not sep:
            continue
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


load_env_file()

API_BASE = os.getenv("ANCORA_API_BASE", "https://ancora.craggroup.com").rstrip("/")
API_LOGIN_ENDPOINT = os.getenv("ANCORA_LOGIN_URL", f"{API_BASE}/api/auth/login")
API_UPLOAD_ENDPOINT = os.getenv("ANCORA_UPLOAD_URL", f"{API_BASE}/api/documents/upload")
API_STATUS_ENDPOINT = os.getenv("ANCORA_STATUS_URL", f"{API_BASE}/api/documents")

DATA_ROOT = Path(__file__).parent / "data" / "dados_abertos_sc"
MANIFEST_PATH = DATA_ROOT / "manifest.json"
UPLOAD_LOG_PATH = DATA_ROOT / "upload_manifest.json"

SKIP_FILENAMES = {"manifest.json", "scrape_run.log", "upload_manifest.json"}

FORMAT_BY_EXT: dict[str, str] = {
    ".json": "json",
    ".geojson": "json",
    ".csv": "csv",
    ".xlsx": "xlsx",
    ".xls": "xls",
    ".pdf": "pdf",
    ".html": "html",
    ".htm": "html",
    ".txt": "txt",
    ".md": "md",
    ".docx": "docx",
}

FORMAT_BY_LABEL: dict[str, str] = {
    "JSON": "json",
    "GEOJSON": "json",
    "CSV": "csv",
    "XLSX": "xlsx",
    "XLS": "xls",
    "PDF": "pdf",
    "HTML": "html",
    "TXT": "txt",
    "XML": "txt",
    "PARQUET": "csv",
}

UNSUPPORTED_LABELS = {"PNG", "ZIP", "GIF", "JPG", "JPEG"}

FORMAT_TO_EXT: dict[str, str] = {
    "json": ".json",
    "csv": ".csv",
    "xlsx": ".xlsx",
    "xls": ".xls",
    "pdf": ".pdf",
    "html": ".html",
    "txt": ".txt",
    "md": ".md",
    "docx": ".docx",
}


KNOWN_EXTENSIONS = set(FORMAT_BY_EXT.keys())


def _upload_filename(path: Path, fmt: str) -> str:
    """Ensure multipart filename has an extension the API accepts."""
    suffix = path.suffix.lower()
    if suffix in KNOWN_EXTENSIONS:
        return path.name
    ext = FORMAT_TO_EXT.get(fmt, "")
    return f"{path.name}{ext}" if ext else path.name


@dataclass
class UploadItem:
    """One file queued for upload."""

    path: Path
    title: str
    format: str
    origin_url: str
    organizacao: str = ""
    dataset: str = ""
    bytes: int = 0


@dataclass
class UploadResult:
    """Outcome of one upload attempt."""

    path: str
    title: str
    format: str
    success: bool = False
    document_id: str | None = None
    status: str | None = None
    error: str | None = None


@dataclass
class UploadSummary:
    """Aggregate upload run."""

    total: int = 0
    success: int = 0
    failed: int = 0
    skipped: int = 0
    results: list[UploadResult] = field(default_factory=list)


def _resolve_password(password: str | None) -> str | None:
    """Read API password from CLI flag, .env, or environment."""
    return password or os.getenv("ANCORA_PASSWORD")


def login_session(
    password: str,
    verify_ssl: bool = False,
) -> requests.Session | None:
    """Authenticate and return a session with the cragcitys_session cookie."""
    session = requests.Session()
    session.verify = verify_ssl
    try:
        response = session.post(
            API_LOGIN_ENDPOINT,
            json={"password": password},
            timeout=30,
        )
    except requests.RequestException as exc:
        logger.error("Falha no login: %s", exc)
        return None

    if response.status_code >= 400:
        logger.error("Login falhou (HTTP %s): %s", response.status_code, response.text[:200])
        return None

    try:
        payload = response.json()
    except json.JSONDecodeError:
        logger.error("Login retornou resposta invalida: %s", response.text[:200])
        return None

    if not payload.get("authenticated"):
        logger.error("Login nao autenticou: %s", payload)
        return None

    if not session.cookies:
        logger.error("Login OK mas nenhum cookie de sessao recebido")
        return None

    logger.info("Login OK (sessao autenticada)")
    return session


def _normalize_path(path: str | Path) -> Path:
    """Return a resolved Path for cross-platform manifest matching."""
    return Path(path).resolve()


def _guess_format(path: Path, label: str | None = None) -> str | None:
    """Map file extension or manifest label to API format (known extension wins)."""
    ext = path.suffix.lower()
    if ext in KNOWN_EXTENSIONS:
        mapped = FORMAT_BY_EXT.get(ext)
        if mapped:
            return mapped

    name_lower = path.name.lower()
    for ext_key, fmt in FORMAT_BY_EXT.items():
        if name_lower.endswith(ext_key):
            return fmt

    if label and label.upper().strip() in UNSUPPORTED_LABELS:
        return None

    if label:
        mapped = FORMAT_BY_LABEL.get(label.upper().strip())
        if mapped:
            return mapped

    return None


def _build_title(organizacao: str, dataset_title: str, arquivo: str) -> str:
    """Readable document title for the API."""
    base = dataset_title.strip() or arquivo.strip() or "Documento"
    org = organizacao.strip()
    if org and org.lower() not in base.lower():
        return f"{base} - {org}"
    return base


def _load_scrape_manifest() -> dict[str, Any]:
    """Load scraper manifest if present."""
    if not MANIFEST_PATH.exists():
        return {}
    try:
        with open(MANIFEST_PATH, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Nao foi possivel ler %s: %s", MANIFEST_PATH, exc)
        return {}


def _index_manifest_entries(scrape_manifest: dict[str, Any]) -> dict[Path, dict[str, Any]]:
    """Index manifest successes by resolved local file path."""
    index: dict[Path, dict[str, Any]] = {}
    for entry in scrape_manifest.get("sucessos", []):
        caminho = entry.get("caminho")
        if not caminho:
            continue
        try:
            index[_normalize_path(caminho)] = entry
        except OSError:
            continue
    return index


def discover_upload_items(
    data_root: Path,
    file_filter: str | None = None,
) -> list[UploadItem]:
    """Collect uploadable files under data_root using manifest metadata when available."""
    scrape_manifest = _load_scrape_manifest()
    manifest_index = _index_manifest_entries(scrape_manifest)
    items: list[UploadItem] = []

    if not data_root.exists():
        logger.error("Diretorio nao encontrado: %s", data_root)
        return items

    for path in sorted(data_root.rglob("*")):
        if not path.is_file():
            continue
        if path.name in SKIP_FILENAMES:
            continue

        rel = path.relative_to(data_root).as_posix()
        if file_filter and file_filter.replace("\\", "/") not in rel:
            continue

        entry = manifest_index.get(_normalize_path(path))
        organizacao = ""
        dataset = ""
        dataset_title = ""
        origin_url = "https://dados.sc.gov.br/dataset"
        label = None

        if entry:
            organizacao = entry.get("organizacao") or ""
            dataset = entry.get("dataset") or ""
            dataset_title = entry.get("dataset_title") or dataset
            origin_url = entry.get("url") or f"https://dados.sc.gov.br/dataset/{dataset}"
            label = entry.get("formato")
        else:
            parts = path.relative_to(data_root).parts
            if len(parts) >= 3:
                organizacao = parts[0]
                dataset = parts[1]
                dataset_title = dataset.replace("-", " ").title()
                origin_url = f"https://dados.sc.gov.br/dataset/{dataset}"

        fmt = _guess_format(path, label)
        if not fmt:
            logger.warning("Formato nao suportado, pulando: %s", rel)
            continue

        title = _build_title(organizacao, dataset_title, path.name)
        size = path.stat().st_size

        items.append(
            UploadItem(
                path=path,
                title=title,
                format=fmt,
                origin_url=origin_url,
                organizacao=organizacao,
                dataset=dataset,
                bytes=size,
            )
        )

    return items


def upload_file(
    item: UploadItem,
    session: requests.Session,
    timeout: int = 300,
) -> UploadResult:
    """Upload one file via multipart/form-data."""
    result = UploadResult(
        path=str(item.path),
        title=item.title,
        format=item.format,
    )

    mime_type = mimetypes.guess_type(item.path.name)[0] or "application/octet-stream"
    upload_name = _upload_filename(item.path, item.format)
    if upload_name == item.path.name and not item.path.suffix:
        mime_type = mimetypes.guess_type(upload_name)[0] or mime_type

    try:
        with open(item.path, "rb") as handle:
            response = session.post(
                API_UPLOAD_ENDPOINT,
                data={
                    "title": item.title,
                    "format": item.format,
                    "origin_url": item.origin_url,
                },
                files={"file": (upload_name, handle, mime_type)},
                timeout=timeout,
            )
    except requests.RequestException as exc:
        result.error = str(exc)
        return result

    if response.status_code == 401:
        result.error = "Nao autenticado (401). Faca login novamente."
        return result

    if response.status_code >= 400:
        result.error = f"HTTP {response.status_code}: {response.text[:300]}"
        return result

    try:
        payload = response.json()
    except json.JSONDecodeError:
        result.error = f"Resposta nao-JSON: {response.text[:300]}"
        return result

    result.success = True
    result.document_id = payload.get("id")
    result.status = payload.get("status")
    return result


def check_document_status(
    doc_id: str,
    session: requests.Session,
) -> dict[str, Any] | None:
    """Fetch processing status for one uploaded document."""
    try:
        response = session.get(
            f"{API_STATUS_ENDPOINT}/{doc_id}",
            timeout=60,
        )
        if response.status_code == 200:
            return response.json()
        logger.error("Status %s para %s: %s", response.status_code, doc_id, response.text[:200])
        return None
    except requests.RequestException as exc:
        logger.error("Falha ao consultar status de %s: %s", doc_id, exc)
        return None


def wait_for_documents(
    doc_ids: list[str],
    session: requests.Session,
    max_wait_minutes: int = 10,
) -> None:
    """Poll document statuses until done, error, or timeout."""
    deadline = time.time() + max_wait_minutes * 60
    pending = set(doc_ids)

    while pending and time.time() < deadline:
        still_pending: set[str] = set()
        for doc_id in pending:
            info = check_document_status(doc_id, session)
            if not info:
                still_pending.add(doc_id)
                continue
            status = info.get("status", "unknown")
            if status in ("done", "error"):
                logger.info("Documento %s: %s", doc_id, status)
                if status == "error":
                    logger.warning("  erro: %s", info.get("error_message"))
            else:
                still_pending.add(doc_id)

        pending = still_pending
        if pending:
            logger.info("Aguardando %d documento(s)...", len(pending))
            time.sleep(10)

    if pending:
        logger.warning("Timeout: %d documento(s) ainda pendentes", len(pending))


def write_upload_log(summary: UploadSummary) -> None:
    """Persist upload results beside the scraped files."""
    payload = {
        "metadata": {
            "endpoint": API_UPLOAD_ENDPOINT,
            "data_coleta": datetime.now(timezone.utc).isoformat(),
            "total": summary.total,
            "success": summary.success,
            "failed": summary.failed,
            "skipped": summary.skipped,
        },
        "results": [asdict(item) for item in summary.results],
    }
    with open(UPLOAD_LOG_PATH, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    logger.info("Log de upload salvo em %s", UPLOAD_LOG_PATH)


def upload_all(
    data_root: Path,
    password: str | None = None,
    delay: float = 2.0,
    dry_run: bool = False,
    file_filter: str | None = None,
    check_status: bool = False,
    timeout: int = 300,
    verify_ssl: bool = False,
) -> UploadSummary:
    """Upload every discovered file under data_root."""
    if not verify_ssl:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    session: requests.Session | None = None
    if not dry_run:
        resolved_password = _resolve_password(password)
        if not resolved_password:
            logger.error(
                "Senha ausente. Defina ANCORA_PASSWORD no .env ou use --password."
            )
            return UploadSummary()
        session = login_session(resolved_password, verify_ssl=verify_ssl)
        if session is None:
            return UploadSummary()

    items = discover_upload_items(data_root, file_filter=file_filter)
    summary = UploadSummary(total=len(items))

    if not items:
        logger.warning("Nenhum arquivo encontrado em %s", data_root)
        return summary

    logger.info("Arquivos para upload: %d", len(items))
    logger.info("Diretorio: %s", data_root)
    if dry_run:
        logger.info("=== DRY RUN ===")
        for idx, item in enumerate(items, start=1):
            rel = item.path.relative_to(data_root)
            logger.info(
                "[%d/%d] %s | %s | %s | %.1f MB",
                idx,
                len(items),
                rel,
                item.format,
                item.title,
                item.bytes / (1024 * 1024),
            )
        return summary

    doc_ids: list[str] = []
    assert session is not None

    for idx, item in enumerate(items, start=1):
        rel = item.path.relative_to(data_root)
        logger.info(
            "[%d/%d] Enviando %s (%.1f MB)",
            idx,
            len(items),
            rel,
            item.bytes / (1024 * 1024),
        )

        result = upload_file(
            item,
            session=session,
            timeout=timeout,
        )
        summary.results.append(result)

        if result.success:
            summary.success += 1
            logger.info(
                "  OK id=%s status=%s",
                result.document_id,
                result.status,
            )
            if result.document_id:
                doc_ids.append(result.document_id)
        else:
            summary.failed += 1
            logger.error("  FALHA: %s", result.error)
            if result.error and "401" in result.error:
                logger.error("Abortando: autenticacao invalida.")
                break

        if idx < len(items):
            time.sleep(delay)

    write_upload_log(summary)

    logger.info("=" * 60)
    logger.info("RESUMO UPLOAD")
    logger.info("Total: %d | Sucesso: %d | Falha: %d", summary.total, summary.success, summary.failed)

    if check_status and doc_ids and session:
        wait_for_documents(doc_ids, session)

    return summary


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Upload arquivos de data/dados_abertos_sc para ancora.craggroup.com"
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DATA_ROOT,
        help="Diretorio com os arquivos (default: data/dados_abertos_sc)",
    )
    parser.add_argument(
        "--file",
        help="Caminho relativo dentro de data-dir (ex: 'Secretaria.../tev/tev.xlsx')",
    )
    parser.add_argument(
        "--password",
        help="Senha da API (default: .env ANCORA_PASSWORD)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=2.0,
        help="Segundos entre uploads (default: 2.0)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Timeout por upload em segundos (default: 300)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Apenas listar arquivos sem enviar",
    )
    parser.add_argument(
        "--check-status",
        action="store_true",
        help="Aguardar processamento ETL apos upload",
    )
    parser.add_argument(
        "--verify-ssl",
        action="store_true",
        help="Validar certificado SSL (default: desabilitado)",
    )
    parser.add_argument(
        "--status",
        help="Consultar status de um documento pelo ID",
    )

    args = parser.parse_args()

    if args.status:
        resolved_password = _resolve_password(args.password)
        if not resolved_password:
            logger.error("Senha ausente para consultar status.")
            sys.exit(1)
        if not args.verify_ssl:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        session = login_session(resolved_password, verify_ssl=args.verify_ssl)
        if session is None:
            sys.exit(1)
        info = check_document_status(args.status, session)
        if info:
            print(json.dumps(info, indent=2, ensure_ascii=True))
        else:
            sys.exit(1)
        return

    summary = upload_all(
        data_root=args.data_dir,
        password=args.password,
        delay=args.delay,
        dry_run=args.dry_run,
        file_filter=args.file,
        check_status=args.check_status,
        timeout=args.timeout,
        verify_ssl=args.verify_ssl,
    )

    if not args.dry_run and summary.failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
