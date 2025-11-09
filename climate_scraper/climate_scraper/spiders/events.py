import scrapy
from scrapy_playwright.page import PageMethod
from datetime import datetime
import google.generativeai as genai
import os
import re
import pytz
import json

class ClimateEventsSpider(scrapy.Spider):
    name = "climate_events"
    
    custom_settings = {
        'DOWNLOAD_HANDLERS': {
            'http': 'scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler',
            'https': 'scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler',
        },
        'TWISTED_REACTOR': 'twisted.internet.asyncioreactor.AsyncioSelectorReactor',
        'ITEM_PIPELINES': {
           'climate_scraper.pipelines.ClimateEventsPipeline': 300,
        },
        'PLAYWRIGHT_BROWSER_TYPE': 'chromium',
        'PLAYWRIGHT_LAUNCH_OPTIONS': {
            'headless': True,
            'timeout': 90000,
            'args': ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage']
        },
        'PLAYWRIGHT_DEFAULT_NAVIGATION_TIMEOUT': 90000,
        'USER_AGENT': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'CONCURRENT_REQUESTS': 1,  # Reduced to 1 for stability
        'DOWNLOAD_DELAY': 5,  # Increased delay
        'ROBOTSTXT_OBEY': False,
    }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.scraped_count = 0
        self.failed_count = 0
        self.ist = pytz.timezone('Asia/Kolkata')
        
        # Get configuration from environment
        self.urls_to_scrape = self.get_urls_from_env()
        self.format_columns = self.get_format_from_env()
        
        self.logger.info(f"🎯 Initialized with {len(self.urls_to_scrape)} URLs")
        self.logger.info(f"📋 Extracting {len(self.format_columns)} fields per event")
        self.logger.info(f"📝 Columns: {self.format_columns}")
    
    def get_urls_from_env(self):
        """Get URLs from environment variable"""
        urls_str = os.getenv("SCRAPER_URLS", "")
        self.logger.info(f"🔍 Reading URLs from environment")
        
        if urls_str:
            urls = [url.strip() for url in urls_str.split(",") if url.strip()]
            self.logger.info(f"✅ Found {len(urls)} URLs")
            for i, url in enumerate(urls, 1):
                self.logger.info(f"  {i}. {url}")
            return urls
        
        self.logger.error("❌ No URLs found!")
        return []
    
    def get_format_from_env(self):
        """Get format columns from environment variable"""
        columns_str = os.getenv("SCRAPER_COLUMNS", "")
        self.logger.info(f"🔍 Reading column format from environment")
        
        if columns_str:
            columns = [col.strip() for col in columns_str.split(",") if col.strip()]
            self.logger.info(f"✅ Found {len(columns)} columns")
            for i, col in enumerate(columns[:5], 1):
                self.logger.info(f"  {i}. {col}")
            return columns
        
        self.logger.warning("⚠️ No columns found, using defaults")
        return ["Event Name", "Date", "Location", "Description"]
    
    def start_requests(self):
        """Generate requests for all configured URLs"""
        if not self.urls_to_scrape:
            self.logger.error("❌ No URLs configured!")
            return
        
        for url in self.urls_to_scrape:
            if not url.startswith(('http://', 'https://')):
                url = 'https://' + url
            
            self.logger.info(f"🌐 Creating request for: {url}")
            
            yield scrapy.Request(
                url,
                callback=self.parse_events_page,
                meta={
                    "playwright": True,
                    "playwright_include_page": True,
                    "playwright_page_methods": [
                        PageMethod("wait_for_load_state", "networkidle", timeout=60000),
                    ],
                },
                errback=self.errback_close_page,
                dont_filter=True
            )
    
    async def errback_close_page(self, failure):
        """Handle request failures"""
        page = failure.request.meta.get("playwright_page")
        if page:
            try:
                await page.close()
            except:
                pass
        
        url = failure.request.url
        self.logger.error(f"❌ Request failed for {url}: {failure.value}")
        self.failed_count += 1
        
        # Yield a fallback item
        yield self.create_fallback_item(url, f"Request failed: {failure.value}")
    
    async def parse_events_page(self, response):
        """Parse the events listing page"""
        page = response.meta.get("playwright_page")
        url = response.url
        
        self.logger.info(f"=" * 80)
        self.logger.info(f"🌍 SCRAPING EVENTS FROM: {url}")
        self.logger.info(f"=" * 80)
        
        try:
            # Wait for page to load
            self.logger.info(f"⏳ Waiting for page to load...")
            await page.wait_for_timeout(5000)
            
            # Scroll to load all events
            self.logger.info(f"📜 Scrolling page to load all events...")
            try:
                await page.evaluate('''async () => {
                    for (let i = 0; i < 5; i++) {
                        window.scrollTo(0, document.body.scrollHeight);
                        await new Promise(resolve => setTimeout(resolve, 2000));
                    }
                    window.scrollTo(0, 0);
                }''')
                await page.wait_for_timeout(3000)
            except Exception as scroll_error:
                self.logger.warning(f"⚠️ Scroll error (continuing): {scroll_error}")
            
            # Get page content
            self.logger.info(f"📄 Extracting page content...")
            try:
                page_text = await page.evaluate('''() => {
                    const unwanted = document.querySelectorAll(
                        'script, style, nav, header, footer, .cookie-banner, .modal, iframe, noscript'
                    );
                    unwanted.forEach(el => el.remove());
                    
                    let main = document.querySelector('main');
                    if (!main) main = document.querySelector('[role="main"]');
                    if (!main) main = document.querySelector('.main-content');
                    if (!main) main = document.body;
                    
                    return main.innerText;
                }''')
                
                page_title = await page.title()
            except Exception as extract_error:
                self.logger.error(f"❌ Content extraction error: {extract_error}")
                raise
            
            # Clean text
            page_text = re.sub(r'\s+', ' ', page_text).strip()
            
            self.logger.info(f"📊 Page stats:")
            self.logger.info(f"  - Title: {page_title}")
            self.logger.info(f"  - Content: {len(page_text)} chars")
            
            if len(page_text) < 100:
                self.logger.error(f"❌ Insufficient content from {url}")
                self.failed_count += 1
                yield self.create_fallback_item(url, "Insufficient content - page may be blocked or empty")
                return
            
            # Limit content size
            page_text = page_text[:40000]  # 40k chars
            
            # Extract events using Gemini
            self.logger.info(f"🤖 Sending to Gemini AI to extract events...")
            events_data = await self.extract_events_with_gemini(
                url,
                page_title,
                page_text,
                self.format_columns
            )
            
            if events_data and len(events_data) > 0:
                self.logger.info(f"✅ Found {len(events_data)} events on {url}")
                
                for idx, event in enumerate(events_data, 1):
                    self.scraped_count += 1
                    event["scraped_at"] = datetime.now(self.ist).strftime("%Y-%m-%d %H:%M:%S")
                    event["source_url"] = url
                    event["scraping_status"] = "Success"
                    
                    # Get first column name for logging
                    first_col = self.format_columns[0] if self.format_columns else "Event Name"
                    event_name = event.get(first_col, 'N/A')
                    self.logger.info(f"📌 Event {self.scraped_count} ({idx}/{len(events_data)}): {str(event_name)[:60]}")
                    
                    yield event
            else:
                self.logger.warning(f"⚠️ No events found on {url}")
                self.failed_count += 1
                yield self.create_fallback_item(url, "No events found - page structure may have changed")
                
        except Exception as e:
            self.logger.error(f"❌ Error parsing {url}: {e}")
            import traceback
            self.logger.error(f"Traceback:\n{traceback.format_exc()}")
            self.failed_count += 1
            yield self.create_fallback_item(url, f"{type(e).__name__}: {str(e)[:100]}")
        finally:
            try:
                if page:
                    await page.close()
            except:
                pass
    
    async def extract_events_with_gemini(self, url, page_title, content, columns):
        """Use Gemini to extract multiple events from page"""
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            self.logger.error("❌ No Gemini API key found in environment!")
            return None
        
        try:
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel('gemini-2.0-flash')
            
            # Build column list for prompt
            columns_formatted = "\n".join([f'  "{col}"' for col in columns])
            
            # Create sample JSON structure
            sample_event = {col: "..." for col in columns}
            sample_json = json.dumps([sample_event], indent=2)
            
            prompt = f"""You are an expert at extracting climate and sustainability events from web pages.

**Website:** {url}
**Page Title:** {page_title}

**Content:**
{content}

**TASK:** Extract ALL climate/sustainability/environmental events from this page.

For EACH event found, extract these EXACT fields (use these exact names):
{columns_formatted}

**RULES:**
1. Extract ALL events on the page (there may be multiple)
2. If a field is not found, use "N/A"
3. For dates: extract in readable format like "15 January 2025" or "January 15-17, 2025"
4. For locations: include city and country, or "Virtual" if online
5. Keep descriptions concise (2-3 sentences maximum)
6. Extract organizers, sponsors, themes, formats, etc. as they appear in the column names

**CRITICAL:** Return ONLY a JSON array with these EXACT field names. No markdown, no explanations, just the JSON.

**Expected format:**
{sample_json}

Return the JSON array now:"""
            
            self.logger.info(f"🤖 Requesting Gemini extraction with {len(columns)} fields...")
            
            response = await model.generate_content_async(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=0.1,
                    max_output_tokens=8000
                )
            )
            
            if not response or not response.text:
                self.logger.error(f"❌ Empty Gemini response")
                return None
            
            response_text = response.text.strip()
            self.logger.info(f"✅ Gemini response received: {len(response_text)} chars")
            
            # Extract JSON from response
            json_str = self.extract_json_from_text(response_text)
            
            if not json_str:
                self.logger.error(f"❌ No JSON found in response")
                self.logger.error(f"Response preview: {response_text[:500]}")
                return None
            
            # Parse JSON
            try:
                events = json.loads(json_str)
            except json.JSONDecodeError as je:
                self.logger.error(f"❌ JSON parse error: {je}")
                self.logger.error(f"JSON string: {json_str[:1000]}")
                return None
            
            # Ensure it's a list
            if not isinstance(events, list):
                events = [events]
            
            self.logger.info(f"✅ Successfully parsed {len(events)} events from JSON")
            
            # Validate events have required fields
            valid_events = []
            for event in events:
                if isinstance(event, dict) and len(event) > 0:
                    valid_events.append(event)
            
            return valid_events
            
        except Exception as e:
            self.logger.error(f"❌ Gemini extraction error: {e}")
            import traceback
            self.logger.error(f"Traceback: {traceback.format_exc()}")
            return None
    
    def extract_json_from_text(self, text):
        """Extract JSON array from text that may contain markdown or other content"""
        # Remove markdown code blocks
        text = re.sub(r'```(?:json)?\s*', '', text)
        text = re.sub(r'```\s*', '', text)
        text = text.strip()
        
        # Try to find JSON array
        array_match = re.search(r'\[\s*\{.*?\}\s*\]', text, re.DOTALL)
        if array_match:
            return array_match.group(0)
        
        # Try to find single JSON object and wrap it
        obj_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', text, re.DOTALL)
        if obj_match:
            return '[' + obj_match.group(0) + ']'
        
        return None
    
    def create_fallback_item(self, url, error):
        """Create fallback item when scraping fails"""
        timestamp = datetime.now(self.ist).strftime("%Y-%m-%d %H:%M:%S")
        result = {
            "scraped_at": timestamp,
            "source_url": url,
            "scraping_status": f"Failed: {error}"
        }
        
        # Add N/A for all format columns
        for col in self.format_columns:
            result[col] = "N/A"
        
        return result
    
    def closed(self, reason):
        """Log summary when spider closes"""
        self.logger.info("=" * 80)
        self.logger.info(f"🎯 SCRAPING SESSION COMPLETE")
        self.logger.info(f"✅ Events successfully scraped: {self.scraped_count}")
        self.logger.info(f"❌ Pages failed: {self.failed_count}")
        self.logger.info(f"📊 Total URLs processed: {len(self.urls_to_scrape)}")
        self.logger.info("=" * 80)



