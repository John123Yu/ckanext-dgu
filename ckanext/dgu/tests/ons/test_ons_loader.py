import os

from pylons import config
from sqlalchemy.util import OrderedDict

from ckanext.dgu.ons import importer
from ckanext.dgu.ons.loader import OnsLoader
from ckanext.tests.test_loader import TestLoaderBase
from ckan import model
from ckan.tests import *


TEST_DIR = os.path.dirname(os.path.abspath(__file__))
SAMPLE_PATH = os.path.join(TEST_DIR, 'samples')
SAMPLE_FILEPATH_1 = os.path.join(SAMPLE_PATH, 'ons_hub_sample.xml')
SAMPLE_FILEPATH_2 = os.path.join(SAMPLE_PATH, 'ons_hub_sample2.xml')
SAMPLE_FILEPATH_3 = os.path.join(SAMPLE_PATH, 'ons_hub_sample3')
SAMPLE_FILEPATH_4 = os.path.join(SAMPLE_PATH, 'ons_hub_sample4.xml')
SAMPLE_FILEPATH_4a = os.path.join(SAMPLE_PATH, 'ons_hub_sample4a.xml')
SAMPLE_FILEPATH_4b = os.path.join(SAMPLE_PATH, 'ons_hub_sample4b.xml')
SAMPLE_FILEPATH_5 = os.path.join(SAMPLE_PATH, 'ons_hub_sample5.xml')
SAMPLE_FILEPATH_6 = os.path.join(SAMPLE_PATH, 'ons_hub_sample6.xml')
SAMPLE_FILEPATH_7 = os.path.join(SAMPLE_PATH, 'ons_hub_sample7.xml')


class TestOnsLoadBasic(TestLoaderBase):
    def setup(self):
        super(TestOnsLoadBasic, self).setup()
        importer_ = importer.OnsImporter(SAMPLE_FILEPATH_1)
        self.pkg_dicts = [pkg_dict for pkg_dict in importer_.pkg_dict()]

        loader = OnsLoader(self.testclient)
        self.res = loader.load_packages(self.pkg_dicts)
        assert self.res['num_errors'] == 0, self.res
        CreateTestData.flag_for_deletion([pkg_dict['name'] for pkg_dict in self.pkg_dicts])

    def test_fields(self):
        q = model.Session.query(model.Package)
        names = [pkg.name for pkg in q.all()]
        pkg1 = model.Package.by_name(u'uk_official_holdings_of_international_reserves')
        cereals = model.Package.by_name(u'cereals_and_oilseeds_production_harvest')
        custody = model.Package.by_name(u'end_of_custody_licence_release_and_recalls')
        probation = model.Package.by_name(u'probation_statistics_brief')
        assert pkg1, names
        assert cereals, names
        assert custody, names
        assert probation, names
        assert pkg1.title == 'UK Official Holdings of International Reserves', pkg1.title
        assert pkg1.notes.startswith("Monthly breakdown for government's net reserves, detailing gross reserves and gross liabilities."), pkg1.notes
        assert len(pkg1.resources) == 1, pkg1.resources
        assert pkg1.resources[0].url == 'http://www.hm-treasury.gov.uk/national_statistics.htm', pkg1.resources[0]
        assert pkg1.resources[0].description == 'December 2009 | hub/id/119-36345', pkg1.resources[0].description
        assert len(custody.resources) == 2, custody.resources
        assert custody.resources[0].url == 'http://www.justice.gov.uk/publications/endofcustodylicence.htm', custody.resources[0]
        assert custody.resources[0].description == 'November 2009 | hub/id/119-36836', custody.resources[0].description
        assert custody.resources[1].url == 'http://www.justice.gov.uk/publications/endofcustodylicence.htm', custody.resources[0]
        assert custody.resources[1].description == 'December 2009 | hub/id/119-36838', custody.resources[1].description
        assert pkg1.extras['date_released'] == u'2010-01-06', pkg1.extras['date_released']
        assert probation.extras['date_released'] == u'2010-01-04', probation.extras['date_released']
        assert pkg1.extras['department'] == u"Her Majesty's Treasury", pkg1.extras['department']
        assert cereals.extras['department'] == u"Department for Environment, Food and Rural Affairs", cereals.extras['department']
        assert custody.extras['department'] == u"Ministry of Justice", custody.extras['department']
        assert u"Source agency: HM Treasury" in pkg1.notes, pkg1.notes
        assert pkg1.extras['categories'] == 'Economy', pkg1.extras['category']
        assert pkg1.extras['geographic_coverage'] == '111100: United Kingdom (England, Scotland, Wales, Northern Ireland)', pkg1.extras['geographic_coverage']
        assert pkg1.extras['national_statistic'] == 'no', pkg1.extras['national_statistic']
        assert cereals.extras['national_statistic'] == 'yes', cereals.extras['national_statistic']
        assert custody.extras['national_statistic'] == 'no', custody.extras['national_statistic']
        assert 'Designation: Official Statistics not designated as National Statistics' in custody.notes
        assert pkg1.extras['geographical_granularity'] == 'UK and GB', pkg1.extras['geographical_granularity']
        assert 'Language: English' in pkg1.notes, pkg1.notes
        def check_tags(pkg, tags_list):            
            pkg_tags = [tag.name for tag in pkg.tags]
            for tag in tags_list:
                assert tag in pkg_tags, "Couldn't find tag '%s' in tags: %s" % (tag, pkg_tags)
        check_tags(pkg1, ('economics-and-finance', 'reserves', 'currency', 'assets', 'liabilities', 'gold', 'economy', 'government-receipts-and-expenditure', 'public-sector-finance'))
        check_tags(cereals, ('environment', 'farming'))
        check_tags(custody, ('public-order-justice-and-rights', 'justice-system', 'prisons'))
        assert 'Alternative title: UK Reserves' in pkg1.notes, pkg1.notes
        
        assert pkg1.extras['external_reference'] == u'ONSHUB', pkg1.extras['external_reference']
        assert 'Open Government Licence' in pkg.license.title, pkg.license.title
        assert pkg1.extras['update_frequency'] == u'monthly', pkg1.extras['update_frequency']
        assert custody.extras['update_frequency'] == u'monthly', custody.extras['update_frequency']
        assert pkg1.author == u"Her Majesty's Treasury", pkg1.author
        assert cereals.author == u'Department for Environment, Food and Rural Affairs', cereals.author
        assert custody.author == u'Ministry of Justice', custody.author

