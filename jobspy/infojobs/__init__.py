from __future__ import annotations

import random
import asyncio
from typing import List

from playwright.async_api import async_playwright, Page
from urllib.parse import urlencode

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

log = create_logger("InfoJobs")


class InfoJobsScraper(Scraper):
    base_url = "https://www.infojobs.net"
    delay = 2
    band_delay = 3
    country = "Spain"

    def __init__(self, proxies: list[str] | str | None = None, ca_cert: str | None = None):
        super().__init__(Site.INFOJOBS, proxies=proxies, ca_cert=ca_cert)
        self.scraper_input = None

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

            current_page_num = 1
            while len(job_list) < results_wanted:
                log.info(f"Fetching InfoJobs page {current_page_num}")
                jobs = await self._fetch_jobs(page, self.scraper_input.search_term, current_page_num)
                if not jobs:
                    break

                job_list.extend(jobs[: results_wanted - len(job_list)])
                current_page_num += 1
                await asyncio.sleep(random.uniform(self.delay, self.delay + self.band_delay))

            await browser.close()

        return JobResponse(jobs=job_list)

    async def _fetch_jobs(self, page: Page, query: str, page_num: int) -> List[JobPost] | None:
        try:
            query_params = {
                "keyword": query,
                "normalizedJobTitleIds": "",  # Can be added if you want to filter by title ID
                "segmentId": "",
                "page": page_num,
                "sortBy": "RELEVANCE",
                "onlyForeignCountry": "false",
                "sinceDate": "ANY",
            }

            search_path = query.replace(" ", "-")
            url = f"{self.base_url}/ofertas-trabajo/{search_path}/?{urlencode(query_params)}"

            await page.goto(url, wait_until="domcontentloaded")
            await page.wait_for_selector("article.js-job-card", timeout=30000)

            job_cards = await page.query_selector_all("article.js-job-card")
            if not job_cards:
                log.debug(f"No job cards found on page {page_num}")
                return None

            job_posts = []
            for card in job_cards:
                try:
                    job_post = await self._extract_job_info(card)
                    if job_post:
                        job_posts.append(job_post)
                except Exception as e:
                    log.error(f"Error extracting job info: {str(e)}")

            return job_posts
        except Exception as e:
            log.error(f"Error fetching jobs: {str(e)}")
            return None

    async def _extract_job_info(self, card) -> JobPost | None:
        try:
            title_el = await card.query_selector("a.js-o-link")
            title = await title_el.inner_text() if title_el else None
            href = await title_el.get_attribute("href") if title_el else None
            job_url = href if href and href.startswith("http") else f"{self.base_url}{href}"

            company_el = await card.query_selector("span[data-test='company-name']")
            company = await company_el.inner_text() if company_el else "Unknown"

            location_el = await card.query_selector("span[data-test='location']")
            location = await location_el.inner_text() if location_el else "Spain"

            job_id = f"infojobs-{abs(hash(job_url))}"
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