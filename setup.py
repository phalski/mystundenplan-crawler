from distutils.core import setup

setup(
    name='mystundenplan-crawler',
    version='0.1',
    packages=['mystundenplan', 'mystundenplan.spiders'],
    url='https://github.com/phalski/mystundenplan-crawler',
    license='MIT',
    author='Philipp Michalski',
    author_email='dev@phalski.com',
    description='A web crawler for myStundenplan',

    install_requires=[
        'Scrapy'
    ]
)
