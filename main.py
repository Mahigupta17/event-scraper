from flask import Flask, render_template_string, request, jsonify
import subprocess
import os
import threading
import time
from datetime import datetime
import csv
import io
import pandas as pd
import json
import traceback

app = Flask(__name__)

# -------------------------------------------------------------------------
# Global status and configuration
# -------------------------------------------------------------------------
scraper_status = {
    "running": False,
    "last_run": None,
    "message": "Ready",
    "events_found": 0
}

scraper_config = {
    "urls": [],
    "format_columns": [],
    "sheet_url": "https://docs.google.com/spreadsheets/d/1tDFA7DIRm0b-9mbZby2lNyfgYJtGXSjOwl5ezN3CeME/edit",
    "sheet_name": "Sheet4",
    "project_name": "Climate Events"
}

# -------------------------------------------------------------------------
# HTML Template placeholder (you can keep your long template)
# -------------------------------------------------------------------------
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head><title>Climate Events Scraper</title></head>
<body>
<h2>🌍 Climate Events Scraper</h2>
<form id="scraper-form" method="POST" enctype="multipart/form-data" action="/trigger">
    <label>Project Name:</label><br>
    <input type="text" name="project_name" value="Climate Events"><br><br>
    <label>Enter URLs (JSON list):</label><br>
    <textarea name="urls" rows="5" cols="60">["https://example.com/events"]</textarea><br><br>
    <label>Upload Format File (.csv or .xlsx):</label><br>
    <input type="file" name="format_file"><br><br>
    <button type="submit">Start Scraper</button>
</form>
</body>
</html>
"""

# -------------------------------------------------------------------------
# Run Scraper in Background Thread
# -------------------------------------------------------------------------
def run_scraper_background():
    global scraper_status

    print("\n" + "="*80)
    print("🌍 STARTING CLIMATE EVENTS SCRAPER")
    print("="*80)

    scraper_status.update({
        "running": True,
        "last_run": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "message": "Initializing...",
        "events_found": 0
    })

    try:
        env = os.environ.copy()

        creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "credentials.json")
        if not os.path.exists(creds_path):
            for alt in ["credentials.json", "/app/credentials.json"]:
                if os.path.exists(alt):
                    creds_path = alt
                    break

        env["GOOGLE_APPLICATION_CREDENTIALS"] = creds_path
        print(f"🔑 Credentials: {creds_path}")
        print(f"🔗 URLs: {len(scraper_config['urls'])}")
        print(f"📋 Columns: {len(scraper_config['format_columns'])}")
        print("-"*80)

        scraper_status["message"] = f"Scraping {len(scraper_config['urls'])} websites..."

        # Create the dynamic Scrapy spider file
        spider_path = "/tmp/dynamic_spider.py"
        with open(spider_path, "w") as f:
            f.write(generate_spider_code())

        # Run spider with Scrapy process
        cmd = [
            "python", "-c",
            "import sys; "
            "sys.path.insert(0, '/tmp'); "
            "from dynamic_spider import ClimateEventsSpider; "
            "from scrapy.crawler import CrawlerProcess; "
            "process = CrawlerProcess(); "
            "process.crawl(ClimateEventsSpider); "
            "process.start()"
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            env=env,
            timeout=1800
        )

        print("="*80)
        print("✅ SCRAPER COMPLETED")
        print("="*80)

        output = result.stdout + result.stderr
        print(output)

        # Detect event count if present
        if "Events successfully scraped:" in output:
            for line in output.split("\n"):
                if "Events successfully scraped:" in line:
                    try:
                        count = int(line.split(":")[1].strip())
                        scraper_status["events_found"] = count
                    except:
                        pass

        scraper_status["message"] = "Completed successfully!"

    except subprocess.TimeoutExpired:
        print("⏱️ Timeout after 30 minutes")
        scraper_status["message"] = "Timed out after 30 minutes"

    except Exception as e:
        print(f"❌ Error: {e}")
        traceback.print_exc()
        scraper_status["message"] = f"Error: {str(e)[:200]}"

    finally:
        scraper_status["running"] = False
        print("="*80 + "\n")


# -------------------------------------------------------------------------
# Generate the dynamic Scrapy spider code
# -------------------------------------------------------------------------
def generate_spider_code():
    # Using json.dumps ensures valid Python syntax
    urls_json = json.dumps(scraper_config['urls'])
    columns_json = json.dumps(scraper_config['format_columns'])

    spider_code = f"""
