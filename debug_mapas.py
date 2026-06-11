"""Investigate the ancora mapas tab HTML structure."""
import time
from pathlib import Path
from upload_shp_to_ancora import build_chrome_driver, click_mapas_tab, SITE_URL

driver = build_chrome_driver(headless=False)
try:
    driver.get(SITE_URL)
    time.sleep(3)
    click_mapas_tab(driver)
    time.sleep(3)

    # Print page source snippet
    html = driver.page_source
    print(f"Page title: {driver.title}")
    print(f"HTML length: {len(html)}")

    # Save full HTML for inspection
    Path("debug_mapas.html").write_text(html, encoding="utf-8")
    print("Saved debug_mapas.html")

    # Look for all inputs, dropzones, name fields
    from selenium.webdriver.common.by import By
    inputs = driver.find_elements(By.CSS_SELECTOR, "input, textarea, [contenteditable]")
    print(f"\nFound {len(inputs)} input/textarea elements:")
    for inp in inputs:
        tag = inp.tag_name
        type_ = inp.get_attribute("type") or ""
        id_ = inp.get_attribute("id") or ""
        name_ = inp.get_attribute("name") or ""
        placeholder = inp.get_attribute("placeholder") or ""
        aria = inp.get_attribute("aria-label") or ""
        cls = inp.get_attribute("class") or ""
        displayed = inp.is_displayed()
        rect = inp.rect
        print(f"  <{tag} type={type_} id={id_!r} name={name_!r} placeholder={placeholder!r} aria-label={aria!r} class={cls!r} displayed={displayed} rect={rect}>")

finally:
    input("Press Enter to close...")
    driver.quit()