# -*- coding: utf-8 -*-
import scrapy


class StplSpider(scrapy.Spider):
    name = 'stpl'
    allowed_domains = ['wwww3.primuss.de']
    start_urls = ['http://wwww3.primuss.de/']

    def parse(self, response):
        pass
