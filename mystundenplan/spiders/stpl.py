# -*- coding: utf-8 -*-
import scrapy
from scrapy.exceptions import CloseSpider
from mystundenplan.items import SessionItem
from urllib.parse import urlparse, parse_qs
from w3lib.url import url_query_cleaner


class StplSpider(scrapy.Spider):
    name = 'stpl'
    allowed_domains = ['wwww3.primuss.de']

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

    def scrape_session(self, response):
        parsed_url = urlparse(response.url)
        parsed_query = parse_qs(parsed_url.query)

        try:
            session = SessionItem(
                url=url_query_cleaner(response.url),
                fh=parsed_query['FH'][0],
                lang=parsed_query['Lang'][0],
                user=parsed_query['User'][0],
                session=parsed_query['Session'][0],
            )

            if not (session['url'] and not session['url'] == self.login_url and
                    session['fh'] and
                    session['lang'] and
                    session['user'] and
                    session['session'] and 40 == len(session['session'])
                    ):
                raise CloseSpider("No valid session found. Please check your credentials!")

            self.session = session
            self.logger.info("Created session %s" % dict(self.session))

        except KeyError:
            raise CloseSpider("No valid session found. Please check your credentials!")

        self.parse(response)

    def parse(self, response):
        if not self.session:
            raise CloseSpider("No active session present")
        pass
