# -*- coding: utf-8 -*-
import scrapy


class Download(scrapy.Item):
    meta = scrapy.Field()
    data = scrapy.Field()