#        assert model.Group.by_name(u'ukgov') in pkg1.groups
        for pkg in (pkg1, cereals, custody):
            assert pkg.extras['import_source'].startswith('ONS'), '%s %s' % (pkg.name, pkg.extras['import_source'])


class TestOnsLoadTwice(TestLoaderBase):
    def setup(self):
        super(TestOnsLoadTwice, self).setup()
        # SAMPLE_FILEPATH_2 has the same packages as 1, but slightly updated
        for filepath in [SAMPLE_FILEPATH_1, SAMPLE_FILEPATH_2]:
            importer_ = importer.OnsImporter(filepath)
            pkg_dicts = [pkg_dict for pkg_dict in importer_.pkg_dict()]
            loader = OnsLoader(self.testclient)
            res = loader.load_packages(pkg_dicts)
            assert res['num_errors'] == 0, res
        CreateTestData.flag_for_deletion([pkg_dict['name'] for pkg_dict in pkg_dicts])

    def test_packages(self):
        pkg = model.Package.by_name(u'uk_official_holdings_of_international_reserves')
        assert pkg.title == 'UK Official Holdings of International Reserves', pkg.title
        assert pkg.notes.startswith('CHANGED'), pkg.notes
        assert len(pkg.resources) == 1, pkg.resources
        assert 'CHANGED' in pkg.resources[0].description, pkg.resources


class TestOnsLoadClashTitle(TestLoaderBase):
    # two packages with the same title, both from ONS,
    # but from different departments, so must be different packages
    def setup(self):
        super(TestOnsLoadClashTitle, self).setup()
        # ons items have been split into 3 files, because search needs to
        # do indexing in between
        for suffix in 'abc':
            importer_ = importer.OnsImporter(SAMPLE_FILEPATH_3 + suffix + '.xml')
            pkg_dicts = [pkg_dict for pkg_dict in importer_.pkg_dict()]
            loader = OnsLoader(self.testclient)
            self.res = loader.load_packages(pkg_dicts)
            assert self.res['num_errors'] == 0, self.res
        CreateTestData.flag_for_deletion([pkg_dict['name'] for pkg_dict in pkg_dicts])

    def test_ons_package(self):
        pkg = model.Package.by_name(u'annual_survey_of_hours_and_earnings')
        assert pkg
        assert pkg.extras.get('department') == 'UK Statistics Authority', pkg.extras.get('department')
        assert 'Office for National Statistics' in pkg.notes, pkg.notes
        assert len(pkg.resources) == 2, pkg.resources
        assert '2007 Results Phase 3 Tables' in pkg.resources[0].description, pkg.resources
        assert '2007 Pensions Results' in pkg.resources[1].description, pkg.resources

    def test_welsh_package(self):
        pkg = model.Package.by_name(u'annual_survey_of_hours_and_earnings_')
        assert pkg
        assert pkg.extras['department'] == 'Welsh Assembly Government', pkg.extras['department']
        assert len(pkg.resources) == 1, pkg.resources
        assert '2008 Results' in pkg.resources[0].description, pkg.resources


