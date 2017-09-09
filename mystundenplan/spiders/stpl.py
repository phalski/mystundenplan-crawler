# -*- coding: utf-8 -*-
import jmespath
import json
import mystundenplan.spiders.session as session
import re
from scrapy import Selector


class StplSpider(session.SessionSpider):
    """
    Scrapy spider for myStundenplan app

    Usage:
    scrapy crawl stpl -a tenant='[tenant]' -a username='[username]' -a password='[password]' -o stpl.jl

    The site will be traversed the following way:
    .
    └── semesterJson
        └── foreach:sem
            ├── indexHtml
            │   ├── foreach:stg
            │   │   └── courseJson
            │   │       └── foreach:stgru
            │   │           ├── classCalendarHtml
            │   │           └── classCalendarJson
            │   └── foreach:raum
            │       ├── raumCalendarHtml
            │       └── raumCalendarJson
            ├── courseSelectionJson
            │   └── foreach:stgru
            │       └── classSelectionJson
            ├── personalCalendarHtml
            └── personalCalendarJson
    """

    name = 'stpl'

    def __init__(self, tenant=None, username=None, password=None, *args, **kwargs):
        super(StplSpider, self).__init__(tenant, username, password, *args, **kwargs)

    def parse(self, response):
        yield self.request(self.meta('semesterJson'), form={'mode': 'cbsem'}, callback=self.scrape_semester_json)

    def scrape_semester_json(self, response):
        meta = self.extract_meta(response)
        json_data = json.loads(response.text)

        # select semester ids
        # sems = jmespath.search('[? isaktuelles ==`true`].id', json_data)
        sems = jmespath.search('[].id', json_data)
        self.log_select(meta, 'semester', sems)
        for sem in sems:
            context = {'sem': sem}
            yield self.request(self.meta('indexHtml', context), form={'sem': sem}, callback=self.scrape_index_html)
            yield self.request(self.meta('courseSelectionJson', context, True), query={'sem': sem},
                               form={'mode': 'faecherauswahlstg'}, callback=self.scrape_course_selection_json)
            yield self.request(self.meta('personalCalendarHtml', context, True), query={'sem': sem},
                               form={'mode': 'cbGrid'},
                               callback=self.scrape_personal_calendar_html)
            yield self.request(self.meta('personalCalendarJson', context, True), query={'sem': sem, 'method': 'list'},
                               form={'mode': 'calendar'}, callback=self.scrape_json)

        yield {'meta': meta._asdict(), 'data': json_data}
        self.log_done(meta)

    def scrape_course_selection_json(self, response):
        meta = self.extract_meta(response)
        json_data = json.loads(response.text)

        stgrus = jmespath.search('*[].*[].*[].*[].*[].*[].studiengruppen_id', json_data)
        self.log_select(meta, 'class', stgrus)
        for stgru in stgrus:
            context = meta.context.copy()
            context.update({'stgru': stgru})
            yield self.request(self.meta('classSelectionJson', context), query={'sem': context['sem']},
                               form={'mode': 'faecherauswahllv', 'faecherauswahlstgru': stgru},
                               callback=self.scrape_json)

        yield {'meta': meta._asdict(), 'data': json_data}
        self.log_done(meta)

    def scrape_index_html(self, response):
        meta = self.extract_meta(response)
        html_data = Selector(text=response.text)

        # select course ids (without first -1 value)
        stgs = html_data.css("#cbstg > option:not(:first-child)").css('::attr(value)').extract()
        self.log_select(meta, 'course', stgs)
        for stg in stgs:
            context = meta.context.copy()
            context.update({'stg': stg})
            yield self.request(self.meta('courseJson', context), query={'sem': context['sem']},
                               form={'mode': 'cbstg', 'stg': stg},
                               callback=self.scrape_course_json)

        # select raum ids (without first -1 value)
        raums = html_data.css("#cbraum > option:not(:first-child)").css(
            "::attr(value)").extract()
        self.log_select(meta, 'raum', raums)
        for raum in raums:
            context = meta.context.copy()
            context.update({'raum': raum})
            yield self.request(self.meta('raumCalendarHtml', context), query={'sem': context['sem'], 'raum': raum},
                               form={'mode': 'cbGrid'}, callback=self.scrape_raum_calendar_html)
            yield self.request(self.meta('raumCalendarJson', context), query={'sem': context['sem'], 'method': 'list'},
                               form={'mode': 'calendar', 'raum': raum}, callback=self.scrape_json)

        # ---
        stundenraster = []
        for line in html_data.css('head > script:last_child::text').re(r'stundenraster\[\d+\] = \[(.*)\];'):
            m = re.fullmatch(r'\'(?P<starts>\d{2}.\d{2})\', \'(?P<ends>\d{2}.\d{2})\', \'(?P<slot>\d+)\'', line)
            if m:
                stundenraster.append({'slot': m.group('slot'), 'starts': m.group('starts'), 'ends': m.group('ends'), })

        cbraum = []
        for (i, element) in enumerate(html_data.css("#cbraum > option:not(:first-child)")):
            cbraum.append({
                'id': element.css('::attr(value)').extract_first(),
                'title': element.css('::attr(title)').extract_first(),
                'name': element.css('::text').extract_first()
            })

        js_variables = html_data.css('head > script:last_child::text')

        data = {
            'title': html_data.css('head > title::text').extract_first(),
            'indexLink': js_variables.re_first(r'indexLink = \'(.*)\';'),
            'frontendDir': js_variables.re_first(r'frontendDir = \'(.*)\';'),
            'stplIndexLink': js_variables.re_first(r'STPL.IndexLink = \'(.*)\';'),
            'vorlesungsanfang': js_variables.re_first(r'Vorlesungsanfang = \'(.*)\';'),
            'vorlesungsende': js_variables.re_first( r'Vorlesungsende = \'(.*)\';'),
            'semesteranfang': js_variables.re_first( r'Semesteranfang = \'(.*)\';'),
            'semesterende': js_variables.re_first(r'Semesterende = \'(.*)\';'),
            'stundenraster': stundenraster,
            'cbraum': cbraum
        }
        # ---


        yield {'meta': meta._asdict(), 'data': data}
        self.log_done(meta)

    def scrape_course_json(self, response):
        meta = self.extract_meta(response)
        json_data = json.loads(response.text)

        # select class ids
        stgrus = jmespath.search('*[].studiengruppen_id', json_data)
        self.log_select(meta, 'class', stgrus)
        for stgru in stgrus:
            context = meta.context.copy()
            context.update({'stgru': stgru})
            yield self.request(self.meta('classCalendarHtml', context), query={'sem': context['sem'], 'stgru': stgru},
                               form={'mode': 'cbGrid'}, callback=self.scrape_class_calendar_html)
            yield self.request(self.meta('classCalendarJson', context), query={'sem': context['sem'], 'method': 'list'},
                               form={'mode': 'calendar', 'stgru': stgru}, callback=self.scrape_json)

        yield {'meta': meta._asdict(), 'data': json_data}
        self.log_done(meta)

    def scrape_personal_calendar_html(self, response):
        meta = self.extract_meta(response)
        html_data = Selector(text=response.text)
        data = {'title': html_data.css('#content_title > h2::text').extract_first()}
        yield {'meta': meta._asdict(), 'data': data}
        self.log_done(meta)

    def scrape_class_calendar_html(self, response):
        meta = self.extract_meta(response)
        html_data = Selector(text=response.text)
        yield {'meta': meta._asdict(), 'data': {
            'title': html_data.css('#content_title > h2::text').extract_first(),
            'subtitle': html_data.css('#content_subtitle > div::text').extract_first()
        }}
        self.log_done(meta)

    def scrape_raum_calendar_html(self, response):
        meta = self.extract_meta(response)
        html_data = Selector(text=response.text)
        yield {'meta': meta._asdict(), 'data': {
            'title': html_data.css('#content_title > h2::text').extract_first(),
            'subtitle': html_data.css('#content_subtitle > div > div:nth-child(1)::text').extract_first(),
            'description': html_data.css('#content_subtitle > div > div:nth-child(2)::text').re_first(
                r'Beschreibung: (.*)$'),
            'type': html_data.css('#content_subtitle > div > div:nth-child(3)::text').re_first(r'Raumtyp: (.*)$')
        }}
        self.log_done(meta)

    def scrape_json(self, response):
        meta = self.extract_meta(response)
        json_data = json.loads(response.text)
        yield {'meta': meta._asdict(), 'data': json_data}
        self.log_done(meta)

    def log_select(self, meta, name, items):
        self.logger.info('Selected %s %s(s) from %s' % (len(items), name, meta.id))

    def log_done(self, meta):
        self.logger.info('Processed %s', meta.id)