# import scrapy
# from scrapy_playwright.page import PageMethod
# from datetime import datetime
# import google.generativeai as genai
# import os
# import re
# import pytz
# import json

# class ClimateEventsSpider(scrapy.Spider):
#     name = "climate_events"
    
#     custom_settings = {
#         'DOWNLOAD_HANDLERS': {
#             'http': 'scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler',
#             'https': 'scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler',
#         },
#         'TWISTED_REACTOR': 'twisted.internet.asyncioreactor.AsyncioSelectorReactor',
#         'ITEM_PIPELINES': {
#            'climate_scraper.pipelines.ClimateEventsPipeline': 300,
#         },
#         'PLAYWRIGHT_BROWSER_TYPE': 'chromium',
#         'PLAYWRIGHT_LAUNCH_OPTIONS': {
#             'headless': True,
#             'timeout': 90000,
#             'args': ['--no-sandbox', '--disable-setuid-sandbox']
#         },
#         'PLAYWRIGHT_DEFAULT_NAVIGATION_TIMEOUT': 90000,
#         'USER_AGENT': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
#         'CONCURRENT_REQUESTS': 2,
#         'DOWNLOAD_DELAY': 3,
#     }
    
#     def __init__(self, *args, **kwargs):
#         super().__init__(*args, **kwargs)
#         self.scraped_count = 0
#         self.failed_count = 0
#         self.ist = pytz.timezone('Asia/Kolkata')
        
