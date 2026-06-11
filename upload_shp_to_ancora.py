"""Upload SHP files from shp_camadas subfolders to ancora.craggroup.com mapas tab.

Usage:
    python upload_shp_to_ancora.py                    # dry run
    python upload_shp_to_ancora.py --run              # actually upload
    python upload_shp_to_ancora.py --run --folder "aerodromos"  # specific subfolder
"""

import argparse
import logging
import time
from pathlib import Path
from collections import defaultdict

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

SHP_CAMADAS_DIR = Path(__file__).parent / "data" / "shp_camadas"
SITE_URL = "https://ancora.craggroup.com/documentos"

ALLOWED_EXTENSIONS = {
    ".shp", ".shx", ".dbf", ".prj", ".cst", ".cpg", ".sbn", ".sbx",
    ".shp.xml", ".zip", ".json", ".geojson", ".csv"
}


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------

def find_upload_files(shp_dir: Path, folder_filter: str | None = None) -> list[tuple[Path, str]]:
    """Return (file_path, subfolder_name) for all uploadable files."""
    files = []
    for subfolder in sorted(shp_dir.iterdir()):
        if not subfolder.is_dir():
            continue
        if folder_filter and folder_filter.lower() not in subfolder.name.lower():
            continue
        for fp in sorted(subfolder.iterdir()):
            if fp.is_file() and (
                fp.suffix.lower() in ALLOWED_EXTENSIONS or fp.name.endswith(".zip")
            ):
                files.append((fp, subfolder.name))
    return files


# ---------------------------------------------------------------------------
# Browser setup
# ---------------------------------------------------------------------------

def build_driver(headless: bool = False) -> webdriver.Chrome:
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1280,900")
    opts.add_argument("--ignore-certificate-errors")
    opts.add_argument("--ignore-ssl-errors")
    opts.add_experimental_option("prefs", {"download.prompt_for_download": False})
    driver = webdriver.Chrome(options=opts)
    driver.implicitly_wait(10)
    return driver


def _unhide(elem) -> None:
    """Remove display/visibility constraints so Selenium can interact with the element."""
    elem.parent.execute_script(
        "Object.assign(arguments[0].style, {"
        "  display: 'block', opacity: '1', visibility: 'visible',"
        "  pointerEvents: 'auto', position: 'fixed',"
        "  top: '0', left: '0', width: '1px', height: '1px', zIndex: '-1'"
        "});",
        elem,
    )


# ---------------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------------

def open_mapas_tab(driver: webdriver.Chrome) -> None:
    wait = WebDriverWait(driver, 15)
    tabs = wait.until(EC.presence_of_all_elements_located(
        (By.CSS_SELECTOR, "[role='tab'], button, a")
    ))
    mapas_tab = next(
        (e for e in tabs if "mapas" in (e.text or "").strip().lower()), None
    )
    if mapas_tab is None:
        try:
            mapas_tab = driver.find_element(
                By.XPATH,
                "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', "
                "'abcdefghijklmnopqrstuvwxyz'), 'mapas')] | "
                "//a[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', "
                "'abcdefghijklmnopqrstuvwxyz'), 'mapas')]"
            )
        except Exception:
            pass
    if mapas_tab:
        logger.info(f"Clicking Mapas tab: {mapas_tab.text.strip()!r}")
        mapas_tab.click()
        time.sleep(2)
    else:
        logger.warning("Could not find 'Mapas' tab")


def find_file_input(driver: webdriver.Chrome):
    """Find and unhide the hidden file input inside the dropzone."""
    wait = WebDriverWait(driver, 10)
    for by, sel in [
        (By.CSS_SELECTOR, "input[type='file']"),
        (By.XPATH, "//input[@type='file']"),
    ]:
        try:
            elem = wait.until(EC.presence_of_element_located((by, sel)))
            _unhide(elem)
            logger.info("Found file input")
            return elem
        except Exception:
            continue
    return None


# ---------------------------------------------------------------------------
# Upload helpers
# ---------------------------------------------------------------------------

