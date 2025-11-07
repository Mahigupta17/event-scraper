import scrapy

class ClimateEventItem(scrapy.Item):
    """Dynamic item that can hold any fields based on Excel template"""
    # This will be populated dynamically based on user's Excel columns
    pass