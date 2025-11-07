FROM python:3.9-slim
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir -r requirements.txt
RUN playwright install-deps
RUN useradd -m scraper_user
RUN playwright install chromium
USER scraper_user
ENV PORT=8080
EXPOSE 8080
CMD ["python", "main.py"]