import scrapy
from scrapy_playwright.page import PageMethod
from datetime import datetime
import google.generativeai as genai
import os, re, pytz, json

class ClimateEventsSpider(scrapy.Spider):
    name = "climate_events"

    custom_settings = {{
        'DOWNLOAD_HANDLERS': {{
            'http': 'scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler',
            'https': 'scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler',
        }},
        'TWISTED_REACTOR': 'twisted.internet.asyncioreactor.AsyncioSelectorReactor',
        'PLAYWRIGHT_BROWSER_TYPE': 'chromium',
        'PLAYWRIGHT_LAUNCH_OPTIONS': {{
            'headless': True,
            'args': ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage']
        }},
        'USER_AGENT': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
        'CONCURRENT_REQUESTS': 1,
        'DOWNLOAD_DELAY': 5
    }}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.urls_to_scrape = {urls_json}
        self.format_columns = {columns_json}
        self.scraped_count = 0
        self.failed_count = 0
        self.ist = pytz.timezone('Asia/Kolkata')

    def start_requests(self):
        for url in self.urls_to_scrape:
            if not url.startswith(('http://', 'https://')):
                url = 'https://' + url
            yield scrapy.Request(
                url,
                callback=self.parse,
                meta={{"playwright": True, "playwright_include_page": True}},
                errback=self.errback_close_page,
                dont_filter=True
            )

    async def errback_close_page(self, failure):
        page = failure.request.meta.get("playwright_page")
        if page:
            await page.close()
        self.logger.error(f"Request failed: {{failure.value}}")
        self.failed_count += 1

    async def parse(self, response):
        page = response.meta.get("playwright_page")
        url = response.url
        self.logger.info(f"Scraping {{url}}")
        await page.wait_for_timeout(2000)
        content = await page.content()
        await page.close()

        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            self.logger.error("No Gemini API key found in environment!")
            return
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-1.5-flash")

        prompt = f"Extract events from this HTML: {{content[:10000]}}"
        try:
            resp = await model.generate_content_async(prompt)
            self.logger.info(f"Gemini response: {{resp.text[:200]}}")
        except Exception as e:
            self.logger.error(f"Gemini error: {{e}}")

    def closed(self, reason):
        self.logger.info(f"Events successfully scraped: {{self.scraped_count}}")
        self.logger.info(f"Pages failed: {{self.failed_count}}")