class TestOnsLoadClashSource(TestLoaderBase):
    # two packages with the same title, and department, but one not from ONS,
    # so must be different packages
    def setup(self):
        super(TestOnsLoadClashSource, self).setup()

        self.clash_name = u'cereals_and_oilseeds_production_harvest'
        CreateTestData.create_arbitrary([
            {'name':self.clash_name,
             'title':'Test clash',
             'extras':{
                 'department':'Department for Environment, Food and Rural Affairs',
                 'import_source':'DECC-Jan-09',
                 },
             }
            ])
        importer_ = importer.OnsImporter(SAMPLE_FILEPATH_1)
        CreateTestData.flag_for_deletion(self.clash_name)
        pkg_dicts = [pkg_dict for pkg_dict in importer_.pkg_dict()]
        loader = OnsLoader(self.testclient)
        self.res = loader.load_packages(pkg_dicts)
        assert self.res['num_errors'] == 0, self.res

    def test_names(self):
        pkg1 = model.Package.by_name(self.clash_name)
        assert pkg1.title == u'Test clash', pkg1.title

        pkg2 = model.Package.by_name(self.clash_name + u'_')
        assert pkg2.title == u'Cereals and Oilseeds Production Harvest', pkg2.title

class TestOnsLoadSeries(TestLoaderBase):
    def setup(self):
        super(TestOnsLoadSeries, self).setup()
        for filepath in [SAMPLE_FILEPATH_4a, SAMPLE_FILEPATH_4b]:
            importer_ = importer.OnsImporter(filepath)
            pkg_dicts = [pkg_dict for pkg_dict in importer_.pkg_dict()]
            for pkg_dict in pkg_dicts:
                assert pkg_dict['title'] == 'Regional Labour Market Statistics', pkg_dict
                assert pkg_dict['extras']['agency'] == 'Office for National Statistics', pkg_dict
                assert pkg_dict['extras']['department'] == 'UK Statistics Authority', pkg_dict
            loader = OnsLoader(self.testclient)
            res = loader.load_packages(pkg_dicts)
            assert res['num_errors'] == 0, res
        CreateTestData.flag_for_deletion('regional_labour_market_statistics')

    def test_packages(self):
        pkg = model.Package.by_name(u'regional_labour_market_statistics')
        assert pkg
        assert pkg.title == 'Regional Labour Market Statistics', pkg.title
        assert pkg.extras['agency'] == 'Office for National Statistics', pkg.extras['agency']
        assert len(pkg.resources) == 9, pkg.resources

class TestOnsLoadMissingDept(TestLoaderBase):
    # existing package to be updated has no department given (previously
    # there was no default to 'UK Statistics Authority'.
    def setup(self):
        super(TestOnsLoadMissingDept, self).setup()

        self.orig_pkg_dict = {
             "name": u"measuring_subjective_wellbeing_in_the_uk",
             "title": "Measuring Subjective Wellbeing in the UK",
             "notes": "This report reviews:\n\nWhat is subjective wellbeing and why should we measure it?\n\nHow subjective wellbeing is currently measured in the UK - what subjective wellbeing questions are already being asked on major social surveys in the UK\n\nThe potential uses of subjective wellbeing data collected via these surveys\n\n\nIt concludes that subjective wellbeing is a valid construct that can be measured reliably. This is the first output of ONS' work on subjective wellbeing.\n\nSource agency: Office for National Statistics\n\nDesignation: Supporting material\n\nLanguage: English\n\nAlternative title: Working Paper: Measuring Subjective Wellbeing in the UK",
             "license_id": "ukcrown-withrights",
             "tags": ["communities", "health-well-being-and-care", "people-and-places", "societal-wellbeing", "subjective-wellbeing-subjective-well-being-objective-measures-subjective-measures", "well-being"],
             "groups": ["ukgov"],
             "extras": {"geographic_coverage": "111100: United Kingdom (England, Scotland, Wales, Northern Ireland)", "geographical_granularity": "UK and GB", "external_reference": "ONSHUB", "temporal_granularity": "", "date_updated": "", "agency": "Office for National Statistics", "precision": "", "temporal_coverage_to": "", "temporal_coverage_from": "", "national_statistic": "no", "import_source": "ONS-ons_data_7_days_to_2010-09-17", "department": 'UK Statistics Authority', "update_frequency": "", "date_released": "2010-09-14", "categories": "People and Places"},
             "resources": [{"url": "http://www.ons.gov.uk/about-statistics/measuring-equality/wellbeing/news-and-events/index.html", "format": "", "description": "2010 | hub/id/77-31166", }],
             }
        CreateTestData.create_arbitrary([self.orig_pkg_dict])

        # same data is imported, but should find record and add department
        importer_ = importer.OnsImporter(SAMPLE_FILEPATH_5)
        self.pkg_dict = [pkg_dict for pkg_dict in importer_.pkg_dict()][0]
        loader = OnsLoader(self.testclient)
        self.res = loader.load_package(self.pkg_dict)

    def test_reload(self):
        # Check that another package has not been created
        assert self.pkg_dict['name'] == self.orig_pkg_dict['name'], self.pkg_dict['name']
        pkg1 = model.Package.by_name(self.orig_pkg_dict['name'])

        assert pkg1.extras.get('department') == u'UK Statistics Authority', pkg1.extras


