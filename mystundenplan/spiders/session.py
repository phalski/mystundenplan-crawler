# -*- coding: utf-8 -*-
import scrapy
from collections import namedtuple
from scrapy.exceptions import CloseSpider
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from w3lib.url import url_query_cleaner


def url_create(url, query_data):
    return urlunparse(urlparse(url)._replace(query=urlencode(query_data)))


class SessionSpider(scrapy.Spider):
    VALID_SESSION_LEN = 40

    name = 'session'
    allowed_domains = ['www3.primuss.de']

    def __init__(self, tenant=None, username=None, password=None, *args, **kwargs):
        super(SessionSpider, self).__init__(*args, **kwargs)
        Credentials = namedtuple('Credentials', ['tenant', 'username', 'password'])
        if tenant and username and password:
            self.credentials = Credentials(tenant, username, password)

        self.session = None

    def start_requests(self):
        if not self.credentials:
            raise CloseSpider("Credentials missing")

        self.logger.debug('Attempting login with %s' % (self.credentials,))
        request = scrapy.FormRequest('https://www3.primuss.de/stpl/login.php',
                                     formdata={'user': self.credentials.username, 'pwd': self.credentials.password,
                                               'mode': 'login', 'FH': self.credentials.tenant},
                                     callback=self.store_session_data)
        return [request]

    def store_session_data(self, response):
        query = parse_qs(urlparse(response.url).query)

        try:
            Session = namedtuple('Session', ['url', 'fh', 'lang', 'user', 'session'])
            session = Session(url_query_cleaner(response.url), query.get('FH')[0], query.get('Lang')[0],
                              query.get('User')[0], query.get('Session')[0])
            self.session = session
        except KeyError:
            raise CloseSpider("No valid session found. Please check your credentials!")

        self.logger.info('Stored %s' % (self.session,))
        return self.parse(response)

    def parse(self, response):
        raise NotImplementedError

    def request(self, meta, query=None, form=None, callback=None):
        """ Returns a new form request with given query and form params

        Query and form will be updated with current session information

        :param query:
        :param form:
        :param callback:
        :return:
        """
        if query is None: query = {}
        if form is None: form = {}

        query.update({'FH': self.session.fh})
        form.update({'User': self.session.user, 'Session': self.session.session})

        return scrapy.FormRequest(url_create(self.session.url, query), formdata=form, callback=callback,
                                  meta={'meta': meta})

    def meta(self, name, context=None, show_user=False):
        meta_context = {'fh': self.session.fh}
        if show_user:
            meta_context.update({'user': self.session.user})
        if not context is None:
            meta_context.update(context)

        Meta = namedtuple('Meta', ['id', 'name', 'context'])
        return Meta('%s(%s)' % (name, meta_context), name, meta_context)

    def extract_meta(self, response):
        return response.meta['meta']