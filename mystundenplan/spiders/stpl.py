# -*- coding: utf-8 -*-
import jmespath
import json
import mystundenplan.spiders.session as session
import re
from scrapy import Selector
from mystundenplan.items import Download


class StplSpider(session.SessionSpider):
    """
    Scrapy spider for myStundenplan app

    Usage:
    scrapy crawl stpl -a tenant='[tenant]' -a username='[username]' -a password='[password]' -o stpl.jl

    Tenant is 'fhin' for THI, use your LDAP user credentials to authenticate yourself.

    The site will be traversed the following way:
    .
    └── semesterJson
        └── foreach:semester
            ├── indexHtml
            │   ├── foreach:course
            │   │   └── courseJson
            │   │       └── foreach:class
            │   │           ├── classCalendarHtml
            │   │           └── classCalendarJson
            │   └── foreach:location
            │       ├── locationCalendarHtml
            │       └── locationCalendarJson
            ├── courseSelectionJson
            │   └── foreach:class
            │       └── classSelectionJson
            ├── personalCalendarHtml
            └── personalCalendarJson

    By default this spider will fetch only data from the latest semester. Use the [all] switch to scrape the full data
    set. (-a all=True)
    """

    name = 'stpl'

    def __init__(self, tenant=None, username=None, password=None, all=False, *args, **kwargs):
        super(StplSpider, self).__init__(tenant, username, password, *args, **kwargs)
        self.all = all

    def parse(self, response):
        yield self.semester_json_request(self.scrape_semester_json)

    def scrape_semester_json(self, response):
        meta, json_data = self.json_response(response)

        # select semester ids
        if self.all:
            self.logger.info('Start scraping all semesters')
            semesters = jmespath.search('[].id', json_data)
        else:
            self.logger.info('Start scraping current semester')
            semesters = jmespath.search('[? isaktuelles ==`true`].id', json_data)

        self.log_select(meta, Key.SEMESTER, semesters)
        for semester in semesters:
            yield self.index_html_request(semester, self.scrape_index_html)
            yield self.course_selection_json_request(semester, self.scrape_course_selection_json)
            yield self.personal_calendar_html_request(semester, self.scrape_personal_calendar_html)
            yield self.personal_calendar_json_request(semester, self.scrape_json)

        yield Download(meta=meta._asdict(), data=json_data)
        self.log_done(meta)

    def scrape_course_selection_json(self, response):
        meta, json_data = self.json_response(response)

        class_s = jmespath.search('*[].*[].*[].*[].*[].*[].studiengruppen_id', json_data)
        self.log_select(meta, Key.CLASS, class_s)
        for class_ in class_s:
            yield self.class_selection_json_request(meta.context[Key.SEMESTER], class_, self.scrape_json)

        yield Download(meta=meta._asdict(), data=json_data)
        self.log_done(meta)

    def scrape_index_html(self, response):
        meta, html_data = self.html_response(response)

        # select course ids (without first -1 value)
        courses = html_data.css("#cbstg > option:not(:first-child)").css('::attr(value)').extract()
        self.log_select(meta, Key.COURSE, courses)
        for course in courses:
            yield self.course_json_request(meta.context[Key.SEMESTER], course, self.scrape_course_json)

        # select location ids (without first -1 value)
        locations = html_data.css("#cbraum > option:not(:first-child)").css("::attr(value)").extract()
        self.log_select(meta, Key.LOCATION, locations)
        for location in locations:
            yield self.location_calendar_html_request(meta.context[Key.SEMESTER], location, self.scrape_location_calendar_html)
            yield self.location_calendar_json_request(meta.context[Key.SEMESTER], location, self.scrape_json)

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
            'vorlesungsende': js_variables.re_first(r'Vorlesungsende = \'(.*)\';'),
            'semesteranfang': js_variables.re_first(r'Semesteranfang = \'(.*)\';'),
            'semesterende': js_variables.re_first(r'Semesterende = \'(.*)\';'),
            'stundenraster': stundenraster,
            'cbraum': cbraum
        }
        # ---
        yield Download(meta=meta._asdict(), data=data)
        self.log_done(meta)

    def scrape_course_json(self, response):
        meta, json_data = self.json_response(response)

        # select class ids
        class_s = jmespath.search('*[].studiengruppen_id', json_data)
        self.log_select(meta, Key.CLASS, class_s)
        for class_ in class_s:
            yield self.class_calendar_html_request(meta.context[Key.SEMESTER], meta.context[Key.COURSE], class_,
                                                   self.scrape_class_calendar_html)
            yield self.class_calendar_json_request(meta.context[Key.SEMESTER], meta.context[Key.COURSE], class_,
                                                   self.scrape_json)

        yield Download(meta=meta._asdict(), data=json_data)
        self.log_done(meta)

    def scrape_personal_calendar_html(self, response):
        meta, html_data = self.html_response(response)
        yield Download(meta=meta._asdict(), data={'title': html_data.css('#content_title > h2::text').extract_first()})
        self.log_done(meta)

    def scrape_class_calendar_html(self, response):
        meta, html_data = self.html_response(response)
        yield Download(meta=meta._asdict(), data={
            'title': html_data.css('#content_title > h2::text').extract_first(),
            'subtitle': html_data.css('#content_subtitle > div::text').extract_first()
        })
        self.log_done(meta)

    def scrape_location_calendar_html(self, response):
        meta, html_data = self.html_response(response)
        yield Download(meta=meta._asdict(), data={
            'title': html_data.css('#content_title > h2::text').extract_first(),
            'subtitle': html_data.css('#content_subtitle > div > div:nth-child(1)::text').extract_first(),
            'description': html_data.css('#content_subtitle > div > div:nth-child(2)::text').re_first(
                r'Beschreibung: (.*)$'),
            'type': html_data.css('#content_subtitle > div > div:nth-child(3)::text').re_first(r'Raumtyp: (.*)$')
        })
        self.log_done(meta)

    def scrape_json(self, response):
        meta, json_data = self.json_response(response)
        yield Download(meta=meta._asdict(), data=json_data)
        self.log_done(meta)

    # --- REQUESTS

    def semester_json_request(self, callback):
        return self.request(self.meta('semesterJson'), form={'mode': 'cbsem'}, callback=callback)

    def index_html_request(self, semester, callback):
        return self.request(self.meta('indexHtml', {Key.SEMESTER: semester}), form={'sem': semester},
                            callback=callback)

    def course_selection_json_request(self, semester, callback):
        return self.request(self.meta('courseSelectionJson', {Key.SEMESTER: semester}, True), query={'sem': semester},
                            form={'mode': 'faecherauswahlstg'}, callback=callback)

    def personal_calendar_html_request(self, semester, callback):
        return self.request(self.meta('personalCalendarHtml', {Key.SEMESTER: semester}, True), query={'sem': semester},
                            form={'mode': 'cbGrid'}, callback=callback)

    def personal_calendar_json_request(self, semester, callback):
        return self.request(self.meta('personalCalendarJson', {Key.SEMESTER: semester}, True),
                            query={'sem': semester, 'method': 'list'},
                            form={'mode': 'calendar'}, callback=callback)

    def class_selection_json_request(self, semester, class_, callback):
        return self.request(self.meta('classSelectionJson', {Key.SEMESTER: semester, Key.CLASS: class_}), query={'sem': semester},
                            form={'mode': 'faecherauswahllv', 'faecherauswahlstgru': class_},
                            callback=callback)

    def course_json_request(self, semester, course, callback):
        return self.request(self.meta('courseJson', {Key.SEMESTER: semester, Key.COURSE: course}), query={'sem': semester},
                            form={'mode': 'cbstg', 'stg': course}, callback=callback)

    def location_calendar_html_request(self, semester, location, callback):
        return self.request(self.meta('locationCalendarHtml', {Key.SEMESTER: semester, Key.LOCATION: location}),
                            query={'sem': semester, 'raum': location},
                            form={'mode': 'cbGrid'}, callback=callback)

    def location_calendar_json_request(self, semester, location, callback):
        return self.request(self.meta('locationCalendarJson', {Key.SEMESTER: semester, Key.LOCATION: location}),
                            query={'sem': semester, 'method': 'list'}, form={'mode': 'calendar', 'raum': location},
                            callback=callback)

    def class_calendar_html_request(self, semester, course, class_, callback):
        return self.request(self.meta('classCalendarHtml', {Key.SEMESTER: semester, Key.COURSE: course, Key.CLASS: class_}),
                            query={'sem': semester, 'stgru': class_}, form={'mode': 'cbGrid'},
                            callback=callback)

    def class_calendar_json_request(self, semester, course, class_, callback):
        return self.request(self.meta('classCalendarJson', {Key.SEMESTER: semester, Key.COURSE: course, Key.CLASS: class_}),
                            query={'sem': semester, 'method': 'list'}, form={'mode': 'calendar', 'stgru': class_},
                            callback=callback)

    # --- HELPERS

    def html_response(self, response):
        return self.extract_meta(response), Selector(text=response.text)

    def json_response(self, response):
        return self.extract_meta(response), json.loads(response.text)

    def log_select(self, meta, name, items):
        self.logger.info('Selected %s %s(s) from %s' % (len(items), name, meta.id))

    def log_done(self, meta):
        self.logger.info('Processed %s', meta.id)


class Key:
    SEMESTER = 'semester'
    COURSE = 'course'
    CLASS = 'class'
    LOCATION = 'location'
