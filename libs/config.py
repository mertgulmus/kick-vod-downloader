import os
from selenium.webdriver.chrome.options import Options

class Config:
    # Download settings
    DOWNLOAD_DIR = os.path.join(os.getcwd(), "kick_vod_downloads")

    # FFmpeg settings
    CONVERT_TO_MP3 = True
    DELETE_ORIGINAL_AFTER_CONVERT = False

    TARGET_CHANNEL = ""

    # Debug
    DEBUG_HTTP = False
    DEBUG_VERBOSE = False

    @staticmethod
    def get_chrome_options():
        chrome_options = Options()
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option("useAutomationExtension", False)
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_argument("--disable-infobars")
        chrome_options.add_argument("--log-level=3")

        prefs = {
            "download.default_directory": Config.DOWNLOAD_DIR,
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "safebrowsing.enabled": True
        }
        chrome_options.add_experimental_option("prefs", prefs)
        return chrome_options