"""
    return spider_code


# -------------------------------------------------------------------------
# Flask Routes
# -------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)


@app.route("/trigger", methods=["POST"])
def trigger():
    global scraper_status, scraper_config

    if scraper_status["running"]:
        return jsonify({"status": "already_running", "message": "Scraper is already running"}), 400

    try:
        project_name = request.form.get("project_name", "Climate_Events")
        urls_json = request.form.get("urls")
        format_file = request.files.get("format_file")

        print("\n" + "="*80)
        print("📥 RECEIVED SCRAPING REQUEST")
        print("="*80)

        if not format_file:
            return jsonify({"status": "error", "message": "No Excel/CSV file uploaded"}), 400

        urls = json.loads(urls_json)
        scraper_config["urls"] = urls
        scraper_config["project_name"] = project_name

        filename = format_file.filename.lower()

        # Read format columns
        if filename.endswith(".csv"):
            content = format_file.read().decode("utf-8", errors="ignore")
            reader = csv.reader(io.StringIO(content))
            headers = next(reader)
            scraper_config["format_columns"] = headers

        elif filename.endswith((".xlsx", ".xls")):
            df = pd.read_excel(format_file, nrows=1)
            scraper_config["format_columns"] = df.columns.tolist()

        else:
            return jsonify({"status": "error", "message": "Unsupported file type"}), 400

        print(f"✅ Config ready: {len(urls)} URLs, {len(scraper_config['format_columns'])} columns")

        thread = threading.Thread(target=run_scraper_background, daemon=True)
        thread.start()

        return jsonify({
            "status": "started",
            "message": f"Scraper started for {len(urls)} URLs"
        }), 200

    except Exception as e:
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/status")
def status():
    return jsonify(scraper_status)


@app.route("/health")
def health():
    return jsonify({"status": "healthy"}), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    print(f"🌐 Climate Events Scraper starting on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)



# from flask import Flask, render_template_string, request, jsonify
# import subprocess
# import os
# import threading
# import time
# from datetime import datetime
# import csv
# import io
# import pandas as pd

# app = Flask(__name__)

# # Track scraper status
# scraper_status = {
#     "running": False,
#     "last_run": None,
#     "message": "Ready",
#     "events_found": 0
# }

# # Store configuration
# scraper_config = {
#     "urls": [],
#     "format_columns": [],
#     "sheet_url": "https://docs.google.com/spreadsheets/d/1tDFA7DIRm0b-9mbZby2lNyfgYJtGXSjOwl5ezN3CeME/edit",
#     "sheet_name": "Sheet4",
#     "project_name": "Climate Events"
# }

# HTML_TEMPLATE = """
# <!DOCTYPE html>
# <html lang="en">
# <head>
#     <meta charset="UTF-8">
#     <meta name="viewport" content="width=device-width, initial-scale=1.0">
#     <title>Climate Events Scraper</title>
#     <style>
#         * { margin: 0; padding: 0; box-sizing: border-box; }
#         body { 
#             font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
#             background: linear-gradient(135deg, #1e3c72 0%, #2a5298 50%, #7e22ce 100%);
#             min-height: 100vh;
#             display: flex;
#             align-items: center;
#             justify-content: center;
#             padding: 20px;
#         }
#         .container { 
#             background: white;
#             padding: 40px;
#             border-radius: 20px;
#             box-shadow: 0 20px 60px rgba(0,0,0,0.3);
#             max-width: 800px;
#             width: 100%;
#         }
#         h1 { 
#             font-size: 36px;
#             color: #1e3c72;
#             margin-bottom: 10px;
#             font-weight: 700;
#             text-align: center;
#         }
#         .subtitle {
#             color: #666;
#             margin-bottom: 30px;
#             font-size: 16px;
#             text-align: center;
#         }
        
#         .section {
#             background: #f8f9fa;
#             border-radius: 12px;
#             padding: 20px;
#             margin: 20px 0;
#             border-left: 4px solid #1e3c72;
#         }
        
#         .section-title {
#             font-size: 18px;
#             font-weight: 600;
#             color: #333;
#             margin-bottom: 12px;
#             display: flex;
#             align-items: center;
#         }
        
#         .section-title .emoji {
#             font-size: 24px;
#             margin-right: 10px;
#         }
        
#         label {
#             display: block;
#             margin-bottom: 8px;
#             color: #555;
#             font-size: 14px;
#             font-weight: 500;
#         }
        
#         input[type="text"], textarea, input[type="file"] {
#             width: 100%;
#             padding: 12px;
#             border: 2px solid #e0e0e0;
#             border-radius: 8px;
#             font-size: 14px;
#             transition: border-color 0.3s;
#             font-family: inherit;
#         }
        
#         input[type="text"]:focus, textarea:focus {
#             outline: none;
#             border-color: #1e3c72;
#         }
        
#         textarea {
#             min-height: 120px;
#             resize: vertical;
#         }
        
#         .help-text {
#             font-size: 12px;
#             color: #888;
#             margin-top: 5px;
#         }
        
#         .btn {
#             background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%);
#             color: white;
#             border: none;
#             padding: 16px 40px;
#             border-radius: 50px;
#             font-size: 18px;
#             font-weight: 600;
#             cursor: pointer;
#             transition: all 0.3s ease;
#             box-shadow: 0 8px 20px rgba(30, 60, 114, 0.4);
#             margin-top: 20px;
#             width: 100%;
#         }
#         .btn:hover:not(:disabled) {
#             transform: translateY(-3px);
#             box-shadow: 0 12px 30px rgba(30, 60, 114, 0.6);
#         }
#         .btn:disabled {
#             background: #ccc;
#             cursor: not-allowed;
#             transform: none;
#             box-shadow: none;
#         }
        
