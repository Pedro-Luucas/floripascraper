"""Geoportal PMF SHP scraper module.

Discovers and downloads every SHP (ESRI Shapefile) layer exposed by the
Florianópolis municipal geoportal's "Camadas em SIG do mapa" page.

Source page (React SPA, links built client-side from JSON):
    https://geo.pmf.sc.gov.br/downloads/camadas-em-sig-do-mapa

Underlying API used (reverse-engineered from
    https://geofloripa.pmf.sc.gov.br/static/js/main.<hash>.chunk.js):

    GET https://geofloripa.pmf.sc.gov.br/geowise/mapa/get_map_by_target
            ?target=geoportal
    Headers:
        X-User-Login: geoportal
        X-User-Token: 3969c9daaccf836c6874c5de4f7b182a

The JSON response contains a `content` array of layer groups. Each group
of type WMS or WFS has a `source` (geoserver base URL), a `workspace`,
and a `layers` array. For every layer the React app renders two download
links:

    SHP:       {source}/ows?service=WFS&version=1.0.0
                       &request=GetFeature&typeName={workspace}:{layer}
                       &outputFormat=SHAPE-ZIP
    METADADOS: {source}/rest/workspaces/{workspace}/featuretypes/{layer}.xml

This scraper targets the SHP links only, mirrors them into
``data/shp_camadas/`` and writes a JSON manifest to
``data/geoportal_camadas_shp.json``.
"""

import json
import logging
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from .base_scraper import BaseScraper
from utils.retry_handler import FailedUrlTracker

logger = logging.getLogger(__name__)

# Output paths
OUTPUT_DIR = Path(__file__).parent.parent / "data"
SHP_DOWNLOAD_DIR = OUTPUT_DIR / "shp_camadas"
MANIFEST_FILENAME = "geoportal_camadas_shp.json"

# API endpoint that lists every downloadable SHP layer
MAP_API_URL = (
    "https://geofloripa.pmf.sc.gov.br/geowise/mapa/get_map_by_target?target=geoportal"
)
# Public landing page (kept for traceability in the manifest)
LANDING_PAGE_URL = "https://geo.pmf.sc.gov.br/downloads/camadas-em-sig-do-mapa"

# Static auth headers used by the React app. They are not secrets — they
# are embedded in the public JS bundle shipped by the geoportal itself.
API_HEADERS: dict[str, str] = {
    "X-User-Login": "geoportal",
    "X-User-Token": "3969c9daaccf836c6874c5de4f7b182a",
}

# Filename safety
_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass
class ShpLayer:
    """One WFS layer exposed as a SHP download."""

    name: str
    layer: str
    workspace: str
    source: str
    group: str
    shp_url: str
    metadata_url: str
    filename: str
    bytes: int | None = None
    downloaded: bool = False
    error: str | None = None
    downloaded_at: str | None = None


@dataclass
class ShpDownloadSummary:
    """Aggregate result returned by ``scrape()``."""

    total: int = 0
    downloaded: int = 0
    failed: int = 0
    skipped: int = 0
    bytes_total: int = 0
    output_dir: str = ""
    manifest_path: str = ""
    errors: list[str] = field(default_factory=list)


