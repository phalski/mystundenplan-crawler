# -*- coding: utf-8 -*-
import scrapy
from scrapy import Selector
from scrapy.exceptions import CloseSpider
from scrapy.loader.processors import SelectJmes, Compose, MapCompose

import re
import json
import jmespath
from mystundenplan.items import SessionItem
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from w3lib.url import url_query_cleaner


def url_create(url, query_data):
    return urlunparse(urlparse(url)._replace(query=urlencode(query_data)))


def require(response, params):
    for param in params:
        if 'param_fh' == param:
            pass


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
        request = scrapy.FormRequest(
            self.login_url,
            formdata={'user': self.username, 'pwd': self.password, 'mode': 'login', 'FH': self.tenant},
            callback=self.store_session_data
        )
        self.logger.debug("Prepared login request for %s:%s@%s at %s" %
                          (self.username, self.password, self.tenant, self.login_url))
        return [request]

    def store_session_data(self, response):
        query = parse_qs(urlparse(response.url).query)

        try:
            session = {
                'url': url_query_cleaner(response.url),
                'fh': query['FH'][0],
                'lang': query['Lang'][0],
                'user': query['User'][0],
                'session': query['Session'][0]
            }

            yield scrapy.FormRequest(
                url_create(session['url'], {'FH': session['fh']}),
                formdata={'mode': 'cbsem', 'Session': session['session'], 'User': session['user']},
                callback=self.scrape_semester_data,
                meta={'session': session}
            )
        except KeyError:
            raise CloseSpider("No valid session found. Please check your credentials!")

    def scrape_semester_data(self, response):
        session = response.meta['session']
        data = json.loads(response.text)

        # scrape semester data
        yield {
            'meta': {
                'contentType': 'semesterData',
                'fh': session['fh'],
                'lang': session['lang'],
                'user': session['user'],
                'session': session['session']
            },
            'content': data
        }

        # select semester ids
        sems = jmespath.search('[? isaktuelles ==`true`].id', data)
        # sems = jmespath.search('[].id', data)
        for sem in sems:
            meta = {
                'session': session,
                'sem': sem
            }

            # crawl index document
            yield scrapy.FormRequest(
                url_create(session['url'], {'FH': session['fh']}),
                formdata={'User': session['user'], 'Session': session['session'], 'sem': sem},
                callback=self.scrape_index_document,
                meta=meta
            )
            # crawl course selection data
            yield scrapy.FormRequest(
                url_create(session['url'], {'FH': session['fh'], 'sem': sem}),
                formdata={'mode': 'faecherauswahlstg', 'Session': session['session'], 'User': session['user']},
                callback=self.scrape_course_selection_data,
                meta=meta
            )
            # crawl personal calendar document
            yield scrapy.FormRequest(
                url_create(session['url'], {'FH': session['fh'], 'sem': sem}),
                formdata={'mode': 'cbGrid', 'Session': session['session'], 'User': session['user']},
                callback=self.scrape_personal_calendar_document,
                meta=meta
            )
            # crawl personal calendar data
            yield scrapy.FormRequest(
                url_create(session['url'], {'FH': session['fh'], 'sem': sem, 'method': 'list'}),
                formdata={'Session': session['session'], 'User': session['user'], 'mode': 'calendar'},
                callback=self.scrape_personal_calendar_data,
                meta=meta
            )

    def scrape_index_document(self, response):
        session = response.meta['session']
        sem = response.meta['sem']
        selector = Selector(text=response.text)

        # scrape index document
        stundenraster_strings = selector.css('head > script:last_child::text').re(r'stundenraster\[\d+\] = \[(.*)\];')
        stundenraster = []
        for s in stundenraster_strings:
            match = re.fullmatch(r'\'(?P<starts>\d{2}.\d{2})\', \'(?P<ends>\d{2}.\d{2})\', \'(?P<slot>\d+)\'', s)
            if match:
                stundenraster.append({
                    'slot': match.group('slot'),
                    'starts': match.group('starts'),
                    'ends': match.group('ends'),
                })

        cbraum = []
        cbraum_elements = Selector(text=response.text).css("#cbraum > option:not(:first-child)")
        for (i, element) in enumerate(cbraum_elements):
            cbraum.append({
                'id': element.css('::attr(value)').extract_first(),
                'title': element.css('::attr(title)').extract_first(),
                'name': element.css('::text').extract_first()
            })

        yield {
            'meta': {
                'contentType': 'indexDocument',
                'fh': session['fh'],
                'lang': session['lang'],
                'user': session['user'],
                'session': session['session'],
                'sem': sem
            },
            'content': {
                'title': selector.css('head > title::text').extract_first(),
                'vorlesungsanfang': selector.css('head > script:last_child::text').re_first(r'Vorlesungsanfang = \'(.*)\';'),
                'vorlesungsende': selector.css('head > script:last_child::text').re_first(r'Vorlesungsende = \'(.*)\';'),
                'semesteranfang': selector.css('head > script:last_child::text').re_first(r'Semesteranfang = \'(.*)\';'),
                'semesterende': selector.css('head > script:last_child::text').re_first(r'Semesterende = \'(.*)\';'),
                'stundenraster': stundenraster,
                'cbraum': cbraum
            }
        }

        # select course ids (without first -1 value)
        stgs = Selector(text=response.text).css("#cbstg > option:not(:first-child)").css('::attr(value)').extract()
        for stg in stgs:
            meta = {
                'session': session,
                'sem': sem,
                'stg': stg
            }

            # crawl course data
            yield scrapy.FormRequest(
                url_create(session['url'], {'FH': session['fh'], 'sem': sem}),
                formdata={'mode': 'cbstg', 'stg': stg, 'Session': session['session'], 'User': session['user']},
                callback=self.scrape_course_data,
                meta=meta
            )

        # select raum ids (without first -1 value)
        raums = Selector(text=response.text).css("#cbraum > option:not(:first-child)").css("::attr(value)").extract()
        for raum in raums:
            meta = {
                'session': session,
                'sem': sem,
                'raum': raum
            }

            # crawl raum calendar document
            yield scrapy.FormRequest(
                url_create(session['url'], {'FH': session['fh'], 'sem': sem, 'raum': raum}),
                formdata={'mode': 'cbGrid', 'Session': session['session'], 'User': session['user']},
                callback=self.scrape_raum_calendar_document,
                meta=meta
            )

            # crawl raum calendar data
            yield scrapy.FormRequest(
                url_create(session['url'], {'FH': session['fh'], 'sem': sem, 'method': 'list'}),
                formdata={'Session': session['session'], 'User': session['user'], 'mode': 'calendar', 'raum': raum},
                callback=self.scrape_raum_calendar_data,
                meta=meta
            )

    def scrape_course_data(self, response):
        session = response.meta['session']
        sem = response.meta['sem']
        stg = response.meta['stg']
        data = json.loads(response.text)

        # scrape course data
        yield {
            'meta': {
                'contentType': 'courseData',
                'fh': session['fh'],
                'lang': session['lang'],
                'user': session['user'],
                'session': session['session'],
                'sem': sem,
                'stg': stg
            },
            'content': data
        }

        # select class ids
        stgrus = jmespath.search('*[].studiengruppen_id', data)
        for stgru in stgrus:
            meta = {
                'session': session,
                'sem': sem,
                'stg': stg,
                'stgru': stgru
            }

            # crawl class calendar document
            yield scrapy.FormRequest(
                url_create(session['url'], {'FH': session['fh'], 'sem': sem, 'stgru': stgru}),
                formdata={'mode': 'cbGrid', 'Session': session['session'], 'User': session['user']},
                callback=self.scrape_class_calendar_document,
                meta=meta
            )

            # crawl class calendar data
            yield scrapy.FormRequest(
                url_create(session['url'], {'FH': session['fh'], 'sem': sem, 'method': 'list'}),
                formdata={'Session': session['session'], 'User': session['user'], 'mode': 'calendar', 'stgru': stgru},
                callback=self.scrape_class_calendar_data,
                meta=meta
            )


    def scrape_class_calendar_document(self, response):
        session = response.meta['session']
        sem = response.meta['sem']
        stg = response.meta['stg']
        stgru = response.meta['stgru']

        # scrape class calendar data
        yield {
            'meta': {
                'contentType': 'classCalendarDocument',
                'fh': session['fh'],
                'lang': session['lang'],
                'user': session['user'],
                'session': session['session'],
                'sem': sem,
                'stg': stg,
                'stgru': stgru
            },
            'content': response.text
        }

    def scrape_class_calendar_data(self, response):
        session = response.meta['session']
        sem = response.meta['sem']
        stg = response.meta['stg']
        stgru = response.meta['stgru']
        data = json.loads(response.text)

        # scrape class calendar data
        yield {
            'meta': {
                'contentType': 'classCalendarData',
                'fh': session['fh'],
                'lang': session['lang'],
                'user': session['user'],
                'session': session['session'],
                'sem': sem,
                'stg': stg,
                'stgru': stgru
            },
            'content': data
        }

    def scrape_raum_calendar_document(self, response):
        session = response.meta['session']
        sem = response.meta['sem']
        raum = response.meta['raum']

        # scrape class calendar data
        yield {
            'meta': {
                'contentType': 'raumCalendarDocument',
                'fh': session['fh'],
                'lang': session['lang'],
                'user': session['user'],
                'session': session['session'],
                'sem': sem,
                'raum': raum
            },
            'content': response.text
        }

    def scrape_raum_calendar_data(self, response):
        session = response.meta['session']
        sem = response.meta['sem']
        raum = response.meta['raum']
        data = json.loads(response.text)

        # scrape class calendar data
        yield {
            'meta': {
                'contentType': 'raumCalendarData',
                'fh': session['fh'],
                'lang': session['lang'],
                'user': session['user'],
                'session': session['session'],
                'sem': sem,
                'raum': raum
            },
            'content': data
        }

    def scrape_course_selection_data(self, response):
        session = response.meta['session']
        sem = response.meta['sem']
        data = json.loads(response.text)

        # scrape course selection data
        yield {
            'meta': {
                'contentType': 'courseSelectionData',
                'fh': session['fh'],
                'lang': session['lang'],
                'user': session['user'],
                'session': session['session'],
                'sem': sem
            },
            'content': data
        }

        stgrus = jmespath.search('*[].*[].*[].*[].*[].*[].studiengruppen_id', data)
        for stgru in stgrus:
            meta = {
                'session': session,
                'sem': sem,
                'stgru': stgru
            }

            # crawl class selection calendar
            yield scrapy.FormRequest(
                url_create(session['url'], {'FH': session['fh'], 'sem': sem}),
                formdata={'mode': 'faecherauswahllv', 'faecherauswahlstgru': stgru, 'Session': session['session'],
                          'User': session['user']},
                callback=self.scrape_class_selection_data,
                meta=meta
            )

    def scrape_class_selection_data(self, response):
        session = response.meta['session']
        sem = response.meta['sem']
        stgru = response.meta['stgru']
        data = json.loads(response.text)

        yield {
            'meta': {
                'contentType': 'classSelectionData',
                'fh': session['fh'],
                'lang': session['lang'],
                'user': session['user'],
                'session': session['session'],
                'sem': sem,
                'stgru': stgru
            },
            'content': data
        }

    def scrape_personal_calendar_document(self, response):
        session = response.meta['session']
        sem = response.meta['sem']

        yield {
            'meta': {
                'contentType': 'personalCalendarDocument',
                'fh': session['fh'],
                'lang': session['lang'],
                'user': session['user'],
                'session': session['session'],
                'sem': sem
            },
            'content': {
                'title': Selector(text=response.text).css('#content_title > h2::text').extract_first()
            }
        }

    def scrape_personal_calendar_data(self, response):
        session = response.meta['session']
        sem = response.meta['sem']
        data = json.loads(response.text)

        yield {
            'meta': {
                'contentType': 'personalCalendarData',
                'fh': session['fh'],
                'lang': session['lang'],
                'user': session['user'],
                'session': session['session'],
                'sem': sem
            },
            'content': data
        }

