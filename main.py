from flask import Flask, render_template_string, request, jsonify
import subprocess
import os
import threading
import time
from datetime import datetime
import csv
import io
import pandas as pd

app = Flask(__name__)

# Track scraper status
scraper_status = {
    "running": False,
    "last_run": None,
    "message": "Ready",
    "events_found": 0
}

# Store configuration
scraper_config = {
    "urls": [],
    "format_columns": [],
    "sheet_url": "https://docs.google.com/spreadsheets/d/1tDFA7DIRm0b-9mbZby2lNyfgYJtGXSjOwl5ezN3CeME/edit",
    "sheet_name": "Sheet4"
}

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Climate Events Scraper</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { 
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #1e3c72 0%, #2a5298 50%, #7e22ce 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }
        .container { 
            background: white;
            padding: 40px;
            border-radius: 20px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            max-width: 800px;
            width: 100%;
        }
        h1 { 
            font-size: 36px;
            color: #1e3c72;
            margin-bottom: 10px;
            font-weight: 700;
            text-align: center;
        }
        .subtitle {
            color: #666;
            margin-bottom: 30px;
            font-size: 16px;
            text-align: center;
        }
        
        .section {
            background: #f8f9fa;
            border-radius: 12px;
            padding: 20px;
            margin: 20px 0;
            border-left: 4px solid #1e3c72;
        }
        
        .section-title {
            font-size: 18px;
            font-weight: 600;
            color: #333;
            margin-bottom: 12px;
            display: flex;
            align-items: center;
        }
        
        .section-title .emoji {
            font-size: 24px;
            margin-right: 10px;
        }
        
        label {
            display: block;
            margin-bottom: 8px;
            color: #555;
            font-size: 14px;
            font-weight: 500;
        }
        
        input[type="text"], textarea, input[type="file"] {
            width: 100%;
            padding: 12px;
            border: 2px solid #e0e0e0;
            border-radius: 8px;
            font-size: 14px;
            transition: border-color 0.3s;
            font-family: inherit;
        }
        
        input[type="text"]:focus, textarea:focus {
            outline: none;
            border-color: #1e3c72;
        }
        
        textarea {
            min-height: 120px;
            resize: vertical;
        }
        
        .help-text {
            font-size: 12px;
            color: #888;
            margin-top: 5px;
        }
        
        .btn {
            background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%);
            color: white;
            border: none;
            padding: 16px 40px;
            border-radius: 50px;
            font-size: 18px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s ease;
            box-shadow: 0 8px 20px rgba(30, 60, 114, 0.4);
            margin-top: 20px;
            width: 100%;
        }
        .btn:hover:not(:disabled) {
            transform: translateY(-3px);
            box-shadow: 0 12px 30px rgba(30, 60, 114, 0.6);
        }
        .btn:disabled {
            background: #ccc;
            cursor: not-allowed;
            transform: none;
            box-shadow: none;
        }
        
        .status-box {
            margin-top: 30px;
            padding: 20px;
            border-radius: 12px;
            font-size: 15px;
            display: none;
            animation: fadeIn 0.5s;
        }
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(-10px); }
            to { opacity: 1; transform: translateY(0); }
        }
        .status-box.show { display: block; }
        .status-box.loading {
            background: #fff3cd;
            border: 2px solid #ffc107;
            color: #856404;
        }
        .status-box.success {
            background: #d4edda;
            border: 2px solid #28a745;
            color: #155724;
        }
        .status-box.error {
            background: #f8d7da;
            border: 2px solid #dc3545;
            color: #721c24;
        }
        
        .spinner {
            border: 4px solid #f3f3f3;
            border-top: 4px solid #1e3c72;
            border-radius: 50%;
            width: 50px;
            height: 50px;
            animation: spin 1s linear infinite;
            margin: 20px auto;
            display: none;
        }
        .spinner.show { display: block; }
        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
        
        .sheet-link {
            display: inline-block;
            margin-top: 20px;
            color: #1e3c72;
            text-decoration: none;
            font-size: 14px;
            transition: color 0.3s;
            text-align: center;
            width: 100%;
        }
        .sheet-link:hover { color: #7e22ce; text-decoration: underline; }
        
        .upload-area {
            border: 2px dashed #1e3c72;
            border-radius: 8px;
            padding: 30px;
            text-align: center;
            background: #f0f4ff;
            cursor: pointer;
            transition: all 0.3s;
        }
        .upload-area:hover {
            background: #e3ecff;
            border-color: #2a5298;
        }
        
        .preset-urls {
            background: #e8f5e9;
            padding: 15px;
            border-radius: 8px;
            margin-top: 10px;
        }
        
        .preset-urls h4 {
            font-size: 14px;
            color: #2e7d32;
            margin-bottom: 8px;
        }
        
        .preset-urls ul {
            list-style: none;
            font-size: 12px;
            color: #1b5e20;
        }
        
        .preset-urls li {
            margin: 5px 0;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🌍 Climate Events Scraper</h1>
        <p class="subtitle">Automated Climate & Sustainability Events Data Collection</p>
        
        <!-- Section 1: Project Name -->
        <div class="section">
            <div class="section-title">
                <span class="emoji">📝</span>
                Project Name
            </div>
            <input type="text" id="projectName" placeholder="e.g., Climate Events 2025" value="Climate Events Collection">
            <p class="help-text">Name your scraping project</p>
        </div>
        
        <!-- Section 2: Event Websites -->
        <div class="section">
            <div class="section-title">
                <span class="emoji">🔗</span>
                Event Websites to Scrape
            </div>
            <textarea id="urlList" placeholder="Enter event website URLs (one per line):
https://www.eventbrite.com
https://unfccc.int/calendar/events-list
https://www.un.org/en/climatechange/events
https://thinklandscape.globallandscapesforum.org"></textarea>
            <p class="help-text">Paste URLs of event aggregator websites, one per line</p>
            
            <div class="preset-urls">
                <h4>🌟 Suggested Climate Event Websites:</h4>
                <ul>
                    <li>✓ Eventbrite (climate + sustainability events)</li>
                    <li>✓ UNFCCC Calendar</li>
                    <li>✓ UN Climate Change Events</li>
                    <li>✓ Global Landscapes Forum</li>
                    <li>✓ Climate Tracker Events</li>
                </ul>
            </div>
        </div>
        
        <!-- Section 3: Excel Format -->
        <div class="section">
            <div class="section-title">
                <span class="emoji">📋</span>
                Excel Format Template
            </div>
            <label for="formatFile">Upload your Excel template with column headers:</label>
            <div class="upload-area" onclick="document.getElementById('formatFile').click()">
                <p style="font-size: 48px; margin-bottom: 10px;">📄</p>
                <p style="font-weight: 600; margin-bottom: 5px;">Click to upload Excel/CSV</p>
                <p class="help-text">Accepts .xlsx, .xls, or .csv files</p>
            </div>
            <input type="file" id="formatFile" accept=".csv,.xlsx,.xls" style="display: none;" onchange="handleFileUpload(this)">
            <p id="fileName" style="margin-top: 10px; color: #1e3c72; font-weight: 600;"></p>
            
            <div class="help-text" style="margin-top: 10px;">
                Expected columns: Event Name, Date, Location, Description, Organizer, Type, Topic, etc.
            </div>
        </div>
        
        <!-- Section 4: Destination -->
        <div class="section">
            <div class="section-title">
                <span class="emoji">📊</span>
                Destination Google Sheet
            </div>
            <input type="text" id="sheetUrl" value="https://docs.google.com/spreadsheets/d/1tDFA7DIRm0b-9mbZby2lNyfgYJtGXSjOwl5ezN3CeME/edit" readonly>
            <p class="help-text">Sheet: Sheet4 | Data will be appended to this sheet</p>
        </div>
        
        <button class="btn" id="scrapeBtn" onclick="startScraper()">
            <span id="btnText">🚀 Start Scraping Events</span>
        </button>
        
        <div class="spinner" id="spinner"></div>
        
        <div class="status-box" id="statusBox">
            <div id="statusText"></div>
        </div>
        
        <a href="https://docs.google.com/spreadsheets/d/1tDFA7DIRm0b-9mbZby2lNyfgYJtGXSjOwl5ezN3CeME/edit?gid=0#gid=0" target="_blank" class="sheet-link">
            📊 View Results in Google Sheet (Sheet4)
        </a>
    </div>
    
    <script>
        let uploadedFormat = null;
        
        function handleFileUpload(input) {
            const file = input.files[0];
            if (file) {
                document.getElementById('fileName').textContent = `✅ Uploaded: ${file.name}`;
                uploadedFormat = file;
            }
        }
        
        function startScraper() {
            const projectName = document.getElementById('projectName').value.trim();
            const urlList = document.getElementById('urlList').value.trim();
            const btn = document.getElementById('scrapeBtn');
            const btnText = document.getElementById('btnText');
            const spinner = document.getElementById('spinner');
            const statusBox = document.getElementById('statusBox');
            const statusText = document.getElementById('statusText');
            
            if (!projectName) {
                alert('Please enter a project name');
                return;
            }
            
            if (!urlList) {
                alert('Please enter at least one event website URL');
                return;
            }
            
            if (!uploadedFormat) {
                alert('Please upload your Excel format template');
                return;
            }
            
            const urls = urlList.split('\n').filter(url => url.trim()).map(url => url.trim());
            
            if (urls.length === 0) {
                alert('No valid URLs found');
                return;
            }
            
            btn.disabled = true;
            btnText.textContent = '⏳ Starting...';
            spinner.classList.add('show');
            statusBox.className = 'status-box loading show';
            statusText.innerHTML = '<strong>Initializing Climate Events Scraper...</strong><br>Analyzing Excel format and preparing extraction...';
            
            const formData = new FormData();
            formData.append('project_name', projectName);
            formData.append('urls', JSON.stringify(urls));
            formData.append('format_file', uploadedFormat);
            
            fetch('/trigger', {
                method: 'POST',
                body: formData
            })
            .then(response => response.json())
            .then(data => {
                if (data.status === 'started') {
                    statusText.innerHTML = `<strong>✅ Scraper Started!</strong><br>Processing ${urls.length} event website(s). This may take 10-30 minutes depending on data volume.`;
                    btnText.textContent = '⏳ Scraping Events...';
                    startPolling();
                } else {
                    throw new Error(data.message || 'Failed to start scraper');
                }
            })
            .catch(error => {
                statusBox.className = 'status-box error show';
                statusText.innerHTML = '<strong>❌ Error</strong><br>' + error.message;
                btn.disabled = false;
                btnText.textContent = '🚀 Start Scraping Events';
                spinner.classList.remove('show');
            });
        }
        
        function startPolling() {
            setTimeout(pollStatus, 5000);
        }
        
        function pollStatus() {
            fetch('/status')
            .then(response => response.json())
            .then(data => {
                const btn = document.getElementById('scrapeBtn');
                const btnText = document.getElementById('btnText');
                const spinner = document.getElementById('spinner');
                const statusBox = document.getElementById('statusBox');
                const statusText = document.getElementById('statusText');
                
                if (data.running) {
                    statusBox.className = 'status-box loading show';
                    statusText.innerHTML = `
                        <strong>🔄 Scraping in Progress...</strong><br>
                        ${data.message}<br>
                        <small>Started: ${data.last_run || 'Just now'}</small>
                    `;
                    btn.disabled = true;
                    btnText.textContent = '⏳ Scraping Events...';
                    spinner.classList.add('show');
                    setTimeout(pollStatus, 5000);
                } else {
                    statusBox.className = 'status-box success show';
                    statusText.innerHTML = `
                        <strong>✅ Scraping Complete!</strong><br>
                        ${data.message}<br>
                        ${data.events_found > 0 ? `Found ${data.events_found} events. ` : ''}
                        Check Sheet4 in your Google Sheet for results.
                    `;
                    btn.disabled = false;
                    btnText.textContent = '🚀 Start Scraping Events';
                    spinner.classList.remove('show');
                }
            })
            .catch(error => {
                console.error('Polling error:', error);
                setTimeout(pollStatus, 5000);
            });
        }
        
        // Drag and drop
        const uploadArea = document.querySelector('.upload-area');
        ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
            uploadArea.addEventListener(eventName, e => {
                e.preventDefault();
                e.stopPropagation();
            }, false);
        });
        
        ['dragenter', 'dragover'].forEach(eventName => {
            uploadArea.addEventListener(eventName, () => {
                uploadArea.style.background = '#d4e4ff';
                uploadArea.style.borderColor = '#2a5298';
            }, false);
        });
        
        ['dragleave', 'drop'].forEach(eventName => {
            uploadArea.addEventListener(eventName, () => {
                uploadArea.style.background = '#f0f4ff';
                uploadArea.style.borderColor = '#1e3c72';
            }, false);
        });
        
        uploadArea.addEventListener('drop', function(e) {
            const dt = e.dataTransfer;
            const files = dt.files;
            document.getElementById('formatFile').files = files;
            handleFileUpload(document.getElementById('formatFile'));
        }, false);
    </script>