class GeoportalShpScraper(BaseScraper):
    """Scraper for the SHP layers at ``geo.pmf.sc.gov.br``.

    Inherits HTTP/retry/rate-limit plumbing from ``BaseScraper`` and
    keeps the same JSON-on-disk contract as the other scrapers in the
    project.
    """

    def __init__(self, rate_limit_delay: float = 0.5) -> None:
        """Initialize the scraper.

        Args:
            rate_limit_delay: Minimum delay between HTTP requests in seconds.
                              Geoportal downloads are heavy; keep this short
                              so the manifest fetch is snappy, but generous
                              enough to stay polite across 100+ downloads.
        """
        super().__init__(
            name="geoportal_shp",
            base_url="https://geofloripa.pmf.sc.gov.br",
            rate_limit_delay=rate_limit_delay,
        )
        self.output_dir = OUTPUT_DIR
        self.download_dir = SHP_DOWNLOAD_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.download_dir.mkdir(parents=True, exist_ok=True)
        logger.info(
            f"GeoportalShpScraper initialized; SHP files -> {self.download_dir}"
        )

    # ------------------------------------------------------------------ #
    # Layer discovery                                                     #
    # ------------------------------------------------------------------ #

    def _fetch_layer_index(self) -> list[dict[str, Any]]:
        """Fetch the map configuration JSON describing every layer.

        Returns:
            The ``content`` array from the geowise API. Each element is a
            layer group with a ``layers`` sub-array. Empty list on error.
        """
        logger.info(f"Fetching layer index: {MAP_API_URL}")

        # Use requests directly so we can add the API-specific headers
        # (BaseScraper._make_request would overwrite them with browser headers).
        import requests

        try:
            response = requests.get(
                MAP_API_URL,
                headers={**self._get_headers(), **API_HEADERS},
                timeout=60,
            )
            response.raise_for_status()
        except requests.RequestException as e:
            logger.error(f"Failed to fetch layer index: {e}")
            return []

        try:
            payload = response.json()
        except json.JSONDecodeError as e:
            logger.error(f"Layer index returned non-JSON: {e}")
            return []

        content = payload.get("content", []) if isinstance(payload, dict) else []
        logger.info(f"Layer index returned {len(content)} group(s)")
        return content

    @staticmethod
    def _safe_filename(text: str) -> str:
        """Sanitize a string for use as a filename on every major OS."""
        cleaned = _SAFE_RE.sub("_", text.strip())
        cleaned = cleaned.strip("._-") or "layer"
        return cleaned[:160]

    def _build_layer_records(self, content: list[dict[str, Any]]) -> list[ShpLayer]:
        """Turn the raw content array into one ``ShpLayer`` per WFS featuretype.

        Mirrors the React component's filter: skip groups that are not
        WMS/WFS and skip layer entries without a ``layer`` name (these are
        non-downloadable sublayers in the React app).
        """
        records: list[ShpLayer] = []
        seen_urls: set[str] = set()

        for group in content:
            gtype = (group.get("type") or "").upper()
            if gtype not in ("WMS", "WFS"):
                continue

            source = (group.get("source") or "").rstrip("/")
            workspace = group.get("workspace") or ""
            group_name = group.get("name") or ""
            if not source or not workspace:
                logger.warning(
                    f"Group '{group_name}' missing source/workspace; skipping"
                )
                continue

            for layer in group.get("layers") or []:
                layer_name = layer.get("layer")
                if not layer_name:
                    continue

                type_name = f"{workspace}:{layer_name}"
                shp_url = (
                    f"{source}/ows?service=WFS&version=1.0.0"
                    f"&request=GetFeature&typeName={type_name}"
                    f"&outputFormat=SHAPE-ZIP"
                )
                metadata_url = (
                    f"{source}/rest/workspaces/{workspace}"
                    f"/featuretypes/{layer_name}.xml"
                )
                if shp_url in seen_urls:
                    continue
                seen_urls.add(shp_url)

                display = layer.get("name") or layer_name
                full_name = f"{group_name} - {display}" if group_name else display
                filename = self._safe_filename(f"{workspace}__{layer_name}.zip")

                records.append(
                    ShpLayer(
                        name=full_name,
                        layer=layer_name,
                        workspace=workspace,
                        source=source,
                        group=group_name,
                        shp_url=shp_url,
                        metadata_url=metadata_url,
                        filename=filename,
                    )
                )

        logger.info(f"Discovered {len(records)} SHP layer(s) to download")
        return records

    # ------------------------------------------------------------------ #
    # Download                                                            #
    # ------------------------------------------------------------------ #

    def _download_one(
        self, record: ShpLayer, tracker: FailedUrlTracker
    ) -> bool:
        """Download a single SHP zip into the target folder.

        Args:
            record: The layer metadata; mutated in place with size/timestamp.
            tracker: Tracker used to record failures for later retry.

        Returns:
            True if the file was written successfully, False otherwise.
        """
        import requests

        target = self.download_dir / record.filename
        if target.exists() and target.stat().st_size > 0:
            logger.debug(f"Already on disk, skipping: {target.name}")
            record.downloaded = True
            record.bytes = target.stat().st_size
            record.downloaded_at = datetime.now(timezone.utc).isoformat()
            return True

        self._apply_rate_limit()

        try:
            with requests.get(
                record.shp_url,
                headers={**self._get_headers(), **API_HEADERS},
                stream=True,
                timeout=120,
            ) as resp:
                resp.raise_for_status()
                with open(target, "wb") as fh:
                    for chunk in resp.iter_content(chunk_size=64 * 1024):
                        if chunk:
                            fh.write(chunk)
        except requests.RequestException as e:
            record.error = str(e)
            record.downloaded = False
            logger.error(f"Failed to download {record.shp_url}: {e}")
            tracker.add_failed_url(record.shp_url, self.name, str(e))
            if target.exists() and target.stat().st_size == 0:
                target.unlink(missing_ok=True)
            return False

        record.bytes = target.stat().st_size
        record.downloaded = True
        record.downloaded_at = datetime.now(timezone.utc).isoformat()
        logger.info(
            f"Downloaded {record.filename} ({record.bytes / 1024:.1f} KB)"
        )
        return True

    def _download_all(
        self, records: list[ShpLayer]
    ) -> tuple[int, int, int, int]:
        """Download every record, returning (downloaded, failed, skipped, bytes)."""
        tracker = FailedUrlTracker()
        downloaded = failed = skipped = 0
        bytes_total = 0

        for idx, record in enumerate(records, start=1):
            logger.info(
                f"[{idx}/{len(records)}] {record.workspace}:{record.layer}"
            )
            already = (
                self.download_dir / record.filename
            ).exists() and (self.download_dir / record.filename).stat().st_size > 0
            ok = self._download_one(record, tracker)
            if ok and already:
                skipped += 1
            if ok:
                downloaded += 1
                if record.bytes:
                    bytes_total += record.bytes
            else:
                failed += 1

        return downloaded, failed, skipped, bytes_total

    # ------------------------------------------------------------------ #
    # Manifest                                                            #
    # ------------------------------------------------------------------ #

    def _write_manifest(
        self,
        records: list[ShpLayer],
        summary: ShpDownloadSummary,
    ) -> Path:
        """Persist a JSON manifest with everything we discovered + downloaded."""
        manifest_path = self.output_dir / MANIFEST_FILENAME

        payload = {
            "metadata": {
                "fonte": self.name,
                "url_origem": LANDING_PAGE_URL,
                "api": MAP_API_URL,
                "data_coleta": datetime.now(timezone.utc).isoformat(),
                "count": len(records),
                "downloaded": summary.downloaded,
                "failed": summary.failed,
                "skipped": summary.skipped,
                "bytes_total": summary.bytes_total,
                "output_dir": str(self.download_dir),
            },
            "camadas": [asdict(r) for r in records],
        }

        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        logger.info(f"Manifest written: {manifest_path}")
        return manifest_path

    # ------------------------------------------------------------------ #
    # Public entry point                                                  #
    # ------------------------------------------------------------------ #

    def scrape(self) -> dict[str, Any]:
        """Discover, download, and manifest every SHP link on the page.

        Returns:
            Dict with counts, paths, and the per-layer manifest data —
            the same shape ``run_all.py`` expects from other scrapers.
        """
        start = time.time()
        summary = ShpDownloadSummary(output_dir=str(self.download_dir))

        content = self._fetch_layer_index()
        if not content:
            summary.errors.append("Layer index empty or unreachable")
            return asdict(summary)

        records = self._build_layer_records(content)
        summary.total = len(records)
        if not records:
            summary.errors.append("No SHP layers discovered")
            return asdict(summary)

        downloaded, failed, skipped, bytes_total = self._download_all(records)
        summary.downloaded = downloaded
        summary.failed = failed
        summary.skipped = skipped
        summary.bytes_total = bytes_total

        manifest_path = self._write_manifest(records, summary)
        summary.manifest_path = str(manifest_path)

        elapsed = time.time() - start
        logger.info(
            f"GeoportalShp scrape done in {elapsed:.1f}s: "
            f"{downloaded} downloaded ({skipped} cached), {failed} failed, "
            f"{bytes_total / (1024 * 1024):.1f} MB total"
        )
        return asdict(summary)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    scraper = GeoportalShpScraper()
    print(json.dumps(scraper.scrape(), indent=2, ensure_ascii=False))
