from __future__ import annotations

import random
import asyncio
from typing import List

from playwright.async_api import async_playwright, Page

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

log = create_logger("ProfessionHU")


class ProfessionHUScraper(Scraper):
    base_url = "https://www.profession.hu"
    delay = 2
    band_delay = 3

    def __init__(self, proxies: list[str] | str | None = None, ca_cert: str | None = None):
        super().__init__(Site.PROFESSIONHU, proxies=proxies, ca_cert=ca_cert)
        self.scraper_input = None
        self.country = "Hungary"

    def scrape(self, scraper_input: ScraperInput) -> JobResponse:
        self.scraper_input = scraper_input
        return asyncio.run(self._async_scrape())

    async def _async_scrape(self) -> JobResponse:
        job_list: list[JobPost] = []
        results_wanted = self.scraper_input.results_wanted or 10

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()
            
            # Configure proxy if available
            if self.proxies:
                # Implementation for proxy would go here
                pass
                
            page = await context.new_page()
            
            current_page_num = 1
            
            while len(job_list) < results_wanted:
                log.info(f"Fetching Profession.hu jobs page {current_page_num}")
                
                jobs = await self._fetch_jobs(page, self.scraper_input.search_term, current_page_num)
                if not jobs:
                    break
                
                for job in jobs:
                    job_list.append(job)
                    if len(job_list) >= results_wanted:
                        break
                
                current_page_num += 1
                # Add randomized delay between requests
                await asyncio.sleep(random.uniform(self.delay, self.delay + self.band_delay))
            
            await browser.close()
        
        return JobResponse(jobs=job_list[:results_wanted])

    async def _fetch_jobs(self, page: Page, query: str, page_num: int) -> List[JobPost] | None:
        try:
            # Format query for profession.hu search URL
            formatted_query = query.replace(" ", "-")
            url = f"{self.base_url}/allasok/{formatted_query}/{page_num}/"
            
            await page.goto(url, wait_until="domcontentloaded")
            
            # Wait for job listings to load
            await page.wait_for_selector(".job-card", timeout=10000)
            
            # Extract job data from the page
            job_posts = []
            job_cards = await page.query_selector_all(".job-card")
            
            if not job_cards:
                log.debug(f"No job cards found on page {page_num}")
                return None
            
            log.debug(f"Found {len(job_cards)} job cards on page {page_num}")
            
            for card in job_cards:
                try:
                    job_post = await self._extract_job_info(card, page)
                    if job_post:
                        job_posts.append(job_post)
                except Exception as e:
                    log.error(f"ProfessionHU: Error extracting job info: {str(e)}")
            
            return job_posts
        
        except Exception as e:
            log.error(f"ProfessionHU: Error fetching jobs - {str(e)}")
            return None

    async def _extract_job_info(self, card, page: Page) -> JobPost | None:
        try:
            # Extract job title and URL
            title_element = await card.query_selector(".job-card__title a")
            if not title_element:
                return None
            
            job_title = await title_element.inner_text()
            relative_url = await title_element.get_attribute("href")
            job_url = f"{self.base_url}{relative_url}" if relative_url else None
            
            if not job_url:
                return None
            
            # Extract company name
            company_element = await card.query_selector(".job-card__company-name")
            company_name = await company_element.inner_text() if company_element else None
            
            # Extract location
            location_element = await card.query_selector(".job-card__company-address span")
            location = await location_element.inner_text() if location_element else None
            
            # Create unique job ID
            job_id = f"professionhu-{abs(hash(job_url))}"
            
            # Create location object
            location_obj = Location(city=location, country=Country.from_string(self.country))
            
            return JobPost(
                id=job_id,
                title=job_title,
                company_name=company_name,
                location=location_obj,
                job_url=job_url,
            )
        
        except Exception as e:
            log.error(f"Error extracting job details: {str(e)}")
            return None