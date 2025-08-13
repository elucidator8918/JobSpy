from __future__ import annotations

import random
import asyncio

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

log = create_logger("Upwork")


class UpworkScraper(Scraper):
    base_url = "https://www.upwork.com"
    delay = 2
    band_delay = 3

    def __init__(self, proxies: list[str] | str | None = None, ca_cert: str | None = None, user_agent: str | None = None):
        super().__init__(Site.UPWORK, proxies=proxies, ca_cert=ca_cert)
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
            page = await context.new_page()

            query = self.scraper_input.search_term.replace(" ", "%20")
            search_url = f"{self.base_url}/search/jobs/?q={query}"
            await page.goto(search_url, wait_until="domcontentloaded")

            try:
                await page.wait_for_selector("section.up-card-section", timeout=10000)
            except Exception as e:
                log.error(f"Upwork: Timeout waiting for job cards - {e}")
                await browser.close()
                return JobResponse(jobs=[])

            previous_count = 0
            scroll_attempts = 0
            max_scroll_attempts = 10

            while len(job_list) < results_wanted and scroll_attempts < max_scroll_attempts:
                await page.evaluate("window.scrollBy(0, document.body.scrollHeight)")
                await asyncio.sleep(random.uniform(self.delay, self.delay + self.band_delay))

                job_cards = await page.query_selector_all("section.up-card-section")
                new_count = len(job_cards)

                if new_count == previous_count:
                    scroll_attempts += 1
                else:
                    scroll_attempts = 0
                    previous_count = new_count

                for card in job_cards[len(job_list):]:  # Parse only new cards
                    if len(job_list) >= results_wanted:
                        break
                    try:
                        job_post = await self._extract_job_info(card)
                        if job_post:
                            job_list.append(job_post)
                    except Exception as e:
                        log.error(f"Upwork: Error extracting job info: {e}")

            await browser.close()
            return JobResponse(jobs=job_list[:results_wanted])

    async def _extract_job_info(self, card) -> JobPost | None:
        try:
            title_element = await card.query_selector("h4 a")
            job_title = await title_element.inner_text() if title_element else None
            job_url = await title_element.get_attribute("href") if title_element else None
            if job_url and not job_url.startswith("http"):
                job_url = f"{self.base_url}{job_url}"

            company_element = await card.query_selector("span.up-line-clamp-v2")
            company_name = await company_element.inner_text() if company_element else None

            location = "Remote"  # Upwork jobs are typically remote

            job_id = f"upwork-{abs(hash(job_url))}"
            location_obj = Location(city=location, country=Country.from_string(self.country))

            return JobPost(
                id=job_id,
                title=job_title,
                company_name=company_name,
                location=location_obj,
                job_url=job_url,
            )
        except Exception as e:
            log.error(f"Upwork: Error extracting job details: {e}")
            return None