#         .status-box {
#             margin-top: 30px;
#             padding: 20px;
#             border-radius: 12px;
#             font-size: 15px;
#             display: none;
#             animation: fadeIn 0.5s;
#         }
#         @keyframes fadeIn {
#             from { opacity: 0; transform: translateY(-10px); }
#             to { opacity: 1; transform: translateY(0); }
#         }
#         .status-box.show { display: block; }
#         .status-box.loading {
#             background: #fff3cd;
#             border: 2px solid #ffc107;
#             color: #856404;
#         }
#         .status-box.success {
#             background: #d4edda;
#             border: 2px solid #28a745;
#             color: #155724;
#         }
#         .status-box.error {
#             background: #f8d7da;
#             border: 2px solid #dc3545;
#             color: #721c24;
#         }
        
#         .spinner {
#             border: 4px solid #f3f3f3;
#             border-top: 4px solid #1e3c72;
#             border-radius: 50%;
#             width: 50px;
#             height: 50px;
#             animation: spin 1s linear infinite;
#             margin: 20px auto;
#             display: none;
#         }
#         .spinner.show { display: block; }
#         @keyframes spin {
#             0% { transform: rotate(0deg); }
#             100% { transform: rotate(360deg); }
#         }
        
#         .sheet-link {
#             display: inline-block;
#             margin-top: 20px;
#             color: #1e3c72;
#             text-decoration: none;
#             font-size: 14px;
#             transition: color 0.3s;
#             text-align: center;
#             width: 100%;
#         }
#         .sheet-link:hover { color: #7e22ce; text-decoration: underline; }
        
#         .upload-area {
#             border: 2px dashed #1e3c72;
#             border-radius: 8px;
#             padding: 30px;
#             text-align: center;
#             background: #f0f4ff;
#             cursor: pointer;
#             transition: all 0.3s;
#         }
#         .upload-area:hover {
#             background: #e3ecff;
#             border-color: #2a5298;
#         }
        
#         .preset-urls {
#             background: #e8f5e9;
#             padding: 15px;
#             border-radius: 8px;
#             margin-top: 10px;
#         }
        
#         .preset-urls h4 {
#             font-size: 14px;
#             color: #2e7d32;
#             margin-bottom: 8px;
#         }
        
#         .preset-urls ul {
#             list-style: none;
#             font-size: 12px;
#             color: #1b5e20;
#         }
        
#         .preset-urls li {
#             margin: 5px 0;
#         }

#         #fileInfo {
#             margin-top: 15px;
#             padding: 15px;
#             background: #e8f5e9;
#             border-radius: 8px;
#             border-left: 4px solid #4caf50;
#         }

#         #fileInfo p {
#             margin: 0;
#             color: #2e7d32;
#         }

#         #fileInfo button {
#             margin-top: 10px;
#             padding: 8px 16px;
#             background: #fff;
#             border: 1px solid #4caf50;
#             border-radius: 5px;
#             color: #2e7d32;
#             cursor: pointer;
#             font-size: 12px;
#         }

#         #fileInfo button:hover {
#             background: #f1f8f4;
#         }
#     </style>
# </head>
# <body>
#     <div class="container">
#         <h1>🌍 Climate Events Scraper</h1>
#         <p class="subtitle">Automated Climate & Sustainability Events Data Collection</p>
        
#         <!-- Section 1: Project Name -->
#         <div class="section">
#             <div class="section-title">
#                 <span class="emoji">📝</span>
#                 Project Name
#             </div>
#             <input type="text" id="projectName" placeholder="e.g., Climate Events 2025" value="Climate Events Collection">
#             <p class="help-text">Name your scraping project</p>
#         </div>
        
#         <!-- Section 2: Event Websites -->
#         <div class="section">
#             <div class="section-title">
#                 <span class="emoji">🔗</span>
#                 Event Websites to Scrape
#             </div>
#             <textarea id="urlList" placeholder="Enter event website URLs (one per line):
# https://thinklandscape.globallandscapesforum.org/71474/climate-events-2025/
# https://www.un.org/en/climatechange/events"></textarea>
#             <p class="help-text">Paste URLs of event aggregator websites, one per line</p>
            
#             <div class="preset-urls">
#                 <h4>🌟 Suggested Climate Event Websites:</h4>
#                 <ul>
#                     <li>✓ Eventbrite (climate + sustainability events)</li>
#                     <li>✓ UNFCCC Calendar</li>
#                     <li>✓ UN Climate Change Events</li>
#                     <li>✓ Global Landscapes Forum</li>
#                     <li>✓ Climate Tracker Events</li>
#                 </ul>
#             </div>
#         </div>
        