#         # Get configuration from environment
#         self.urls_to_scrape = self.get_urls_from_env()
#         self.format_columns = self.get_format_from_env()
        
#         self.logger.info(f"🎯 Initialized with {len(self.urls_to_scrape)} URLs")
#         self.logger.info(f"📋 Extracting {len(self.format_columns)} fields per event")
    
#     def get_urls_from_env(self):
#         """Get URLs from environment variable"""
#         urls_str = os.getenv("SCRAPER_URLS", "")
#         self.logger.info(f"🔍 Reading URLs from environment")
        
#         if urls_str:
#             urls = [url.strip() for url in urls_str.split(",") if url.strip()]
#             self.logger.info(f"✅ Found {len(urls)} URLs")
#             for i, url in enumerate(urls, 1):
#                 self.logger.info(f"  {i}. {url}")
#             return urls
        
#         self.logger.error("❌ No URLs found!")
#         return []
    
#     def get_format_from_env(self):
#         """Get format columns from environment variable"""
#         columns_str = os.getenv("SCRAPER_COLUMNS", "")
#         self.logger.info(f"🔍 Reading column format from environment")
        
#         if columns_str:
#             columns = [col.strip() for col in columns_str.split(",") if col.strip()]
#             self.logger.info(f"✅ Found {len(columns)} columns")
#             self.logger.info(f"Columns: {', '.join(columns[:10])}...")
#             return columns
        