def wait_upload_done(driver: webdriver.Chrome, timeout: int = 90) -> None:
    """Wait for loading/uploading indicators to disappear."""
    wait = WebDriverWait(driver, timeout)
    for sel in [
        (By.CSS_SELECTOR, "[aria-busy='true']"),
        (By.XPATH, "//*[contains(@class,'uploading') or contains(@class,'loading')]"),
    ]:
        try:
            wait.until(EC.invisibility_of_element_located(sel))
            return
        except Exception:
            pass
    # Fallback: give it a moment
    time.sleep(3)


# ---------------------------------------------------------------------------
# Edit modal
# ---------------------------------------------------------------------------

def find_editar_button_for_row(driver: webdriver.Chrome, folder_files: list[Path]) -> bool:
    """Click the Editar button on the row that matches the just-uploaded layer.

    We identify the row by matching the .shp filename that was uploaded
    (the ancora UI shows the filename in the row).
    """
    time.sleep(2)  # Give the new row time to render

    # The primary .shp filename (without path) is shown in the row
    shp_names = [f.name for f in folder_files if f.suffix.lower() == ".shp"]
    if not shp_names:
        shp_names = [f.name for f in folder_files]

    rows = driver.find_elements(By.CSS_SELECTOR, "table tbody tr")
    logger.info(f"  Scanning {len(rows)} rows for edit button")

    for row in rows:
        try:
            row_html = row.get_attribute("innerHTML")
            # Check if any of our uploaded filenames appears in this row
            if any(shp_name in row_html for shp_name in shp_names):
                editar_btn = row.find_element(
                    By.XPATH, ".//button[contains(text(), 'Editar')]"
                )
                editar_btn.click()
                logger.info(f"  Clicked Editar (matched on: {shp_names[0]})")
                return True
        except Exception:
            continue

    # Fallback: click the first Editar button (most recent/uppermost layer)
    try:
        editar_btns = driver.find_elements(
            By.XPATH, "//button[contains(text(), 'Editar')]"
        )
        if editar_btns:
            editar_btns[0].click()
            logger.info("  Clicked first Editar button (fallback)")
            return True
    except Exception:
        pass

    return False


def fill_edit_name_field(driver: webdriver.Chrome, folder_name: str) -> bool:
    """Fill the layer name field in the edit modal with folder_name.

    The field is under the 'Camada / tag' column header.
    We look for a visible text input in the modal.
    """
    time.sleep(1.5)

    # Try selectors for the name/tag field in the modal
    name_selectors = [
        (By.CSS_SELECTOR, "input[name*='nome' i]"),
        (By.CSS_SELECTOR, "input[name*='name' i]"),
        (By.CSS_SELECTOR, "input[name*='camada' i]"),
        (By.CSS_SELECTOR, "input[name*='tag' i]"),
        (By.CSS_SELECTOR, "input[name*='layer' i]"),
        (By.CSS_SELECTOR, "input[type='text']"),
    ]

    for by, sel in name_selectors:
        try:
            inputs = driver.find_elements(by, sel)
            for inp in inputs:
                _unhide(inp)
                if inp.is_displayed() and inp.is_enabled():
                    inp.clear()
                    inp.send_keys(folder_name)
                    logger.info(f"  Filled name: {folder_name!r}")
                    time.sleep(0.5)
                    # Always click save after filling
                    _click_save_button(driver)
                    return True
        except Exception:
            continue

    logger.warning("  Could not find name input in edit modal")
    return False


def _click_save_button(driver: webdriver.Chrome) -> None:
    """Try to click Save/Confirm/Atualizar in the modal."""
    save_labels = ["Salvar", "Confirmar", "Atualizar", "Aplicar", "Ok", "OK"]
    for label in save_labels:
        try:
            btns = driver.find_elements(
                By.XPATH, f"//button[contains(text(), '{label}')]"
            )
            for btn in btns:
                if btn.is_displayed() and btn.is_enabled():
                    btn.click()
                    logger.info(f"  Clicked: {label}")
                    time.sleep(1)
                    return
        except Exception:
            continue


