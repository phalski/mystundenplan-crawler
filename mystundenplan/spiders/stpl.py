# -*- coding: utf-8 -*-
import scrapy
from scrapy import Selector
from scrapy.exceptions import CloseSpider
from scrapy.loader.processors import SelectJmes, Compose, MapCompose

import json
import jmespath
from mystundenplan.items import SessionItem
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from w3lib.url import url_query_cleaner


class StplSpider(scrapy.Spider):
    VALID_SESSION_LEN = 40

    name = 'stpl'
    allowed_domains = ['www3.primuss.de']

    def __init__(self, login_url=None, tenant=None, username=None, password=None, *args, **kwargs):
        super(StplSpider, self).__init__(*args, **kwargs)

        if not (login_url and tenant and username and password):
            self.logger.critical('Spider opened with missing arguments')
            raise ValueError('Spider opened with missing arguments')

        self.login_url = login_url
        self.tenant = tenant
        self.username = username
        self.password = password

        self.session = None

    def start_requests(self):
        request = scrapy.FormRequest(self.login_url, formdata={
            'user': self.username,
            'pwd': self.password,
            'mode': 'login',
            'FH': self.tenant
        }, callback=self.scrape_session)
        self.logger.debug(
            "Prepared login request for %s:%s@%s at %s" % (self.username, self.password, self.tenant, self.login_url))
        return [request]

    def cbsem_request(self):
        if not self.session:
            raise CloseSpider("Can't create request without active session")

        return self.newRequest(self.session['url'],
                               {
                                   'FH': self.session['fh']
                               },
                               {
                                   'mode': 'cbsem',
                                   'Session': self.session['session'],
                                   'User': self.session['user']
                               },
                               self.scrape_cbsem)

    def index_requests(self, sems):
        if not self.session:
            raise CloseSpider("Can't create request without active session")

        requests = []
        for sem in sems:
            requests.append(self.newRequest(self.session['url'],
                                            {
                                                'FH': self.session['fh']
                                            },
                                            {
                                                'User': self.session['user'],
                                                'Session': self.session['session'],
                                                'sem': sem
                                            },
                                            self.scrape_index))

        return requests

    def cbgrid_raum_requests(self, sem, raums):
        if not self.session:
            raise CloseSpider("Can't create request without active session")

        requests = []
        for raum in raums:
            requests.append(self.newRequest(self.session['url'],
                                            {
                                                'FH': self.session['fh'],
                                                'sem': sem,
                                                'raum': raum
                                            },
                                            {
                                                'mode': raum,
                                                'Session': self.session['session'],
                                                'User': self.session['user']
                                            },
                                            self.scrape_index))

        return requests

    def calendar_raum_requests(self, sem, raums):
        if not self.session:
            raise CloseSpider("Can't create request without active session")

        requests = []
        for raum in raums:
            requests.append(self.newRequest(self.session['url'],
                                            {
                                                'FH': self.session['fh'],
                                                'sem': sem,
                                                'method': 'list'
                                            },
                                            {
                                                'Session': self.session['session'],
                                                'User': self.session['user'],
                                                'mode': 'calendar',
                                                'raum': raum
                                            },
                                            self.scrape_index))

        return requests

    def scrape_session(self, response):
        url_parsed = urlparse(response.url)
        query_parsed = parse_qs(url_parsed.query)

        try:
            session = SessionItem(
                url=url_query_cleaner(response.url),
                fh=query_parsed['FH'][0],
                lang=query_parsed['Lang'][0],
                user=query_parsed['User'][0],
                session=query_parsed['Session'][0],
            )

            if not (session['url'] and not session['url'] == self.login_url and
                        session['fh'] and
                        session['lang'] and
                        session['user'] and
                        session['session'] and StplSpider.VALID_SESSION_LEN == len(session['session'])
                    ):
                raise CloseSpider("No valid session found. Please check your credentials!")

            self.session = session
            self.logger.info("Created session %s" % dict(self.session))

        except KeyError:
            raise CloseSpider("No valid session found. Please check your credentials!")

        return self.parse(response)

    def parse(self, response):
        return [self.cbsem_request()]

    def scrape_cbsem(self, response):
        return self.index_requests(jmespath.search('[].id', json.loads(response.text)))

    def scrape_index(self, response):
        selector = Selector(text=response.body)
        raums = selector.css("#cbraum > option:not(:first-child)").css("::attr(value)").extract()
        requests = []
        requests.extend(self.cbgrid_raum_requests('33', raums))
        requests.extend(self.calendar_raum_requests('33', raums))
        return requests

    def newRequest(self, url, querydata, formdata, callback):
        url_parsed = urlparse(url)
        url_parsed = url_parsed._replace(query=urlencode(querydata))
        return scrapy.FormRequest(urlunparse(url_parsed), formdata=formdata, callback=callback)
