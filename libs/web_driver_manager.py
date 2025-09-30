from typing import Optional
from rich.console import Console
from rich.panel import Panel
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.remote.webdriver import WebDriver as RemoteWebDriver

from .config import Config

class WebDriverManager:
    def __init__(self, console: Console):
        self.console = console

    def setup(self) -> Optional[RemoteWebDriver]:
        # self.console.print(Panel("[bold cyan]Setting up WebDriver...[/bold cyan]", title="Setup", border_style="blue"))
        try:
            # Primary path: use webdriver_manager to fetch a matching ChromeDriver
            service = ChromeService(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=Config.get_chrome_options())
            driver.implicitly_wait(5)
            # self.console.print("[green]WebDriver setup complete.[/green]")
            return driver
        except Exception as setup_e:
            # Fallback path: let Selenium Manager resolve the driver automatically
            self.console.print(f"[yellow]Primary WebDriver setup failed, retrying with Selenium Manager…[/yellow] ({setup_e})")
            try:
                driver = webdriver.Chrome(options=Config.get_chrome_options())
                driver.implicitly_wait(5)
                return driver
            except Exception as fallback_e:
                self.console.print(f"[bold red]Fatal Error during WebDriver setup:[/bold red] {fallback_e}")
                return None

    def close(self, driver: RemoteWebDriver):
        self.console.print("\n[cyan]Closing WebDriver...[/cyan]")
        try:
            driver.quit()
        except Exception as quit_e:
            self.console.print(f"[yellow]Warning: Error during WebDriver quit:[/yellow] {quit_e}")