#         self.logger.warning("⚠️ No columns found, using defaults")
#         return ["Event Name", "Date", "Location", "Description", "Organizer"]
    
#     def start_requests(self):
#         """Generate requests for all configured URLs"""
#         if not self.urls_to_scrape:
#             self.logger.error("❌ No URLs configured!")
#             return
        
#         for url in self.urls_to_scrape:
#             if not url.startswith(('http://', 'https://')):
#                 url = 'https://' + url
            
#             yield scrapy.Request(
#                 url,
#                 callback=self.parse_events_page,
#                 meta={
#                     "playwright": True,
#                     "playwright_include_page": True,
#                     "playwright_page_methods": [
#                         PageMethod("wait_for_load_state", "networkidle", timeout=30000),
#                     ],
#                 },
#                 errback=self.errback_close_page,
#                 dont_filter=True
#             )
    
#     async def errback_close_page(self, failure):
#         page = failure.request.meta.get("playwright_page")
#         if page:
#             await page.close()
#         self.logger.error(f"❌ Request failed: {failure}")
#         self.failed_count += 1
    
#     async def parse_events_page(self, response):
#         """Parse the events listing page"""
#         page = response.meta["playwright_page"]
#         url = response.url
        
#         self.logger.info(f"=" * 80)
#         self.logger.info(f"🌍 SCRAPING EVENTS FROM: {url}")
#         self.logger.info(f"=" * 80)
        
