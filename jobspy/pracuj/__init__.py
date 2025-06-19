from __future__ import annotations

import random
import time
import re
from typing import List
from bs4 import BeautifulSoup
from urllib.parse import urljoin, quote
import cloudscraper

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
        self.scraper = None

    def scrape(self, scraper_input: ScraperInput) -> JobResponse:
        self.scraper_input = scraper_input
        return self._cloudscraper_scrape()

    def _cloudscraper_scrape(self) -> JobResponse:
        job_list: list[JobPost] = []
        results_wanted = self.scraper_input.results_wanted or 10
        
        # Create cloudscraper instance
        self.scraper = cloudscraper.create_scraper(
            browser={
                'browser': 'chrome',
                'platform': 'windows',
                'mobile': False
            }
        )
        
        try:
            # Build initial URL
            url = self._build_url(
                keywords=self.scraper_input.search_term,
                city=getattr(self.scraper_input, 'location', None),
                page=1
            )
            
            log.info(f"Fetching initial PracujPL jobs from: {url}")
            
            # Get first page
            response = self._make_request(url)
            if not response:
                return JobResponse(jobs=[])
            
            # Get max page number
            max_page_num = self._get_max_page_number(response.text)
            log.info(f"Found {max_page_num} pages of results")
            
            current_page_num = 1
            while len(job_list) < results_wanted and current_page_num <= max_page_num:
                log.info(f"Processing page {current_page_num} of {max_page_num}")
                
                # Parse the current page
                jobs = self._parse_jobs_from_page(response.text, response.url)
                if not jobs:
                    break
                
                job_list.extend(jobs[: results_wanted - len(job_list)])
                
                # Move to next page if needed
                if current_page_num < max_page_num and len(job_list) < results_wanted:
                    current_page_num += 1
                    next_page_url = self._build_url(
                        keywords=self.scraper_input.search_term,
                        city=getattr(self.scraper_input, 'location', None),
                        page=current_page_num
                    )
                    log.info(f"Navigating to page {current_page_num}: {next_page_url}")
                    
                    # Add delay between requests
                    time.sleep(random.uniform(self.delay, self.delay + self.band_delay))
                    
                    response = self._make_request(next_page_url)
                    if not response:
                        break
                else:
                    break
                    
        except Exception as e:
            log.error(f"Error during scraping: {str(e)}")
        
        log.info(f"Collected {len(job_list)} jobs from PracujPL")
        return JobResponse(jobs=job_list)

    def _build_url(self, keywords=None, city=None, distance=None, page=1):
        """Constructs a URL for searching jobs on pracuj.pl."""
        base_url = "https://www.pracuj.pl/praca"
        url_parts = []

        if keywords:
            url_parts.append(f"/{quote(keywords)};kw")
        if city:
            url_parts.append(f"/{quote(city)};wp")

        url = base_url + "".join(url_parts)

        query_params = []
        if distance:
            query_params.append(f"rd={distance}")
        if page > 1:
            query_params.append(f"pn={page}")

        if query_params:
            url += "?" + "&".join(query_params)

        return url

    def _get_headers(self):
        """Generate HTTP headers that mimic a modern web browser."""
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36',
            'Accept': '*/*',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Connection': 'keep-alive',
            'Cache-Control': 'no-cache',
            'Host': 'www.pracuj.pl',
        }
        return headers

    def _make_request(self, url):
        """Makes an HTTP request using cloudscraper with proper error handling."""
        try:
            log.info(f"Making request to: {url}")
            headers = self._get_headers()

            response = self.scraper.get(
                url,
                headers=headers,
                allow_redirects=True,
                timeout=20
            )

            log.info(f"Response status: {response.status_code}")

            # Check for explicit blocks
            if response.status_code == 403:
                log.error(f"Cloudflare challenge likely failed. Status: 403.")
                return None
            elif "Przepraszamy, strona której szukasz jest niedostępna" in response.text or "detected unusual activity" in response.text:
                log.warning(f"Potential block detected despite status {response.status_code}")
                return None

            response.raise_for_status()
            return response

        except Exception as e:
            log.error(f"Request failed for {url}: {str(e)}")
            return None

    def _get_max_page_number(self, page_content: str) -> int:
        """Get the maximum page number from pagination."""
        try:
            soup = BeautifulSoup(page_content, "html.parser")
            max_page_element = soup.find(
                "span", {"data-test": "top-pagination-max-page-number"}
            )
            if max_page_element and max_page_element.text:
                return int(max_page_element.text.strip())
        except Exception as e:
            log.error(f"Error determining max page number: {str(e)}")
        return 1

    def _parse_jobs_from_page(self, page_content: str, base_url: str) -> List[JobPost] | None:
        """Parse job listings from the page content."""
        try:
            soup = BeautifulSoup(page_content, "html.parser")
            
            # Find the main offers container
            main_offers_area = soup.find('div', id='offers-list')
            if not main_offers_area:
                log.error("Could not find the main offers area ('div#offers-list')")
                return None

            # Find all job offer elements
            job_offer_elements = main_offers_area.find_all('div', attrs={'data-test-offerid': True})
            
            if not job_offer_elements:
                log.debug("No job offer elements found on page")
                return None
            
            log.debug(f"Found {len(job_offer_elements)} job offer elements on page")
            job_posts = []
            
            for element in job_offer_elements:
                try:
                    job_post = self._extract_job_info(element, base_url)
                    if job_post:
                        job_posts.append(job_post)
                except Exception as e:
                    log.error(f"Error extracting job info: {str(e)}")
            
            return job_posts
        except Exception as e:
            log.error(f"Error parsing jobs from page: {str(e)}")
            return None

    def _extract_job_info(self, offer_element, base_url) -> JobPost | None:
        """Extract job information from a job offer element."""
        try:
            # Extract Offer ID
            offer_id = offer_element.get("data-test-offerid")
            if not offer_id:
                log.warning("Could not find offer id")
                return None

            # Extract Position
            position_tag = offer_element.find('h2', attrs={'data-test': 'offer-title'})
            if not position_tag:
                log.warning("Could not find position tag")
                return None
            
            # Sometimes the title is inside an 'a' tag within the h2
            link_in_title = position_tag.find('a')
            if link_in_title and link_in_title.text:
                title = self._clean_text(link_in_title.text)
            else:
                title = self._clean_text(position_tag.text)

            # Validate title
            if not title or title.strip() == "":
                log.warning("Could not extract valid job title")
                return None

            # Extract Company Name
            company = "N/A"
            company_section = offer_element.find('div', attrs={'data-test': 'section-company'})
            if company_section:
                company_tag = company_section.find('h3', attrs={'data-test': 'text-company-name'})
                if company_tag:
                    company = self._clean_text(company_tag.text)
            else:
                # Fallback: Sometimes company name might be in the alt text of the logo image
                logo_img = offer_element.find('img', attrs={'data-test': 'image-responsive'})
                if logo_img and logo_img.get('alt'):
                    company = self._clean_text(logo_img['alt'])

            # Extract Location (City)
            location = "N/A"
            location_tag = offer_element.find('h4', attrs={'data-test': 'text-region'})
            if location_tag:
                location = self._clean_text(location_tag.text)
            else:
                # Sometimes location might be in a list item if multiple locations exist
                location_list_item = offer_element.find('li', attrs={'data-test': lambda x: x and x.startswith('offer-location-')})
                if location_list_item:
                    location = self._clean_text(location_list_item.text)

            # Extract Offer Link - ensure we always have a valid URL
            job_url = ""
            link_tag = None
            if position_tag:  # Prefer link within the title h2
                link_tag = position_tag.find('a')
            if not link_tag:  # Fallback to the direct link if not in title
                link_tag = offer_element.find('a', attrs={'data-test': 'link-offer'}, recursive=False)

            if link_tag and link_tag.get('href'):
                job_url = urljoin(base_url, link_tag['href'])
            else:
                # If no URL found, create a fallback URL
                job_url = f"{base_url}/oferta/{offer_id}" if offer_id else f"{base_url}/oferta/unknown"
                log.warning(f"Could not find job URL for offer {offer_id}, using fallback: {job_url}")

            # Create job ID
            job_id = f"pracujpl-{offer_id}" if offer_id else f"pracujpl-{abs(hash(job_url))}"

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

    def _clean_text(self, text):
        """Normalizes and sanitizes text by removing redundant whitespace."""
        if not text:
            return ""
        # Replace non-breaking spaces and trim
        text = text.replace('\xa0', ' ').strip()
        # Collapse multiple whitespace characters into a single space
        return re.sub(r'\s+', ' ', text.strip())