#         <!-- Section 3: Excel Format -->
#         <div class="section">
#             <div class="section-title">
#                 <span class="emoji">📋</span>
#                 Excel Format Template
#             </div>
#             <label for="formatFile">Upload your Excel template with column headers:</label>
            
#             <div class="upload-area" onclick="document.getElementById('formatFile').click()">
#                 <p style="font-size: 48px; margin-bottom: 10px;">📄</p>
#                 <p style="font-weight: 600; margin-bottom: 5px;" id="uploadPrompt">Click to upload Excel/CSV</p>
#                 <p class="help-text">Accepts .xlsx, .xls, or .csv files</p>
#             </div>
            
#             <input type="file" id="formatFile" accept=".csv,.xlsx,.xls" style="display: none;" onchange="handleFileUpload(this)">
            
#             <!-- Show uploaded file info -->
#             <div id="fileInfo" style="display: none;">
#                 <p style="font-weight: 600;">
#                     <span style="font-size: 20px;">✅</span> 
#                     <span id="fileName"></span>
#                 </p>
#                 <p style="margin: 5px 0 0 0; font-size: 12px; color: #1b5e20;">
#                     <span id="columnCount"></span> columns detected
#                 </p>
#                 <button onclick="clearFile()">
#                     🗑️ Remove & Upload Different File
#                 </button>
#             </div>
            
#             <div class="help-text" style="margin-top: 10px;">
#                 Expected columns: Event Name, Date, Location, Description, Organizer, Type, Topic, etc.
#             </div>
#         </div>
        
#         <!-- Section 4: Destination -->
#         <div class="section">
#             <div class="section-title">
#                 <span class="emoji">📊</span>
#                 Destination Google Sheet
#             </div>
#             <input type="text" id="sheetUrl" value="https://docs.google.com/spreadsheets/d/1tDFA7DIRm0b-9mbZby2lNyfgYJtGXSjOwl5ezN3CeME/edit" readonly>
#             <p class="help-text">Sheet: Sheet4 | Data will be appended to this sheet</p>
#         </div>
        
#         <button class="btn" id="scrapeBtn" onclick="startScraper()">
#             <span id="btnText">🚀 Start Scraping Events</span>
#         </button>
        
#         <div class="spinner" id="spinner"></div>
        
#         <div class="status-box" id="statusBox">
#             <div id="statusText"></div>
#         </div>
        
#         <a href="https://docs.google.com/spreadsheets/d/1tDFA7DIRm0b-9mbZby2lNyfgYJtGXSjOwl5ezN3CeME/edit?gid=0#gid=0" target="_blank" class="sheet-link">
#             📊 View Results in Google Sheet (Sheet4)
#         </a>
#     </div>
    
#     <script>
#         let uploadedFormat = null;
#         let extractedColumns = [];
        
#         function handleFileUpload(input) {
#             const file = input.files[0];
#             if (!file) return;
            
#             // Validate file type
#             const validExtensions = ['.csv', '.xls', '.xlsx'];
#             const fileExtension = '.' + file.name.split('.').pop().toLowerCase();
            
#             if (!validExtensions.includes(fileExtension)) {
#                 alert('❌ Invalid file type! Please upload .csv, .xls, or .xlsx file.');
#                 input.value = '';
#                 return;
#             }
            
#             // Store file
#             uploadedFormat = file;
            
#             // Show file info
#             document.getElementById('fileName').textContent = file.name;
#             document.getElementById('uploadPrompt').textContent = 'File uploaded successfully!';
#             document.getElementById('fileInfo').style.display = 'block';
            
#             // Try to extract columns (for CSV files we can preview)
#             if (fileExtension === '.csv') {
#                 const reader = new FileReader();
#                 reader.onload = function(e) {
#                     const text = e.target.result;
#                     const firstLine = text.split('\\n')[0];
#                     const columns = firstLine.split(',').map(col => col.trim().replace(/^"|"$/g, ''));
#                     extractedColumns = columns;
#                     document.getElementById('columnCount').textContent = `${columns.length}`;
#                     console.log('📋 Detected columns:', columns);
#                 };
#                 reader.readAsText(file);
#             } else {
#                 document.getElementById('columnCount').textContent = 'Processing...';
#             }
#         }
        