#         try:
#             # Wait for page to load
#             await page.wait_for_timeout(5000)
            
#             # Scroll to load all events
#             self.logger.info(f"📜 Scrolling page to load all events...")
#             await page.evaluate('''async () => {
#                 for (let i = 0; i < 3; i++) {
#                     window.scrollTo(0, document.body.scrollHeight);
#                     await new Promise(resolve => setTimeout(resolve, 2000));
#                 }
#                 window.scrollTo(0, 0);
#             }''')
            
#             await page.wait_for_timeout(3000)
            
#             # Get page content
#             self.logger.info(f"📄 Extracting page content...")
#             page_text = await page.evaluate('''() => {
#                 const unwanted = document.querySelectorAll(
#                     'script, style, nav, header, footer, .cookie-banner, .modal, iframe, noscript'
#                 );
#                 unwanted.forEach(el => el.remove());
                
#                 let main = document.querySelector('main');
#                 if (!main) main = document.querySelector('[role="main"]');
#                 if (!main) main = document.querySelector('.main-content');
#                 if (!main) main = document.body;
                
#                 return main.innerText;
#             }''')
            
#             page_title = await page.title()
            
#             # Clean text
#             page_text = re.sub(r'\s+', ' ', page_text).strip()
            
#             self.logger.info(f"📊 Page stats:")
#             self.logger.info(f"  - Title: {page_title}")
#             self.logger.info(f"  - Content: {len(page_text)} chars")
            
#             if len(page_text) < 200:
#                 self.logger.error(f"❌ Insufficient content from {url}")
#                 self.failed_count += 1
#                 yield self.create_fallback_item(url, "Insufficient content - possible blocking")
#                 return
            
#             page_text = page_text[:30000]  # Limit to 30k chars
            
#             # Extract events using Gemini
#             self.logger.info(f"🤖 Sending to Gemini to extract events...")
#             events_data = await self.extract_events_with_gemini(
#                 url,
#                 page_title,
#                 page_text,
#                 self.format_columns
#             )
            
#             if events_data and len(events_data) > 0:
#                 self.logger.info(f"✅ Found {len(events_data)} events on {url}")
                
#                 for event in events_data:
#                     self.scraped_count += 1
#                     event["scraped_at"] = datetime.now(self.ist).strftime("%Y-%m-%d %H:%M:%S")
#                     event["source_url"] = url
#                     event["scraping_status"] = "Success"
                    
#                     self.logger.info(f"📌 Event {self.scraped_count}: {event.get('Name of event', 'N/A')[:50]}")
#                     yield event
#             else:
#                 self.logger.warning(f"⚠️ No events found on {url}")
#                 self.failed_count += 1
#                 yield self.create_fallback_item(url, "No events found")
                
#         except Exception as e:
#             self.logger.error(f"❌ Error parsing {url}: {e}")
#             import traceback
#             self.logger.error(f"Traceback:\n{traceback.format_exc()}")
#             self.failed_count += 1
#             yield self.create_fallback_item(url, f"{type(e).__name__}: {str(e)}")
#         finally:
#             try:
#                 await page.close()
#             except:
#                 pass
    
