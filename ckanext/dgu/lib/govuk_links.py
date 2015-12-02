from collections import defaultdict
import warnings
import re

import requests
from requests.packages.urllib3 import exceptions
import requests_cache
from sqlalchemy.orm.exc import DetachedInstanceError

from ckanext.dgu.bin.running_stats import Stats
from ckanext.dgu.model import govuk_publications as govuk_pubs_model
import ckan.logic as logic
from ckan import model


class GovukPublicationLinks(object):

    @classmethod
    def init(cls):
        if 'requests' not in dir(cls):
            cls.requests = requests_cache.CachedSession(
                'govuk_pubs', expire_after=60*60*24*30)  # 30 days
            cls.reset_stats()

    @classmethod
    def fix_local_resources(cls, resource_id=None, dataset_name=None):
        """
        Finds local resources that point at a publication and deletes them.  If we
        have the publication record then when we import it we will get all of the
        attachments - making these resources pointing at top level publication
        pages unnecessary.
        """
        stats = Stats()

        # Get the IDs of any resources that link to publications
        publication_links = model.Session.query(govuk_pubs_model.Link)\
            .filter(govuk_pubs_model.Link.ckan_table == 'resource')\
            .filter(govuk_pubs_model.Link.govuk_table == 'publication').all()

        commit = False

        # For each resource id delete it and the link to the publication as
        # if we have a publication, we will pick up all of the attachments
        # anyway.
        for publication_link in publication_links:
            commit = True
            resource = model.Resource.get(publication_link.ckan_id)

            stats.add("Removing resource", resource.id)
            stats.add("Removing resource->publication link", publication_link.id)

            model.Session.delete(publication_link)
            model.Session.delete(resource)

            model.Session.commit()

        print stats

    @classmethod
    def _find_collections_for_publications(cls, objects_to_link):
        publications = [obj[1] for obj in objects_to_link if obj[0] == govuk_pubs_model.Publication]

        print publications

        return objects_to_link

    @classmethod
    def autolink(cls, resource_id=None, dataset_name=None):
        '''autolink - Find clear links between gov.uk and DGU'''
        # requests should not print InsecurePlatformWarning
        warnings.simplefilter("ignore", exceptions.InsecurePlatformWarning)

        stats = Stats()
        resources = get_resources(resource_id=resource_id, dataset_name=dataset_name)
        urls_that_redirect_matcher = get_urls_that_redirect_matcher()

        publications = set()
        collections = set()

        for res in resources:
            try:
                pkg = res.resource_group.package
            except DetachedInstanceError:
                # looks like we've just committed, so re-get the resource
                res = model.Resource.get(res.id)
                pkg = res.resource_group.package

            res_identity = '%s.%s' % (pkg.name, res.position)

            # Find the links
            dataset_id = res.resource_group.package.id
            objs_to_link = cls.find_govuk_objs_to_autolink(res.url, res.id, dataset_id)
            for p in [obj[1] for obj in objs_to_link if obj[0] == govuk_pubs_model.Publication]:
                publications.add(p)
                for c in p.collections:
                    collections.add(c)

            # Sometimes the URL has been moved - look for redirect (#195)
            if not objs_to_link and urls_that_redirect_matcher.match(res.url):
                response = requests.head(res.url)
                if response.headers.get('location'):
                    objs_to_link = cls.find_govuk_objs_to_autolink(response.headers['location'], res.id, dataset_id)
                    print stats.add(
                        'URL redirected (%s link)' %
                        ('could' if objs_to_link else 'could NOT'),
                        res_identity)

            # Update the Link objects
            existing_links = model.Session.query(govuk_pubs_model.Link) \
                                  .filter_by(ckan_table='resource') \
                                  .filter_by(ckan_id=res.id) \
                                  .all()
            existing_link_ids = [(link.govuk_id, link.ckan_id) for link in existing_links]
            outcomes = defaultdict(list)
            needs_commit = False
            for govuk_type, obj, ckan_type, ckan_id in objs_to_link:
                if (obj.govuk_id, ckan_id) in existing_link_ids:
                    outcomes['%s-%s' % (govuk_type.__name__.lower(), ckan_type)].append('unchanged')
                    existing_link_ids.remove((obj.govuk_id, ckan_id))
                else:
                    link = govuk_pubs_model.Link(
                        govuk_table=govuk_type.__tablename__,
                        govuk_id=obj.govuk_id,
                        ckan_table=ckan_type,
                        ckan_id=ckan_id)
                    model.Session.add(link)
                    needs_commit = True
                    print 'LINK', link
                    outcomes['%s-%s' % (govuk_type.__name__.lower(), ckan_type)].append('added')
            if existing_link_ids:
                for link in existing_links:
                    if (link.govuk_id, ckan_id) in existing_link_ids:
                        outcomes['%s-%s' % (link.govuk_table, link.ckan_table)].append('removed')
                        model.Session.delete(link)
                        needs_commit = True
            if outcomes:
                outcomes_strs = ['%s %s' % (govuk_type,
                                            '/'.join(outcomes[govuk_type]))
                                 for govuk_type in outcomes.keys()]
                stats.add('Link %s' % ', '.join(outcomes_strs), res_identity)
            else:
                stats.add('No links', res_identity)

            if needs_commit:
                model.Session.commit()
                model.Session.remove()


        dataset_pubs = set([p.id for p in publications])
        if collections:
            c = next(iter(collections))
            allpubs = set()

            collection = model.Session.query(govuk_pubs_model.Collection)\
                .filter(govuk_pubs_model.Collection.id==c.id).first()
            for pub in collection.publications:
                allpubs.add(pub.id)

            diff_count = len(allpubs - dataset_pubs)
            print "Difference in publications between dataset and collection: ", diff_count
            print "50% of collection pubs", (len(allpubs) / 2.0)
            if diff_count < (len(allpubs) / 2.0):
                # We use the URL for the Collection (as unique govuk id) and so
                # this will only return collections
                existing_count = model.Session.query(govuk_pubs_model.Link)\
                    .filter(govuk_pubs_model.Link.govuk_id == c.url)\
                    .filter(govuk_pubs_model.Link.ckan_id == dataset_name)\
                    .filter(govuk_pubs_model.Link.ckan_table == 'dataset')\
                    .count()
                if not existing_count:
                    link = govuk_pubs_model.Link(
                        govuk_table="collection",
                        govuk_id=c.url,
                        ckan_table="dataset",
                        ckan_id=dataset_name)
                    model.Session.add(link)
                    model.Session.commit()
                    print "LINK", link
                    stats.add('Collection-Dataset link added', link)



        print stats

    @classmethod
    def find_govuk_objs_to_autolink(cls, res_url, res_id, dataset_id):
        objs_to_link = []
        publications = set()
        # First look for links from the Resource to the Publication or Attachment
        for govuk_type in (govuk_pubs_model.Publication,
                           govuk_pubs_model.Attachment):
            objs_to_link_ = model.Session.query(govuk_type) \
                                 .filter_by(url=res_url) \
                                 .all()
            if objs_to_link_:
                objs_to_link.extend([(govuk_type, obj, 'resource', res_id)
                                     for obj in objs_to_link_])

                # If Resource is linked, also link its Dataset to the Publication
                if govuk_type == govuk_pubs_model.Publication:
                    publications |= set(objs_to_link_)
                elif govuk_type == govuk_pubs_model.Attachment:
                    publications |= set(attachment.publication
                                        for attachment in objs_to_link_)
                objs_to_link.extend([(govuk_pubs_model.Publication, publication,
                                      'dataset', dataset_id)
                                     for publication in publications])

        return objs_to_link