#         function clearFile() {
#             uploadedFormat = null;
#             extractedColumns = [];
#             document.getElementById('formatFile').value = '';
#             document.getElementById('fileInfo').style.display = 'none';
#             document.getElementById('uploadPrompt').textContent = 'Click to upload Excel/CSV';
#         }
        
#         function startScraper() {
#             const projectName = document.getElementById('projectName').value.trim();
#             const urlList = document.getElementById('urlList').value.trim();
#             const btn = document.getElementById('scrapeBtn');
#             const btnText = document.getElementById('btnText');
#             const spinner = document.getElementById('spinner');
#             const statusBox = document.getElementById('statusBox');
#             const statusText = document.getElementById('statusText');
            
#             // Validation
#             if (!projectName) {
#                 alert('❌ Please enter a project name');
#                 return;
#             }
            
#             if (!urlList) {
#                 alert('❌ Please enter at least one event website URL');
#                 return;
#             }
            
#             if (!uploadedFormat) {
#                 alert('❌ Please upload your Excel format template first!');
#                 document.querySelector('.upload-area').style.borderColor = '#dc3545';
#                 document.querySelector('.upload-area').style.background = '#fff5f5';
#                 setTimeout(() => {
#                     document.querySelector('.upload-area').style.borderColor = '#1e3c72';
#                     document.querySelector('.upload-area').style.background = '#f0f4ff';
#                 }, 2000);
#                 return;
#             }
            
#             const urls = urlList.split('\\n').filter(url => url.trim()).map(url => url.trim());
            
#             if (urls.length === 0) {
#                 alert('❌ No valid URLs found');
#                 return;
#             }
            
#             // Disable button and show loading
#             btn.disabled = true;
#             btnText.textContent = '⏳ Starting...';
#             spinner.classList.add('show');
#             statusBox.className = 'status-box loading show';
#             statusText.innerHTML = `
#                 <strong>Initializing Climate Events Scraper...</strong><br>
#                 📄 Processing format file: ${uploadedFormat.name}<br>
#                 🔗 Analyzing ${urls.length} website(s)...
#             `;
            
#             // Create FormData
#             const formData = new FormData();
#             formData.append('project_name', projectName);
#             formData.append('urls', JSON.stringify(urls));
#             formData.append('format_file', uploadedFormat);
            
#             console.log('📤 Sending request with file:', uploadedFormat.name);
            
#             // Send request
#             fetch('/trigger', {
#                 method: 'POST',
#                 body: formData
#             })
#             .then(response => response.json())
#             .then(data => {
#                 if (data.status === 'started') {
#                     statusText.innerHTML = `
#                         <strong>✅ Scraper Started!</strong><br>
#                         Processing ${urls.length} event website(s).<br>
#                         Format: ${uploadedFormat.name}<br>
#                         <small>This may take 10-30 minutes depending on data volume.</small>
#                     `;
#                     btnText.textContent = '⏳ Scraping Events...';
#                     startPolling();
#                 } else {
#                     throw new Error(data.message || 'Failed to start scraper');
#                 }
#             })
#             .catch(error => {
#                 statusBox.className = 'status-box error show';
#                 statusText.innerHTML = '<strong>❌ Error</strong><br>' + error.message;
#                 btn.disabled = false;
#                 btnText.textContent = '🚀 Start Scraping Events';
#                 spinner.classList.remove('show');
#                 console.error('Error:', error);
#             });
#         }
        
#         function startPolling() {
#             setTimeout(pollStatus, 5000);
#         }
        
#         function pollStatus() {
#             fetch('/status')
#             .then(response => response.json())
#             .then(data => {
#                 const btn = document.getElementById('scrapeBtn');
#                 const btnText = document.getElementById('btnText');
#                 const spinner = document.getElementById('spinner');
#                 const statusBox = document.getElementById('statusBox');
#                 const statusText = document.getElementById('statusText');
                