</body>
</html>
"""

def run_scraper_background():
    """Run scraper in background"""
    global scraper_status
    
    print("\n" + "="*80)
    print("🌍 STARTING CLIMATE EVENTS SCRAPER")
    print("="*80)
    
    scraper_status["running"] = True
    scraper_status["last_run"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    scraper_status["message"] = "Initializing..."
    scraper_status["events_found"] = 0
    
    try:
        env = os.environ.copy()
        creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "credentials.json")
        
        if not os.path.exists(creds_path):
            for alt in ["credentials.json", "/app/credentials.json"]:
                if os.path.exists(alt):
                    creds_path = alt
                    break
        
        env["GOOGLE_APPLICATION_CREDENTIALS"] = creds_path
        env["SCRAPER_URLS"] = ",".join(scraper_config["urls"])
        env["SCRAPER_COLUMNS"] = ",".join(scraper_config["format_columns"])
        env["SCRAPER_PROJECT_NAME"] = scraper_config.get("project_name", "Climate Events")
        env["SCRAPER_SHEET_NAME"] = scraper_config["sheet_name"]
        
        print(f"🔑 Credentials: {creds_path}")
        print(f"🔗 URLs: {len(scraper_config['urls'])}")
        print(f"📋 Columns: {len(scraper_config['format_columns'])}")
        print("-"*80)
        
        scraper_status["message"] = f"Scraping {len(scraper_config['urls'])} websites..."
        
        result = subprocess.run(
            ["scrapy", "crawl", "climate_events"],
            capture_output=True,
            text=True,
            env=env,
            timeout=1800,  # 30 minutes
            check=True
        )
        
        print("="*80)
        print("✅ SCRAPER COMPLETED")
        print("="*80)
        
        scraper_status["message"] = "Completed successfully!"
        
    except subprocess.TimeoutExpired:
        print("⏱️ Timeout after 30 minutes")
        scraper_status["message"] = "Timed out"
    except Exception as e:
        print(f"❌ Error: {e}")
        scraper_status["message"] = f"Error: {str(e)[:200]}"
    finally:
        scraper_status["running"] = False
        print("="*80 + "\n")

@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route("/trigger", methods=["POST"])
def trigger():
    global scraper_status, scraper_config
    
    if scraper_status["running"]:
        return jsonify({"status": "already_running", "message": "Scraper is running"}), 400
    
    try:
        project_name = request.form.get('project_name', 'Climate_Events')
        urls_json = request.form.get('urls')
        format_file = request.files.get('format_file')
        
        import json
        urls = json.loads(urls_json)
        scraper_config["urls"] = urls
        scraper_config["project_name"] = project_name
        
        if format_file:
            filename = format_file.filename.lower()
            
            if filename.endswith('.csv'):
                try:
                    content = format_file.read().decode('utf-8')
                except:
                    format_file.seek(0)
                    try:
                        content = format_file.read().decode('latin-1')
                    except:
                        format_file.seek(0)
                        content = format_file.read().decode('utf-8', errors='ignore')
                
                csv_reader = csv.reader(io.StringIO(content))
                headers = next(csv_reader)
                scraper_config["format_columns"] = headers
                
            elif filename.endswith(('.xlsx', '.xls')):
                try:
                    format_file.seek(0)
                    temp_path = '/tmp/format_template.xlsx'
                    format_file.save(temp_path)
                    
                    df = pd.read_excel(temp_path, nrows=1, engine='openpyxl')
                    headers = df.columns.tolist()
                    scraper_config["format_columns"] = headers
                    
                    if os.path.exists(temp_path):
                        os.remove(temp_path)
                    
                    print(f"✅ Extracted {len(headers)} columns from Excel")
                except Exception as e:
                    print(f"❌ Excel error: {e}")
                    if os.path.exists('/tmp/format_template.xlsx'):
                        os.remove('/tmp/format_template.xlsx')
                    return jsonify({"status": "error", "message": str(e)}), 400
            else:
                return jsonify({"status": "error", "message": "Upload CSV or Excel"}), 400
        
        print(f"📋 Columns: {scraper_config['format_columns'][:5]}...")
        
        thread = threading.Thread(target=run_scraper_background, daemon=True)
        thread.start()
        
        return jsonify({"status": "started", "message": f"Started for {len(urls)} URLs"}), 200
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
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