# -*- coding: utf-8 -*-
import scrapy

class SessionItem(scrapy.Item):
    url = scrapy.Field()
    fh = scrapy.Field()
    lang = scrapy.Field()
    user = scrapy.Field()
    session = scrapy.Field()