def publication_link_to_dataset(pkg_id, pub_id):
    return model.Session.query(govuk_pubs_model.Link)\
            .filter(govuk_pubs_model.Link.ckan_id == pkg_id )\
            .filter(govuk_pubs_model.Link.ckan_table == "package")\
            .filter(govuk_pubs_model.Link.govuk_table == "publication")\
            .filter(govuk_pubs_model.Link.govuk_id == pub_id).first()


def publication_link_from_resource(resource_id):
    return model.Session.query(govuk_pubs_model.Link)\
                        .filter(govuk_pubs_model.Link.ckan_id == resource_id )\
                        .filter(govuk_pubs_model.Link.ckan_table == "resource")\
                        .filter(govuk_pubs_model.Link.govuk_table == "publication").first()

def get_packages_and_resources(resource_id=None, dataset_name=None, url_like='https:\/\/www.gov.uk\/%'):
    ''' Returns all gov.uk resource ids grouped by the package_ids.'''
    from ckan import model
    resources = model.Session.query(model.Resource.id, model.Package.id) \
                .filter_by(state='active') \
                .filter(model.Resource.url.like(url_like)) \
                .join(model.ResourceGroup) \
                .join(model.Package) \
                .filter_by(state='active')
    criteria = ['gov.uk']
    if dataset_name:
        resources = resources.filter(model.Package.name==dataset_name)
        criteria.append('Dataset:%s' % dataset_name)
    if resource_id:
        resources = resources.filter(model.Resource.id==resource_id)
        criteria.append('Resource:%s' % resource_id)

    results = defaultdict(list)
    for r, p in resources.all():
        results[p].append(r)

    return results

def get_resources(resource_id=None, dataset_name=None):
    ''' Returns all gov.uk resources, or filtered by the given criteria. '''
    from ckan import model
    resources = model.Session.query(model.Resource) \
                .filter_by(state='active') \
                .filter(model.Resource.url.like('https:\/\/www.gov.uk\/%')) \
                .join(model.ResourceGroup) \
                .join(model.Package) \
                .filter_by(state='active')
    criteria = ['gov.uk']
    if dataset_name:
        resources = resources.filter(model.Package.name==dataset_name)
        criteria.append('Dataset:%s' % dataset_name)
    if resource_id:
        resources = resources.filter(model.Resource.id==resource_id)
        criteria.append('Resource:%s' % resource_id)
    resources = resources.all()
    print '%i resources (%s)' % (len(resources), ' '.join(criteria))
    return resources


def get_urls_that_redirect_matcher():
    return re.compile('https://www.gov.uk/government/(publications)')
