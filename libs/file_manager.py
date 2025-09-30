import os
import time
from selenium.webdriver.remote.webdriver import WebDriver as RemoteWebDriver
from rich import print

from .config import Config

class FileManager:
    def __init__(self):
        os.makedirs(Config.DOWNLOAD_DIR, exist_ok=True)

    def save_debug_info(self, driver_instance: RemoteWebDriver, prefix: str = "error", vod_url: str = "N/A") -> None:
        if not driver_instance:
            print("[yellow]Warning:[/yellow] Driver not available, cannot save debug info.")
            return
        try:
            timestamp = time.strftime("%Y%m%d-%H%M%S")

            # Sanitize VOD URL for filename
            if vod_url == "N/A":
                sanitized_vod_url = "general"
            elif '/' in vod_url:
                sanitized_vod_url = vod_url.split('/')[-1]
            else:
                sanitized_vod_url = vod_url.replace(':', '_').replace('/', '_')

            filename_base = f'{prefix}_{sanitized_vod_url}_{timestamp}'

            screenshot_path = os.path.join(Config.DOWNLOAD_DIR, f'{filename_base}_screenshot.png')
            page_source_path = os.path.join(Config.DOWNLOAD_DIR, f'{filename_base}_page_source.html')

            driver_instance.save_screenshot(screenshot_path)
            print(f"[cyan]Saved debug screenshot:[/cyan] {screenshot_path}")

            with open(page_source_path, 'w', encoding='utf-8') as f:
                f.write(driver_instance.page_source)
            print(f"[cyan]Saved debug page source:[/cyan] {page_source_path}")

        except Exception as debug_e:
            print(f"[bold red]Error saving debug info:[/bold red] {debug_e}")