class TestNationalParkDuplicate(TestLoaderBase):
    def setup(self):
        super(TestNationalParkDuplicate, self).setup()
        filepath = SAMPLE_FILEPATH_6
        importer_ = importer.OnsImporter(filepath)
        pkg_dicts = [pkg_dict for pkg_dict in importer_.pkg_dict()]
        self.name = u'national_park_parliamentary_constituency_and_ward_level_mid-year_population_estimates_experimental'
        for pkg_dict in pkg_dicts:
            assert pkg_dict['name'] == self.name, pkg_dict['name']
            assert pkg_dict['title'] == 'National Park, Parliamentary Constituency and Ward level mid-year population estimates (experimental)', pkg_dict
            assert pkg_dict['extras']['agency'] == 'Office for National Statistics', pkg_dict
            assert pkg_dict['extras']['department'] == 'UK Statistics Authority', pkg_dict
        loader = OnsLoader(self.testclient)
        res = loader.load_packages(pkg_dicts)
        assert res['num_errors'] == 0, res
        CreateTestData.flag_for_deletion(self.name)

    def test_packages(self):
        names = [pkg.name for pkg in model.Session.query(model.Package).all()]
        assert names == [self.name], names
        pkg = model.Package.by_name(self.name)
        assert pkg
        assert len(pkg.resources) == 3, pkg.resources

class TestDeathsOverwrite(TestLoaderBase):
    def setup(self):
        super(TestDeathsOverwrite, self).setup()
        self.orig_pkg_dict = {
            "name": u"weekly_provisional_figures_on_deaths_registered_in_england_and_wales",
            "title": "Weekly provisional figures on deaths registered in England and Wales",
            "version": None, "url": None, "author": "UK Statistics Authority", "author_email": None, "maintainer": None, "maintainer_email": None,
            "notes": "Weekly death figures provide provisional counts of the number of deaths registered in England and Wales in the latest four weeks for which data are available up to the end of 2009. From week one 2010 the latest eight weeks for which data are available will be published.\n\nSource agency: Office for National Statistics\n\nDesignation: National Statistics\n\nLanguage: English\n\nAlternative title: Weekly deaths",
            "license_id": "ukcrown-withrights",
            "tags": ["death", "deaths", "life-events", "life-in-the-community", "mortality-rates", "population", "weekly-deaths"],
            "groups": ["ukgov"], "extras": {
                "geographic_coverage": "101000: England, Wales",
                "geographical_granularity": "Country",
                "external_reference": "ONSHUB",
                "temporal_coverage-from": "",
                "temporal_granularity": "",
                "date_updated": "",
                "agency": "",
                "precision": "",
                "geographic_granularity": "",
                "temporal_coverage_to": "",
                "temporal_coverage_from": "",
                "taxonomy_url": "",
                "import_source": "ONS-ons_data_60_days_to_2010-09-22",
                "date_released": "2010-08-03",
                "temporal_coverage-to": "",
                "department": "UK Statistics Authority",
                "update_frequency": "",
                "national_statistic": "yes",
                "categories": "Population"},
            "resources": [
                {"url": "http://www.statistics.gov.uk/StatBase/Prep/9684.asp", "format": "", "description": "17/07/2009 | hub/id/77-27942", "hash": "", }],
            }

        CreateTestData.create_arbitrary([self.orig_pkg_dict])

        # same data is imported, but should find record and add department
        importer_ = importer.OnsImporter(SAMPLE_FILEPATH_7)
        self.pkg_dict = [pkg_dict for pkg_dict in importer_.pkg_dict()][0]
        loader = OnsLoader(self.testclient)
        print self.pkg_dict
        self.res = loader.load_package(self.pkg_dict)
        self.name = self.orig_pkg_dict['name']

    def test_packages(self):
        names = [pkg.name for pkg in model.Session.query(model.Package).all()]
        assert names == [self.name], names
        pkg = model.Package.by_name(self.name)
        assert pkg
        assert len(pkg.resources) == 2, pkg.resources
