# Use an official Python runtime as a parent image
FROM python:3.9-slim

# Set the working directory in the container
WORKDIR /app

# Copy only requirements first for caching
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Then copy rest of project
COPY . .
# Install system dependencies required by Playwright browsers
RUN playwright install-deps

# Create and switch to a non-root user for security
RUN useradd -m scrapy_user
USER scrapy_user

# Install the browser itself as the non-root user
RUN playwright install chromium

# --- *** THE NEW COMMAND *** ---
# Set the default command to run the Flask web server
CMD ["scrapy", "crawl", "climate_events"]