#     async def extract_events_with_gemini(self, url, page_title, content, columns):
#         """Use Gemini to extract multiple events from page"""
#         api_key = os.getenv("GOOGLE_API_KEY")
#         if not api_key:
#             self.logger.error("❌ No Gemini API key!")
#             return None
        
#         try:
#             genai.configure(api_key=api_key)
#             model = genai.GenerativeModel('gemini-2.0-flash')
            
#             # Build prompt for extracting MULTIPLE events
#             columns_list = "\n".join([f"  - {col}" for col in columns])
            
#             prompt = f"""You are an expert at extracting climate and sustainability events from web pages.

# Website: {url}
# Page Title: {page_title}

# Content:
# {content}

# TASK: Extract ALL climate/sustainability/environmental events from this page.

# For EACH event found, extract these fields:
# {columns_list}

# IMPORTANT:
# - Extract ALL events on the page (there may be multiple)
# - If a field is not found, use "N/A"
# - For dates: try to extract in format "DD Month YYYY" or "Month DD-DD YYYY"
# - For location: city, country, or "Virtual" if online
# - For description: be concise (2-3 sentences max)
# - For sponsors: list main sponsors if mentioned

# Return as a JSON array of events:
# [
#   {{
#     "{columns[0]}": "...",
#     "{columns[1]}": "...",
#     ...
#   }},
#   {{
#     "{columns[0]}": "...",
#     ...
#   }}
# ]

# Return ONLY the JSON array, no markdown, no explanations."""
            
#             self.logger.info(f"🤖 Requesting Gemini extraction...")
            
#             response = await model.generate_content_async(
#                 prompt,
#                 generation_config=genai.types.GenerationConfig(
#                     temperature=0.1,
#                     max_output_tokens=8000  # More tokens for multiple events
#                 )
#             )
            
#             if not response or not response.text:
#                 self.logger.error(f"❌ Empty Gemini response")
#                 return None
            
#             self.logger.info(f"✅ Gemini response: {len(response.text)} chars")
            
#             # Extract JSON array
#             json_str = response.text.strip()
#             json_str = re.sub(r'```(?:json)?\s*', '', json_str).strip()
#             json_str = re.sub(r'```\s*$', '', json_str).strip()
            
#             # Try to find JSON array
#             json_match = re.search(r'\[\s*\{.*?\}\s*\]', json_str, re.DOTALL)
            
#             if json_match:
#                 json_str = json_match.group(0)
#             else:
#                 # Maybe it's a single object, wrap in array
#                 obj_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', json_str, re.DOTALL)
#                 if obj_match:
#                     json_str = '[' + obj_match.group(0) + ']'
            
#             import json
#             events = json.loads(json_str)
            
#             if not isinstance(events, list):
#                 events = [events]
            
#             self.logger.info(f"✅ Parsed {len(events)} events from JSON")
            
#             return events
            
#         except json.JSONDecodeError as e:
#             self.logger.error(f"❌ JSON parse error: {e}")
#             self.logger.error(f"Response: {json_str[:500] if 'json_str' in locals() else 'N/A'}")
#             return None
#         except Exception as e:
#             self.logger.error(f"❌ Gemini error: {e}")
#             import traceback
#             self.logger.error(f"Traceback: {traceback.format_exc()}")
#             return None
    
#     def create_fallback_item(self, url, error):
#         """Create fallback item when scraping fails"""
#         timestamp = datetime.now(self.ist).strftime("%Y-%m-%d %H:%M:%S")
#         result = {
#             "scraped_at": timestamp,
#             "source_url": url,
#             "scraping_status": f"Failed: {error}"
#         }
        
#         for col in self.format_columns:
#             result[col] = "N/A"
        
#         return result
    
#     def closed(self, reason):
#         """Log summary when spider closes"""
#         self.logger.info("=" * 80)
#         self.logger.info(f"🎯 SCRAPING COMPLETE")
#         self.logger.info(f"✅ Events found: {self.scraped_count}")
#         self.logger.info(f"❌ Pages failed: {self.failed_count}")
#         self.logger.info("=" * 80)