# ---------------------------------------------------------------------------
# Main upload logic
# ---------------------------------------------------------------------------

def upload_folder(driver: webdriver.Chrome, folder_name: str,
                  folder_files: list[Path], file_input) -> bool:
    """Upload all files from one subfolder, then set the layer name."""
    try:
        # Send all files at once
        paths_str = "\n".join(str(f.resolve()) for f in folder_files)
        file_input.send_keys(paths_str)
        logger.info(f"  Sent {len(folder_files)} files")
        time.sleep(2)

        # Wait for processing to finish
        wait_upload_done(driver)

        # Click Editar on the newly added row
        if find_editar_button_for_row(driver, folder_files):
            fill_edit_name_field(driver, folder_name)

        logger.info(f"  ✓ Done: {folder_name}")
        return True

    except Exception as e:
        logger.error(f"  ✗ Failed '{folder_name}': {e}")
        return False


def upload_all(driver: webdriver.Chrome,
               files: list[tuple[Path, str]],
               dry_run: bool = False) -> tuple[int, int]:
    """Upload all subfolders one by one."""
    success = 0
    failed = 0

    file_input = find_file_input(driver)
    if file_input is None:
        logger.error("Could not find file input element!")
        return 0, len(files)

    by_folder: dict[str, list[Path]] = defaultdict(list)
    for fp, folder in files:
        by_folder[folder].append(fp)

    total = len(by_folder)
    logger.info(f"Uploading {len(files)} files across {total} subfolders...")

    for idx, (folder_name, folder_files) in enumerate(by_folder.items(), start=1):
        logger.info(f"[{idx}/{total}] {folder_name} ({len(folder_files)} files)")

        if dry_run:
            logger.info(f"  [DRY] layer name would be: {folder_name}")
            success += len(folder_files)
            continue

        # No need to click "Selecionar arquivos" — send_keys works directly on the hidden input

        ok = upload_folder(driver, folder_name, folder_files, file_input)
        if ok:
            success += len(folder_files)
        else:
            failed += len(folder_files)

        # Re-unhide input for the next folder
        _unhide(file_input)
        time.sleep(2)

    return success, failed


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Upload SHP files from shp_camadas to ancora.craggroup.com mapas tab"
    )
    parser.add_argument("--run", action="store_true",
                        help="Actually upload (default is dry-run)")
    parser.add_argument("--headless", action="store_true",
                        help="Run Chrome in headless mode")
    parser.add_argument("--folder", "-f", type=str, default=None,
                        help="Only subfolders matching this string")
    parser.add_argument("--shp-dir", type=Path, default=SHP_CAMADAS_DIR)

    args = parser.parse_args()
    dry_run = not args.run

    if not args.shp_dir.exists():
        logger.error(f"Directory not found: {args.shp_dir}")
        return

    files = find_upload_files(args.shp_dir, args.folder)
    if not files:
        logger.warning("No files found!")
        return

    by_folder: dict[str, int] = defaultdict(int)
    for f, folder in files:
        by_folder[folder] += 1

    logger.info(f"Found {len(files)} files across {len(by_folder)} subfolders:")
    for folder, count in sorted(by_folder.items()):
        logger.info(f"  [{count:3d} files] {folder}")

    print()

    if dry_run:
        logger.info("=== DRY RUN — run with --run to actually upload ===")
        return

    logger.info("=== Starting upload ===")
    driver = build_driver(headless=args.headless)

    try:
        driver.get(SITE_URL)
        time.sleep(3)
        open_mapas_tab(driver)
        time.sleep(2)

        success, failed = upload_all(driver, files, dry_run=False)

        print()
        logger.info("=" * 60)
        logger.info("UPLOAD SUMMARY")
        logger.info("=" * 60)
        logger.info(f"Total folders: {len(by_folder)}")
        logger.info(f"Total files:   {len(files)}")
        logger.info(f"Successful:    {success}")
        logger.info(f"Failed:        {failed}")

    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
    finally:
        input("Press Enter to close the browser...")
        driver.quit()


if __name__ == "__main__":
    main()