#                 if (data.running) {
#                     statusBox.className = 'status-box loading show';
#                     statusText.innerHTML = `
#                         <strong>🔄 Scraping in Progress...</strong><br>
#                         ${data.message}<br>
#                         <small>Started: ${data.last_run || 'Just now'}</small>
#                     `;
#                     btn.disabled = true;
#                     btnText.textContent = '⏳ Scraping Events...';
#                     spinner.classList.add('show');
#                     setTimeout(pollStatus, 5000);
#                 } else {
#                     statusBox.className = 'status-box success show';
#                     statusText.innerHTML = `
#                         <strong>✅ Scraping Complete!</strong><br>
#                         ${data.message}<br>
#                         ${data.events_found > 0 ? `Found ${data.events_found} events. ` : ''}
#                         Check Sheet4 in your Google Sheet for results.
#                     `;
#                     btn.disabled = false;
#                     btnText.textContent = '🚀 Start Scraping Events';
#                     spinner.classList.remove('show');
#                 }
#             })
#             .catch(error => {
#                 console.error('Polling error:', error);
#                 setTimeout(pollStatus, 5000);
#             });
#         }
        
#         // Drag and drop
#         const uploadArea = document.querySelector('.upload-area');
#         ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
#             uploadArea.addEventListener(eventName, e => {
#                 e.preventDefault();
#                 e.stopPropagation();
#             }, false);
#         });
        
#         ['dragenter', 'dragover'].forEach(eventName => {
#             uploadArea.addEventListener(eventName, () => {
#                 uploadArea.style.background = '#d4e4ff';
#                 uploadArea.style.borderColor = '#2a5298';
#             }, false);
#         });
        
#         ['dragleave', 'drop'].forEach(eventName => {
#             uploadArea.addEventListener(eventName, () => {
#                 uploadArea.style.background = '#f0f4ff';
#                 uploadArea.style.borderColor = '#1e3c72';
#             }, false);
#         });
        
#         uploadArea.addEventListener('drop', function(e) {
#             const dt = e.dataTransfer;
#             const files = dt.files;
#             document.getElementById('formatFile').files = files;
#             handleFileUpload(document.getElementById('formatFile'));
#         }, false);
#     </script>
# </body>
# </html>
# """

# def run_scraper_background():
#     """Run scraper in background"""
#     global scraper_status
    
#     print("\n" + "="*80)
#     print("🌍 STARTING CLIMATE EVENTS SCRAPER")
#     print("="*80)
    
#     scraper_status["running"] = True
#     scraper_status["last_run"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
#     scraper_status["message"] = "Initializing..."
#     scraper_status["events_found"] = 0
    
#     try:
#         env = os.environ.copy()
#         creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "credentials.json")
        
#         if not os.path.exists(creds_path):
#             for alt in ["credentials.json", "/app/credentials.json"]:
#                 if os.path.exists(alt):
#                     creds_path = alt
#                     break
        
#         env["GOOGLE_APPLICATION_CREDENTIALS"] = creds_path
#         env["SCRAPER_URLS"] = ",".join(scraper_config["urls"])
#         env["SCRAPER_COLUMNS"] = ",".join(scraper_config["format_columns"])
#         env["SCRAPER_PROJECT_NAME"] = scraper_config.get("project_name", "Climate Events")
#         env["SCRAPER_SHEET_NAME"] = scraper_config["sheet_name"]
        
#         print(f"🔑 Credentials: {creds_path}")
#         print(f"🔗 URLs: {len(scraper_config['urls'])}")
#         print(f"📋 Columns: {len(scraper_config['format_columns'])}")
#         print("-"*80)
        
#         scraper_status["message"] = f"Scraping {len(scraper_config['urls'])} websites..."
        
#         result = subprocess.run(
#             ["scrapy", "crawl", "climate_events"],
#             capture_output=True,
#             text=True,
#             env=env,
#             timeout=1800,
#             check=True
#         )
        
#         print("="*80)
#         print("✅ SCRAPER COMPLETED")
#         print("="*80)
        
#         scraper_status["message"] = "Completed successfully!"
        
#     except subprocess.TimeoutExpired:
#         print("⏱️ Timeout after 30 minutes")
#         scraper_status["message"] = "Timed out"
#     except Exception as e:
#         print(f"❌ Error: {e}")
#         scraper_status["message"] = f"Error: {str(e)[:200]}"
#     finally:
#         scraper_status["running"] = False
#         print("="*80 + "\n")

# @app.route("/")
# def index():
#     return render_template_string(HTML_TEMPLATE)

# @app.route("/trigger", methods=["POST"])
# def trigger():
#     global scraper_status, scraper_config
    
#     if scraper_status["running"]:
#         return jsonify({"status": "already_running", "message": "Scraper is already running"}), 400
    
