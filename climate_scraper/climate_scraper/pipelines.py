import gspread
from google.oauth2.service_account import Credentials
import os
from datetime import datetime
import pytz
import time

class ClimateEventsPipeline:
    def __init__(self):
        creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        if not creds_path:
            raise ValueError("❌ GOOGLE_APPLICATION_CREDENTIALS not set")
        
        if not os.path.exists(creds_path):
            raise ValueError(f"❌ Credentials file not found: {creds_path}")

        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        
        print(f"🔐 Loading credentials from: {creds_path}")
        self.creds = Credentials.from_service_account_file(creds_path, scopes=scopes)
        self.client = gspread.authorize(self.creds)
        
        # Your Google Sheet
        self.spreadsheet_id = "1tDFA7DIRm0b-9mbZby2lNyfgYJtGXSjOwl5ezN3CeME"
        self.sheet_name = os.getenv("SCRAPER_SHEET_NAME", "Sheet4")
        
        print(f"📊 Connecting to spreadsheet: {self.spreadsheet_id}")
        print(f"📄 Sheet name: {self.sheet_name}")
        
        try:
            spreadsheet = self.client.open_by_key(self.spreadsheet_id)
            self.sheet = spreadsheet.worksheet(self.sheet_name)
            print(f"✅ Connected to existing sheet: {self.sheet_name}")
        except gspread.exceptions.WorksheetNotFound:
            print(f"⚠️ Sheet '{self.sheet_name}' not found, creating it...")
            spreadsheet = self.client.open_by_key(self.spreadsheet_id)
            self.sheet = spreadsheet.add_worksheet(
                title=self.sheet_name,
                rows="5000",
                cols="50"
            )
            print(f"✅ Created new sheet: {self.sheet_name}")
        except Exception as e:
            print(f"❌ Error connecting to sheet: {e}")
            raise
        
        self.ist = pytz.timezone('Asia/Kolkata')
        self.session_start = datetime.now(self.ist).strftime("%Y-%m-%d %H:%M:%S")
        self.items_scraped = 0
        
        # Get format columns
        self.format_columns = self.get_format_columns()
        print(f"📋 Format columns ({len(self.format_columns)}): {self.format_columns[:5]}...")
        
        # Initialize headers
        self.initialize_headers()
    
    def get_format_columns(self):
        """Get format columns from environment"""
        columns_str = os.getenv("SCRAPER_COLUMNS", "")
        if columns_str:
            columns = [col.strip() for col in columns_str.split(",") if col.strip()]
            return columns
        return ["Event Name", "Date", "Location", "Description"]
    
    def initialize_headers(self):
        """Add headers if sheet is empty"""
        try:
            existing = self.sheet.row_values(1)
            
            if not existing or not existing[0]:
                # Sheet is empty, add headers
                headers = ["Sr. No.", "Scraped At"] + self.format_columns + ["Source URL", "Status"]
                self.sheet.append_row(headers)
                
                # Format header row
                end_col = self.get_column_letter(len(headers))
                self.sheet.format(f'A1:{end_col}1', {
                    "backgroundColor": {"red": 0.1, "green": 0.3, "blue": 0.6},
                    "textFormat": {
                        "bold": True,
                        "foregroundColor": {"red": 1, "green": 1, "blue": 1},
                        "fontSize": 11
                    },
                    "horizontalAlignment": "CENTER"
                })
                print(f"✅ Created headers with {len(headers)} columns")
            else:
                print(f"✅ Headers already exist, skipping initialization")
        except Exception as e:
            print(f"❌ Header initialization error: {e}")
    
    def get_column_letter(self, n):
        """Convert column number to letter (1=A, 27=AA, etc.)"""
        result = ""
        while n > 0:
            n -= 1
            result = chr(65 + (n % 26)) + result
            n //= 26
        return result
    
    def process_item(self, item, spider):
        """Write each event to Google Sheets"""
        
        try:
            # Get current row count (with retry)
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    all_values = self.sheet.get_all_values()
                    sr_no = len([row for row in all_values if row and any(row)])
                    break
                except Exception as e:
                    if attempt < max_retries - 1:
                        spider.logger.warning(f"⚠️ Retry {attempt + 1}/{max_retries} getting row count: {e}")
                        time.sleep(2)
                    else:
                        raise
            
            timestamp = datetime.now(self.ist).strftime("%Y-%m-%d %H:%M:%S")
            
            # Build row: Sr.No + Timestamp + Format Columns + Source + Status
            row = [
                sr_no,  # Serial number
                timestamp,
            ]
            
            # Add data for each format column
            for col in self.format_columns:
                value = item.get(col, "N/A")
                
                # Handle None values
                if value is None:
                    value = "N/A"
                
                # Convert to string and limit length
                value_str = str(value)
                if len(value_str) > 50000:  # Google Sheets cell limit
                    value_str = value_str[:50000] + "... [truncated]"
                
                row.append(value_str)
            
            # Add source URL and status
            row.append(str(item.get("source_url", "N/A")))
            row.append(str(item.get("scraping_status", "Success")))
            
            # Log
            event_name = item.get(self.format_columns[0] if self.format_columns else "Event Name", "N/A")
            spider.logger.info("=" * 70)
            spider.logger.info(f"📝 Writing to Sheet4:")
            spider.logger.info(f"  Event: {str(event_name)[:60]}")
            spider.logger.info(f"  Row: {sr_no}")
            spider.logger.info("=" * 70)
            
            # Append row with retry logic
            for attempt in range(max_retries):
                try:
                    self.sheet.append_row(row, value_input_option='USER_ENTERED')
                    break
                except Exception as e:
                    if attempt < max_retries - 1:
                        spider.logger.warning(f"⚠️ Retry {attempt + 1}/{max_retries} appending row: {e}")
                        time.sleep(2)
                    else:
                        raise
            
            # Get row number
            row_number = len(self.sheet.get_all_values())
            
            # Format row (only highlight failures)
            try:
                end_col = self.get_column_letter(len(row))
                
                # Highlight failed scrapes
                if item.get("scraping_status") != "Success":
                    self.sheet.format(f'A{row_number}:{end_col}{row_number}', {
                        "backgroundColor": {"red": 1, "green": 0.85, "blue": 0.85}
                    })
                
                # Text wrapping for description-like columns
                for i, col in enumerate(self.format_columns, start=3):
                    col_lower = col.lower()
                    if any(word in col_lower for word in ['description', 'agenda', 'theme', 'goals', 'objective']):
                        col_letter = self.get_column_letter(i)
                        self.sheet.format(f'{col_letter}{row_number}', {
                            "wrapStrategy": "WRAP",
                            "verticalAlignment": "TOP"
                        })
            except Exception as e:
                spider.logger.warning(f"⚠️ Formatting error (non-critical): {e}")
            
            self.items_scraped += 1
            spider.logger.info(f"✅ Successfully added to row {row_number}")
            
        except Exception as e:
            spider.logger.error(f"❌ Pipeline error: {e}")
            import traceback
            spider.logger.error(f"Traceback:\n{traceback.format_exc()}")
            
            # Don't raise - allow scraping to continue
            spider.logger.warning(f"⚠️ Continuing despite error...")
        
        return item
    
    def close_spider(self, spider):
        """Add separator when scraping completes"""
        try:
            session_end = datetime.now(self.ist).strftime("%Y-%m-%d %H:%M:%S")
            session_date = datetime.now(self.ist).strftime("%Y-%m-%d")
            
            # Create separator row
            num_cols = 2 + len(self.format_columns) + 2
            
            separator_text = f"═══ SESSION COMPLETED: {session_date} ═══"
            summary = f"Started: {self.session_start} | Ended: {session_end} | Events: {self.items_scraped}"
            
            separator_row = [separator_text, summary] + [""] * (num_cols - 2)
            
            self.sheet.append_row(separator_row, value_input_option='USER_ENTERED')
            row_number = len(self.sheet.get_all_values())
            
            # Format separator
            end_col = self.get_column_letter(num_cols)
            self.sheet.format(f'A{row_number}:{end_col}{row_number}', {
                "backgroundColor": {"red": 0.2, "green": 0.6, "blue": 0.9},
                "textFormat": {
                    "bold": True,
                    "foregroundColor": {"red": 1, "green": 1, "blue": 1},
                    "fontSize": 11
                },
                "horizontalAlignment": "CENTER"
            })
            
            self.sheet.merge_cells(f'A{row_number}:{end_col}{row_number}')
            
            spider.logger.info("=" * 80)
            spider.logger.info(f"✅ Added session completion marker")
            spider.logger.info(f"📊 Total events scraped in this session: {self.items_scraped}")
            spider.logger.info("=" * 80)
            
        except Exception as e:
            spider.logger.error(f"❌ Error adding completion marker: {e}")