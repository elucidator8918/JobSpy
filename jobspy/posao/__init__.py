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

log = create_logger("PosaoHR")


class PosaoHRScraper(Scraper):
    base_url = "https://www.posao.hr"
    delay = 2
    band_delay = 3
    country = "Croatia"

    def __init__(self, proxies: list[str] | str | None = None, ca_cert: str | None = None):
        super().__init__(Site.POSAOHR, proxies=proxies, ca_cert=ca_cert)
        self.scraper_input: ScraperInput | None = None

    def scrape(self, scraper_input: ScraperInput) -> JobResponse:
        self.scraper_input = scraper_input
        return asyncio.run(self._async_scrape())

    async def _async_scrape(self) -> JobResponse:
        job_list: List[JobPost] = []
        wanted = self.scraper_input.results_wanted or 10

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)
            ctx = await browser.new_context()
            page = await ctx.new_page()

            page_num = 1
            while len(job_list) < wanted:
                log.info(f"📄 Fetching page {page_num}")
                jobs = await self._fetch_jobs(page, self.scraper_input.search_term, ctx, page_num)
                if not jobs:
                    break
                job_list.extend(jobs[: wanted - len(job_list)])
                page_num += 1
                await asyncio.sleep(random.uniform(self.delay, self.delay + self.band_delay))

            await browser.close()

        return JobResponse(jobs=job_list)

    async def _fetch_jobs(self, page: Page, query: str, context, page_num: int) -> List[JobPost] | None:
        try:
            # Navigate to search
            await page.goto(self.base_url, wait_until="load")
            # Accept cookies using same logic from sync version
            try:
                btn = page.get_by_role("button", name="Dopusti sve")
                await btn.click(timeout=5000)
                log.info("✅ Clicked 'Dopusti sve'")
            except Exception:
                log.info("ℹ️ No cookie button found")

            # Fill the search box and click
            searchbox = page.get_by_role("searchbox", name="Enter keywords...")
            await searchbox.click()
            await searchbox.fill(query)
            await page.get_by_role("link", name="Search", exact=True).click()
            await page.wait_for_selector("main", timeout=10000)

            # Select job links like the sync code
            links = page.locator("main a:has-text('Expires in')")
            count = await links.count()
            log.info(f"Found {count} job postings on page {page_num}")
            if count == 0:
                return None

            out: List[JobPost] = []
            for i in range(count):
                link = links.nth(i)
                title = (await link.inner_text()).strip()
                href = await link.get_attribute("href")
                job_url = href if href.startswith("http") else self.base_url + href

                log.debug(f"Processing job: {title} → {job_url}")
                post = await self._process_job_detail(context, title, job_url)
                if post:
                    out.append(post)
            return out

        except Exception as e:
            log.error(f"Error on page {page_num}: {e!r}")
            return None

    async def _process_job_detail(self, context, title: str, job_url: str) -> JobPost | None:
        try:
            detail = await context.new_page()
            await detail.goto(job_url)
            await detail.wait_for_selector("#content", timeout=8000)
            description = (await detail.locator("#content").inner_text()).strip()
            await detail.close()

            job_id = f"posaohr-{abs(hash(job_url))}"
            # Attempt to parse company and location—set placeholders if missing
            loc, comp = None, None
            # You can add more parsing logic here if needed

            loc_obj = Location(city=loc or "", country=Country.from_string(self.country))

            return JobPost(
                id=job_id,
                title=title,
                company_name=comp or "",
                location=loc_obj,
                job_url=job_url,
                description=description,
            )
        except Exception as e:
            log.error(f"Failed detail fetch for {job_url}: {e!r}")
            return None