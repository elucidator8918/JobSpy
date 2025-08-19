from __future__ import annotations

import os
import requests
import asyncio
from typing import List
from google import genai

from jobspy.model import (
    Scraper,
    ScraperInput,
    Site,
    JobPost,
    JobResponse,
    Location,
    Country,
    Compensation,
    CompensationInterval,
    UpworkJobListing,
)
from jobspy.util import create_logger

log = create_logger("Upwork")


class UpworkScraper(Scraper):
    base_url = "https://www.upwork.com"

    def __init__(
        self,
        proxies: list[str] | str | None = None,
        ca_cert: str | None = None,
        user_agent: str | None = None,
    ):
        super().__init__(Site.UPWORK, proxies=proxies, ca_cert=ca_cert)
        self.scraper_input = None

    def scrape(self, scraper_input: ScraperInput) -> JobResponse:
        self.scraper_input = scraper_input
        return asyncio.run(self._async_scrape())

    async def _async_scrape(self) -> JobResponse:
        try:
            # 1. Scrape with Firecrawl
            markdown_content = await self._scrape_with_firecrawl(
                search_query=self.scraper_input.search_term, per_page=50
            )

            # 2. Process with Gemini
            job_listings = await self._process_with_gemini(markdown_content)

            # 3. Convert to JobPost objects
            job_posts = await self._convert_to_job_posts(job_listings)

            log.info(f"Successfully scraped {len(job_posts)} Upwork positions")
            return JobResponse(jobs=job_posts)

        except Exception as e:
            log.error(f"Error scraping Upwork: {str(e)}")
            return JobResponse(jobs=[])

    async def _scrape_with_firecrawl(
        self, search_query: str, per_page: int = 50
    ) -> str:
        """Scrape Upwork using Firecrawl API"""
        url = f"{self.base_url}/nx/search/jobs/?q={search_query.replace(' ', '%20')}&per_page={per_page}"

        payload = {
            "url": url,
            "formats": ["markdown"],
            "onlyMainContent": True,
            "proxy": "stealth",
            "parsePDF": True,
            "maxAge": 14400000,  # 4 hours cache
        }

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {os.getenv('FIRECRAWL_API_KEY')}",
        }

        try:
            response = requests.post(
                "https://api.firecrawl.dev/v1/scrape",
                headers=headers,
                json=payload,
                timeout=60,
            )
            response.raise_for_status()

            data = response.json()
            if data.get("success") and "markdown" in data.get("data", {}):
                return data["data"]["markdown"]
            else:
                raise Exception(
                    f"Firecrawl API error: {data.get('error', 'Unknown error')}"
                )

        except requests.exceptions.RequestException as e:
            raise Exception(f"Request failed: {str(e)}")

    async def _process_with_gemini(
        self, markdown_content: str
    ) -> List[UpworkJobListing]:
        """Process markdown content with Gemini to extract structured job data"""
        client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

        prompt = f"""
        Please analyze the following Upwork job listings markdown content and extract structured job information.

        For each job posting, extract:
        - job_title: The title of the job
        - job_link: Complete job link URL (prepend https://www.upwork.com if relative)
        - job_description: Summary of requirements/responsibilities
        - job_company: Name of the company or client (if available)
        - job_city: City requirement (if any, else null)
        - job_country: Country requirement (if any, else null)
        - job_type: Employment type (full-time, part-time, contract, freelance, etc.)
        - job_interval: Payment interval (hourly, daily, weekly, monthly, yearly, fixed-price)
        - job_salary_min: Minimum salary or hourly rate (if mentioned, else null)
        - job_salary_max: Maximum salary or hourly rate (if mentioned, else null)
        - job_salary_currency: Currency for the salary (default to USD if not specified)

        Focus on all job postings found. If any field is not explicitly mentioned, set it to null.

        Here's the markdown content:

        {markdown_content}
        """

        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config={
                    "response_mime_type": "application/json",
                    "response_schema": list[UpworkJobListing],
                },
            )

            job_listings: list[UpworkJobListing] = response.parsed
            return job_listings if job_listings else []

        except Exception as e:
            raise Exception(f"Gemini API error: {str(e)}")

    async def _convert_to_job_posts(
        self, job_listings: List[UpworkJobListing]
    ) -> List[JobPost]:
        """Convert UpworkJobListing objects to JobPost objects"""
        job_posts = []

        for job in job_listings:
            try:
                job_id = f"upwork-{abs(hash(job.job_link))}"
                location_obj = Location(
                    city=job.job_city,
                    country=Country.from_string(job.job_country),
                )

                job_post = JobPost(
                    id=job_id,
                    title=job.job_title,
                    company_name=job.job_company or "Unknown Client",
                    location=location_obj,
                    job_url=job.job_link,
                    description=job.job_description,
                    job_type=job.job_type,
                    compensation=Compensation(
                        interval=CompensationInterval.get_interval(job.job_interval),
                        min_amount=job.job_salary_min,
                        max_amount=job.job_salary_max,
                        currency=job.job_salary_currency or "USD",
                    ),
                )
                job_posts.append(job_post)

            except Exception as e:
                log.error(f"Error converting job listing to JobPost: {str(e)}")
                continue

        return job_posts
