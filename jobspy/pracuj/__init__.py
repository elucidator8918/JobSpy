from __future__ import annotations

import random
import asyncio
from typing import List, Optional
from bs4 import BeautifulSoup

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

from jobspy.model import (
    Scraper,
    ScraperInput,
    Site,
    JobPost,
    JobResponse,
    Location,
    Country,
)
from jobspy.util import create_logger

log = create_logger("PracujPL")


class PracujPLScraper(Scraper):
    base_url = "https://www.pracuj.pl"
    delay = 2
    band_delay = 3
    country = "Poland"

    def __init__(self, proxies: list[str] | str | None = None, ca_cert: str | None = None):
        super().__init__(Site.PRACUJPL, proxies=proxies, ca_cert=ca_cert)
        self.scraper_input = None

    def scrape(self, scraper_input: ScraperInput) -> JobResponse:
        self.scraper_input = scraper_input
        return self._selenium_scrape()

    def _selenium_scrape(self) -> JobResponse:
        job_list: list[JobPost] = []
        results_wanted = self.scraper_input.results_wanted or 10

        # Set up Chrome options
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        
        # Initialize driver
        driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install()),
            options=chrome_options
        )
        
        try:
            # Format search query for URL
            formatted_query = self.scraper_input.search_term.replace(" ", "%20")
            url = f"{self.base_url}/offers/search?keywords={formatted_query}"
            
            log.info(f"Fetching initial PracujPL jobs from: {url}")
            driver.get(url)
            
            # Wait for page to load and close any modals
            self._close_modal(driver)
            
            # Get max page number
            max_page_num = self._get_max_page_number(driver.page_source)
            log.info(f"Found {max_page_num} pages of results")
            
            current_page_num = 1
            while len(job_list) < results_wanted and current_page_num <= max_page_num:
                log.info(f"Processing page {current_page_num} of {max_page_num}")
                
                # Parse the current page
                jobs = self._parse_jobs_from_page(driver.page_source)
                if not jobs:
                    break
                
                job_list.extend(jobs[: results_wanted - len(job_list)])
                
                # Move to next page if needed
                if current_page_num < max_page_num and len(job_list) < results_wanted:
                    current_page_num += 1
                    next_page_url = f"{url}&pn={current_page_num}"
                    log.info(f"Navigating to page {current_page_num}: {next_page_url}")
                    driver.get(next_page_url)
                    self._close_modal(driver)
                    import time
                    time.sleep(random.uniform(self.delay, self.delay + self.band_delay))
                else:
                    break
                    
        except Exception as e:
            log.error(f"Error during scraping: {str(e)}")
        finally:
            driver.quit()
        
        log.info(f"Collected {len(job_list)} jobs from PracujPL")
        return JobResponse(jobs=job_list)
    
    def _close_modal(self, driver) -> None:
        """Close any modal that may appear on the page."""
        try:
            modal = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.CLASS_NAME, "core_ig18o8w"))
            )
            modal.click()
            log.debug("Modal closed successfully")
        except Exception as e:
            log.debug(f"No modal found or error closing modal: {str(e)}")
    
    def _get_max_page_number(self, page_content: str) -> int:
        """Get the maximum page number from pagination."""
        try:
            soup = BeautifulSoup(page_content, "html.parser")
            max_page_element = soup.find(
                "span", {"data-test": "top-pagination-max-page-number"}
            )
            if max_page_element:
                return int(max_page_element.text)
        except Exception as e:
            log.error(f"Error determining max page number: {str(e)}")
        return 1
    
    def _parse_jobs_from_page(self, page_content: str) -> List[JobPost] | None:
        """Parse job listings from the page content."""
        try:
            soup = BeautifulSoup(page_content, "html.parser")
            job_cards = soup.find_all("div", class_="tiles_c1k2agp8")
            
            if not job_cards:
                log.debug("No job cards found on page")
                return None
            
            log.debug(f"Found {len(job_cards)} job cards on page")
            job_posts = []
            
            for card in job_cards:
                try:
                    job_post = self._extract_job_info(card)
                    if job_post:
                        job_posts.append(job_post)
                except Exception as e:
                    log.error(f"Error extracting job info: {str(e)}")
            
            return job_posts
        except Exception as e:
            log.error(f"Error parsing jobs from page: {str(e)}")
            return None
    
    def _extract_job_info(self, card) -> JobPost | None:
        """Extract job information from a job card."""
        try:
            # Extract job title
            title_el = card.find("h2")
            title = title_el.text if title_el else None
            
            # Extract job URL
            url_el = card.find("a", class_="core_n194fgoq")
            href = url_el.get("href") if url_el else None
            job_url = self._remove_search_id(href) if href else None
            
            # Full URL
            if job_url and not job_url.startswith("http"):
                job_url = f"{self.base_url}{job_url}"
            
            # Extract company name
            company_el = card.find("h4")
            company = company_el.text if company_el else None
            
            # Extract location
            location_el = card.find("div", class_="tiles_gsg0tg3")
            location = location_el.text if location_el else None
            
            # Create unique job ID
            job_id = f"pracujpl-{abs(hash(job_url))}" if job_url else None
            
            # Create location object
            location_obj = Location(city=location, country=Country.from_string(self.country))
            
            return JobPost(
                id=job_id,
                title=title,
                company_name=company,
                location=location_obj,
                job_url=job_url,
            )
        except Exception as e:
            log.error(f"Error extracting job details: {str(e)}")
            return None
    
    @staticmethod
    def _remove_search_id(url: str) -> str:
        """Remove search ID parameters from job URLs."""
        if not url:
            return ""
        url_parts = url.split("?")
        return url_parts[0]