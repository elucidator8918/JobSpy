from __future__ import annotations

import random
import asyncio
from typing import List, Optional

from playwright.async_api import async_playwright, Page, TimeoutError as PlaywrightTimeoutError # Added TimeoutError

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

log = create_logger("ArbetsformedlingenSE")


class ArbetsformedlingenScraper(Scraper):
    base_url = "https://arbetsformedlingen.se"
    delay = 2
    band_delay = 3
    country = "Sweden" 

    def __init__(self, proxies: list[str] | str | None = None, ca_cert: str | None = None):
        super().__init__(Site.ARBETSFORMEDLINGEN, proxies=proxies, ca_cert=ca_cert) # site needs to be provided
        self.scraper_input: Optional[ScraperInput] = None # Initialize as Optional

    def scrape(self, scraper_input: ScraperInput) -> JobResponse:
        self.scraper_input = scraper_input
        return asyncio.run(self._async_scrape())

    async def _get_job_description_detail(self, page: Page) -> str:
        """
        Extracts the job description from the job detail page.
        This is an async adaptation of the user's get_job_description function.
        """
        try:
            await page.wait_for_selector("pb-section-job-main-content", timeout=10000)
            main_content = page.locator("pb-section-job-main-content")

            if await main_content.count() == 1:
                # Try heading "Om jobbet"
                heading_om_jobbet = main_content.locator("h2", has_text="Om jobbet")
                if await heading_om_jobbet.count() == 1:
                    return (await main_content.inner_text()).strip()
                
                # Try heading "Om anställningen"
                heading_om_anstallningen = main_content.locator("h2", has_text="Om anställningen")
                if await heading_om_anstallningen.count() == 1:
                    return (await main_content.inner_text()).strip()

                # Otherwise return all text inside main_content
                return (await main_content.inner_text()).strip()

            # Fallback: entire page content (less ideal)
            log.warning("Main content section not found as expected, falling back to full page content.")
            return await page.content()
        except PlaywrightTimeoutError:
            log.error("Timeout waiting for job description main content.")
            return "Error: Could not load job description content."
        except Exception as e:
            log.error(f"Error extracting job description: {e}")
            return f"Error: Could not extract job description due to {e}"

    async def _async_scrape(self) -> JobResponse:
        if not self.scraper_input:
            log.error("Scraper input not set.")
            return JobResponse(jobs=[])

        job_list: list[JobPost] = []
        results_wanted = self.scraper_input.results_wanted or 10 # Default to 10 if not specified

        async with async_playwright() as p:
            # Consider using self.scraper_input.headless
            browser = await p.chromium.launch(headless=False)
            context = await browser.new_context()
            page = await context.new_page()

            # Go to job search page
            initial_search_url = f"{self.base_url}/platsbanken/"
            log.info(f"Navigating to initial search page: {initial_search_url}")
            await page.goto(initial_search_url, wait_until="domcontentloaded")

            # Accept cookies if visible
            try:
                cookie_button = page.get_by_role("button", name="Jag godkänner alla kakor", exact=True)
                if await cookie_button.is_visible(timeout=5000):
                    await cookie_button.click()
                    log.info("✅ Accepted cookies")
                else:
                    log.info("🍪 Cookie consent button not visible or already accepted.")
            except PlaywrightTimeoutError:
                log.info("⚠️ Cookie consent button not found (timeout) or already accepted.")
            except Exception as e:
                log.warning(f"Error handling cookie consent: {e}")


            # Fill in search term and submit
            log.info(f"Performing search for: '{self.scraper_input.search_term}'")
            await page.get_by_label("Sök på ett eller flera ord,").fill(self.scraper_input.search_term)
            await page.get_by_label("Sök", exact=True).click()

            # Wait for search results to load
            try:
                await page.wait_for_selector("pb-feature-search-result-card", timeout=15000)
                await asyncio.sleep(2)  # Stabilize content
            except PlaywrightTimeoutError:
                log.error("Timeout waiting for initial search results to load.")
                await browser.close()
                return JobResponse(jobs=[])

            current_page_num = 1
            while len(job_list) < results_wanted:
                log.info(f"Processing search results page {current_page_num}. Found {len(job_list)}/{results_wanted} jobs so far.")

                # If not the first page, navigate to the next page of results
                if current_page_num > 1:
                    search_query_param = self.scraper_input.search_term.replace(" ", "+")
                    next_page_url = (
                        f"{self.base_url}/platsbanken/annonser?"
                        f"q={search_query_param}&page={current_page_num}"
                    )
                    log.info(f"Navigating to next page: {next_page_url}")
                    try:
                        await page.goto(next_page_url, wait_until="domcontentloaded")
                        await page.wait_for_selector("pb-feature-search-result-card", timeout=10000)
                        await asyncio.sleep(1) # Stabilize
                    except PlaywrightTimeoutError:
                        log.info(f"No more job cards found on page {current_page_num} or page failed to load. Ending scrape.")
                        break # No more pages or error
                    except Exception as e:
                        log.error(f"Error navigating to page {current_page_num}: {e}")
                        break


                job_card_locators = await page.locator("pb-feature-search-result-card").all()
                if not job_card_locators:
                    log.info(f"No job cards found on page {current_page_num}. This might be the end of results.")
                    break
                
                log.info(f"Found {len(job_card_locators)} job cards on page {current_page_num}.")

                for i in range(len(job_card_locators)):
                    if len(job_list) >= results_wanted:
                        break
                    
                    # Re-locate the card to avoid staleness issues after navigation
                    # This is important because page.go_back() reloads, and locators might become stale.
                    # We need to ensure we are still on the search results page before re-locating.
                    try:
                        await page.wait_for_selector("pb-feature-search-result-card", timeout=5000) # Ensure we are on results page
                    except PlaywrightTimeoutError:
                        log.error("Lost search results page context. Aborting current page processing.")
                        break # Break from inner loop, will try next page or end.

                    job_card = page.locator("pb-feature-search-result-card").nth(i)

                    try:
                        title_el = job_card.locator("h3 a")
                        title = (await title_el.inner_text()).strip()
                        link = await title_el.get_attribute("href")
                        if not link:
                            log.warning(f"Could not get link for job card {i+1} on page {current_page_num}. Skipping.")
                            continue
                        
                        detail_url = f"{self.base_url}{link}" if link.startswith("/") else link

                        company_el = job_card.locator("strong.pb-company-name")
                        company_raw = (await company_el.inner_text()).strip() if await company_el.count() > 0 else "N/A"
                        
                        # Attempt to get a more specific location if available
                        # Arbetsförmedlingen often includes location in company or has a separate field
                        location_text = "N/A"
                        location_el = job_card.locator("div.pb-location") # Common selector for location
                        if await location_el.count() > 0:
                            location_text = (await location_el.inner_text()).strip()
                        else: # Fallback if specific location element not found, parse from company string (simplistic)
                            parts = company_raw.split(',')
                            if len(parts) > 1:
                                location_text = parts[-1].strip() # Assume last part after comma is city
                                company_name = ','.join(parts[:-1]).strip()
                            else:
                                company_name = company_raw
                                # Could try to extract city from company_raw using regex if needed
                        
                        if location_text == "N/A" and company_name != "N/A": # if location still N/A try from company
                             parts = company_name.split(',')
                             if len(parts) > 1:
                                location_text = parts[-1].strip()
                                company_name = ','.join(parts[:-1]).strip()


                        log.info(f"🔗 Navigating to job detail: {title} at {detail_url}")
                        await page.goto(detail_url, wait_until="domcontentloaded")
                        
                        description = await self._get_job_description_detail(page)
                        
                        # For published date, it's often relative ("Idag", "Igår", "3 dagar sedan")
                        # You might need more complex parsing or decide if it's crucial.
                        # Example for date from your sync code:
                        # pub_date_el = job_card.locator("div.bottom__left > div.ng-star-inserted").nth(1)
                        # pub_date = (await pub_date_el.inner_text()).strip() if await pub_date_el.count() > 0 else None
                        
                        job_post = JobPost(
                            id=f"arbetsformedlingen-{abs(hash(detail_url))}", # Simple unique ID
                            title=title,
                            company_name=company_name,
                            location=Location(
                                country=Country.from_string(self.country), 
                                city=location_text, 
                                state=None # Sweden doesn't use states like the US
                            ),
                            job_url=detail_url,
                            description=description,
                            # date_posted=pub_date, # If you extract and parse it
                        )
                        job_list.append(job_post)
                        log.info(f"✅ Extracted job {len(job_list)}/{results_wanted}: {title}")

                        # Go back to search results
                        await page.go_back(wait_until="domcontentloaded")
                        # Ensure search results are loaded again
                        await page.wait_for_selector("pb-feature-search-result-card", timeout=10000)
                        await asyncio.sleep(random.uniform(0.5, 1.5)) # Short delay after going back

                    except PlaywrightTimeoutError as e:
                        log.error(f"Timeout processing job card {i+1} on page {current_page_num}: {e}. Skipping card.")
                        # If a timeout occurs, try to go back to a stable state (search results)
                        if page.url != initial_search_url and not page.url.startswith(f"{self.base_url}/platsbanken/annonser"):
                            try:
                                await page.go_back(wait_until="domcontentloaded")
                                await page.wait_for_selector("pb-feature-search-result-card", timeout=5000)
                            except Exception as ex:
                                log.warning(f"Failed to go back to search results after error: {ex}")
                                break # Break inner loop
                        continue # Skip to next card
                    except Exception as e:
                        log.error(f"Error processing job card {i+1} on page {current_page_num}: {e}. Skipping card.")
                        # Similar recovery attempt
                        if page.url != initial_search_url and not page.url.startswith(f"{self.base_url}/platsbanken/annonser"):
                            try:
                                await page.go_back(wait_until="domcontentloaded")
                                await page.wait_for_selector("pb-feature-search-result-card", timeout=5000)
                            except Exception as ex:
                                log.warning(f"Failed to go back to search results after error: {ex}")
                                break # Break inner loop
                        continue


                if len(job_list) >= results_wanted:
                    log.info(f"Reached desired number of results ({results_wanted}).")
                    break
                
                # If no jobs were processed on this page (e.g. all skipped due to errors, or no cards)
                # and we haven't reached results_wanted, it implies no more valid jobs on this page.
                if not job_card_locators: # if we broke out because no cards initially
                    break


                current_page_num += 1
                await asyncio.sleep(random.uniform(self.delay, self.delay + self.band_delay)) # Delay between pages

            await browser.close()
            log.info(f"Scraping finished. Total jobs extracted: {len(job_list)}")

        return JobResponse(jobs=job_list)