#     try:
#         project_name = request.form.get('project_name', 'Climate_Events')
#         urls_json = request.form.get('urls')
#         format_file = request.files.get('format_file')
        
#         print(f"\n{'='*80}")
#         print(f"📥 RECEIVED SCRAPING REQUEST")
#         print(f"{'='*80}")
#         print(f"Project: {project_name}")
#         print(f"URLs JSON: {urls_json}")
#         print(f"Format file: {format_file.filename if format_file else 'NONE'}")
#         print(f"{'='*80}\n")
        
#         if not format_file:
#             return jsonify({"status": "error", "message": "No Excel file uploaded"}), 400
        
#         import json
#         urls = json.loads(urls_json)
#         scraper_config["urls"] = urls
#         scraper_config["project_name"] = project_name
        
#         filename = format_file.filename.lower()
#         print(f"📄 Processing file: {filename}")
        
#         if filename.endswith('.csv'):
#             try:
#                 content = format_file.read().decode('utf-8')
#             except:
#                 format_file.seek(0)
#                 try:
#                     content = format_file.read().decode('latin-1')
#                 except:
#                     format_file.seek(0)
#                     content = format_file.read().decode('utf-8', errors='ignore')
            
#             csv_reader = csv.reader(io.StringIO(content))
#             headers = next(csv_reader)
#             scraper_config["format_columns"] = headers
#             print(f"✅ CSV: Extracted {len(headers)} columns")
#             print(f"   Columns: {', '.join(headers[:10])}...")
            
#         elif filename.endswith(('.xlsx', '.xls')):
#             try:
#                 format_file.seek(0)
#                 temp_path = '/tmp/format_template.xlsx'
#                 format_file.save(temp_path)
                
#                 print(f"💾 Saved to: {temp_path}")
#                 print(f"📊 File size: {os.path.getsize(temp_path)} bytes")
                
#                 # Try with openpyxl first
#                 try:
#                     df = pd.read_excel(temp_path, nrows=1, engine='openpyxl')
#                 except:
#                     # Fallback to xlrd for older .xls files
#                     df = pd.read_excel(temp_path, nrows=1, engine='xlrd')
                
#                 headers = df.columns.tolist()
#                 scraper_config["format_columns"] = headers
                
#                 if os.path.exists(temp_path):
#                     os.remove(temp_path)
                
#                 print(f"✅ Excel: Extracted {len(headers)} columns")
#                 print(f"   Columns: {', '.join(str(h) for h in headers[:10])}...")
                
#             except Exception as e:
#                 print(f"❌ Excel processing error: {e}")
#                 import traceback
#                 traceback.print_exc()
#                 if os.path.exists('/tmp/format_template.xlsx'):
#                     os.remove('/tmp/format_template.xlsx')
#                 return jsonify({
#                     "status": "error", 
#                     "message": f"Failed to read Excel file: {str(e)}"
#                 }), 400
#         else:
#             return jsonify({
#                 "status": "error", 
#                 "message": "Please upload a CSV or Excel file (.csv, .xlsx, .xls)"
#             }), 400
        
#         if not scraper_config["format_columns"]:
#             return jsonify({
#                 "status": "error", 
#                 "message": "No columns found in uploaded file"
#             }), 400
        
#         print(f"\n✅ Configuration ready:")
#         print(f"   - URLs: {len(urls)}")
#         print(f"   - Columns: {len(scraper_config['format_columns'])}")
#         print(f"\n🚀 Starting scraper thread...\n")
        
#         thread = threading.Thread(target=run_scraper_background, daemon=True)
#         thread.start()
        
#         return jsonify({
#             "status": "started", 
#             "message": f"Scraper started for {len(urls)} URLs with {len(scraper_config['format_columns'])} columns"
#         }), 200
        
#     except Exception as e:
#         print(f"\n❌ TRIGGER ERROR: {e}")
#         import traceback
#         traceback.print_exc()
#         return jsonify({"status": "error", "message": str(e)}), 500

# @app.route("/status")
# def status():
#     return jsonify(scraper_status)

# @app.route("/health")
# def health():
#     return jsonify({"status": "healthy"}), 200

# if __name__ == "__main__":
#     port = int(os.environ.get("PORT", 8080))
#     print(f"🌐 Climate Events Scraper starting on port {port}")
#     app.run(host="0.0.0.0", port=port, debug=False)




