import json
import logging
import os
import pylons
import re
import sqlalchemy
import urlparse
import datetime
import urllib
import shutil
import uuid

from pylons import config
from ckan.lib.helpers import flash_success, flash_error
from ckanext.dgu.lib import helpers as dgu_helpers
from ckan.lib.base import BaseController, model, abort, h, redirect
from ckanext.dgu.plugins_toolkit import request, c, render, _, NotAuthorized, get_action
from ckanext.dgu.lib.home import get_themes


log = logging.getLogger(__name__)

class DataController(BaseController):
    def __before__(self, action, **env):
        try:
            BaseController.__before__(self, action, **env)
        except NotAuthorized:
            abort(401, _('Not authorized to see this page'))
        except (sqlalchemy.exc.ProgrammingError,
                sqlalchemy.exc.OperationalError), e:
            # postgres and sqlite errors for missing tables
            msg = str(e)
            if ('relation' in msg and 'does not exist' in msg) or \
                   ('no such table' in msg) :
                # table missing, major database problem
                abort(503, _('This site is currently off-line. Database is not initialised.'))
                # TODO: send an email to the admin person (#1285)
            else:
                raise

    def home(self):
        extra_vars = {}

        # Get the dataset count using search
        # (shouldn't cache, as it makes it more likely to be out of sync with
        # the data page)
        from ckan.lib.search import SearchError, SearchQueryError
        context = {'model': model, 'session': model.Session,
                   'user': c.user or c.author, 'for_view': True,
                   'auth_user_obj': c.userobj}
        data_dict = {
                'q': '*:*',
                'fq': '+dataset_type:dataset',
                #'facet.field': facets.keys(),
                'rows': 0,
            }
        query = get_action('package_search')(context, data_dict)
        extra_vars['num_datasets'] = query['count']

        extra_vars['themes'] = get_themes()

        return render('data/home.html', extra_vars=extra_vars)

    def linked_data_admin(self):
        """
        Instructions for installing Ruby via RVM:

            \curl -sSL https://get.rvm.io | bash -s stable
            # Comment out lines in .bashrc and .bash_profile
            source "$HOME/.rvm/scripts/rvm"
            rvm autolibs distable
            rvm install 1.9.3
            rvm use 1.9.3
            rvm gemset create ukgovld
            rvm alias create ukgovldwg 1.9.3@ukgovld
            cd /vagrant/src/ckanext-dgu/
            ~/.rvm/wrappers/ukgovldwg/bundle
            rvm wrapper ukgovldwg jekyll

        """
        import git

        if not dgu_helpers.is_sysadmin() and not c.user in ['user_d24373', 'user_d102361']:
            abort(401)

        prefix = 'dgu.jekyll.ukgovld.'
        c.repo_url = pylons.config.get(prefix + "repo.url", None)
        c.repo_branch = pylons.config.get(prefix + "repo.branch", None)
        source_repo_path = pylons.config.get(prefix + "local.source", None)
        build_path = pylons.config.get(prefix + "local.build", None)
        deploy_path = pylons.config.get(prefix + "local.deploy", None)

        if source_repo_path and (not os.path.exists(source_repo_path) and
                source_repo_path.startswith('/tmp/')):
            # Directories in /tmp won't survive a reboot
            os.makedirs(source_repo_path)

        if build_path and (not os.path.exists(build_path) and build_path.startswith('/tmp/')):
            # Directories in /tmp won't survive a reboot
            os.makedirs(build_path)

        if not all([c.repo_url, c.repo_branch, source_repo_path, build_path,
                    deploy_path]) or \
                not os.path.exists(source_repo_path):
            c.error = "System not configured, please setup ckan.ini"
            if source_repo_path and not os.path.exists(source_repo_path):
                c.error = "Repo path %s does not exist" % source_repo_path
            return render('data/ukgovld.html')

        # Ensure repo exists locally
        try:
            repo = git.Repo(source_repo_path)
        except git.InvalidGitRepositoryError, e:
            repo = git.Repo.init(source_repo_path)
            repo.create_remote('origin', c.repo_url)

        # Get updates from the repo
        repo.git.fetch()
        repo.git.checkout(c.repo_branch)
        repo.git.rebase()
        repo.git.branch("--set-upstream", "gh-pages", "origin/gh-pages")

        # Get the repo's current commit (we call it: repo_status)
        latest_remote_commit = repo.head.commit
        latest_when = datetime.datetime.fromtimestamp(int(latest_remote_commit.committed_date)).strftime('%H:%M %d-%m-%Y')
        c.repo_status = '"%s" %s (%s)' % (latest_remote_commit.message,
                                          latest_when, str(latest_remote_commit)[:8])

        index_html_filepath = os.path.join(deploy_path, 'index.html')
        repo_status_filepath = os.path.join(build_path, 'repo_status.txt')
        status_filepath = os.path.join(deploy_path, 'repo_status.txt')

        if request.method == "POST":
            def get_exitcode_stdout_stderr(cmd):
                import shlex
                from subprocess import Popen, PIPE
                import ckanext.dgu

                cwd = os.path.abspath(os.path.join(ckanext.dgu.__file__, "../../../"))

                args = shlex.split(cmd)
                log.debug('Running command: %r', args)
                my_env = os.environ.copy()
                my_env['LANG'] = 'en_GB.UTF-8'
                proc = Popen(args, stdout=PIPE, stderr=PIPE, cwd=cwd, env=my_env)
                out, err = proc.communicate()
                exitcode = proc.returncode
                return exitcode, out, err
            cmd_line = '/home/co/.rvm/wrappers/ukgovldwg/jekyll build --source "%s" --destination "%s"'\
                       % (source_repo_path, build_path)
            c.exitcode, out, err = get_exitcode_stdout_stderr(cmd_line)
            c.stdout = cmd_line + '<br/><br/>' + out.replace('\n','<br/>')
            c.stderr = err.replace('\n','<br/>')
            if c.exitcode == 0:
                # If successful, write the repo_status to a file so that
                # we can see what commit was published.
                try:
                    with open(repo_status_filepath, 'w') as f:
                        f.write(c.repo_status)
                except Exception, e:
                    # e.g. permission error, when running in paster
                    log.exception(e)

        if c.exitcode == 0 and deploy_path and os.path.exists(deploy_path):
            # Use distutils to copy the entire tree, shutil will likely complain
            import distutils.core
            try:
                distutils.dir_util.copy_tree(build_path, deploy_path)
            except Exception, e:
                log.exception(e)
                c.deploy_error = 'Site not deployed - error with deployment: %r' % e.args

        c.last_deploy = 'Never'
        if os.path.exists(index_html_filepath):
            s = os.stat(index_html_filepath)
            c.last_deploy = datetime.datetime.fromtimestamp(int(s.st_mtime)).strftime('%H:%M %d-%m-%Y')
            if os.path.exists(status_filepath):
                with open(status_filepath, 'r') as f:
                    c.deploy_status = f.read()

        if c.exitcode == 1:
            c.deploy_error = "Site not deployed, Jekyll did not complete successfully."

        return render('data/ukgovld.html')

    def api(self):
        return render('data/api.html')

    def system_dashboard(self):
        if not dgu_helpers.is_sysadmin():
            abort(401, 'User must be a sysadmin to view this page.')
        return render('data/system_dashboard.html')

    def _set_openspending_reports_dir(self):
        c.openspending_report_dir = os.path.expanduser(pylons.config.get(
            'dgu.openspending_reports_dir',
            '/var/lib/ckan/dgu/openspending_reports'))

    def openspending_report(self):
        self._set_openspending_reports_dir()
        c.content = open (c.openspending_report_dir + "/index.html").read()
        return render('data/openspending_report.html')

    def openspending_publisher_report(self, id):
        id = id.replace('.html', '')
        if id.startswith('publisher-'):
            publisher_name = id.replace('publisher-', '')
            # Check the publisher actually exists, for security
            publisher = model.Group.by_name(publisher_name)
            if publisher:
                c.report_name = id
            else:
                abort(404, 'Publisher not found')
            self._set_openspending_reports_dir()

            path = c.openspending_report_dir + "/" + c.report_name + ".html"
            c.content = open(path).read()
            # Jinja needs it as unicode
            c.content = c.content.decode('utf8')
            return render('data/openspending_publisher_report.html')
        else:
            abort(404)

    def viz_social_investment_and_foundations(self):
        return render('viz/social_investment_and_foundations.html')

    def viz_investment_readiness_programme(self):
        return render('viz/investment_readiness_programme.html')

    def contracts_archive(self, relative_url='/'):
        import requests
        from pylons import response

        if request.method == 'POST':
            abort(405) # Method Not Allowed

        headers = {'X-Script-Name': '/data/contracts-finder-archive'}
        contracts_url = pylons.config.get('dgu.contracts_url')
        url = urlparse.urljoin(contracts_url, relative_url)
        r = requests.get(url,
                         headers=headers,
                         params=dict(request.params),
                         stream=True)

        if r.status_code != 200:
            abort(r.status_code)

        if relative_url.startswith(('/static/', '/download/')):
            # CSS will only get loaded if it has the right content type
            response.content_type = r.headers.get('Content-Type', 'text/html')
            if r.headers.get('Content-Disposition'):
                response.headers['Content-Disposition'] = r.headers.get('Content-Disposition')
            return r.raw.read() # Some of the static files are binary
        else:
            extra_vars = {'content': r.text}
            return render('contracts_archive/front_page.html',
                          extra_vars=extra_vars)

    def resource_cache(self, root, resource_id, filename):
        """
        Called when a request is made for an item in the resource cache and
        is responsible for rendering the data.  When the data to be rendered
        is HTML it will add a header to show that the content is cached, and
        set a <base> header if not present to make sure all relative links are
        resolved correctly.
        """
        from pylons import response
        from paste.fileapp import FileApp
        from ckanext.dgu.lib.helpers import tidy_url
        from ckanext.qa.model import QA

        archive_root = pylons.config.get('ckanext-archiver.archive_dir')
        if not archive_root:
            # Bad configuration likely to cause this.
            abort(404, "Could not find archive folder")

        resource = model.Resource.get(resource_id)

        fmt = ""
        if resource:
            qa = QA.get_for_resource(resource.id)
            if qa:
                fmt = qa.format

        is_html = fmt == "HTML"

        filepath = os.path.join(archive_root, root, resource_id, filename).encode('utf-8')
        filepath = urllib.quote(filepath)
        if not os.path.exists(filepath):
            abort(404, "Resource is not cached")

        file_size = os.path.getsize(filepath)
        if not is_html:
            # Content-Type is determined by FileApp based on the extension.
            # Using the format provided by QA isn't an option currently as
            # for zip files it gives the format of the content of the zip.
            headers = [('Content-Length', str(file_size))]
            fapp = FileApp(filepath, headers=headers)
            return fapp(request.environ, self.start_response)

        origin = tidy_url(resource.url)
        parts = urlparse.urlparse(origin)
        url = "{0}://{1}".format(parts.scheme, parts.netloc)
        base_string = "<head><base href='{0}'>".format(url)

        response.headers['Content-Type'] = 'text/html; charset=utf-8'
        try:
            f = open(filepath, "r")
        except IOError:
            log.error('Error reading resource cache file: %s', filepath)
            abort(403, "The system was unable to read this resource from the cache. Admins have been notified")

        content = f.read()
        f.close()

        if not re.search("<base ", content, re.IGNORECASE):
            compiled_head = re.compile(re.escape("<head>"), re.IGNORECASE)
            content = compiled_head.sub( base_string, content, re.IGNORECASE)

        if not '__archiver__cache__header__' in content:
            # We should insert our HTML block at the bottom of the page with
            # the appropriate CSS to render it at the top.  Easier to insert
            # before </body>.
            c.url = resource.url
            replacement = render("data/cache_header.html")
            try:
                compiled_body = re.compile(re.escape("</body>"), re.IGNORECASE)
                content = compiled_body.sub( "{0}</body>".format(replacement), content, re.IGNORECASE)
            except Exception, e:
                log.warn("Failed to do the replacement in resource<{0}> and file: {1}".format(resource.id, filepath))
                return

        response.write(content)

    def viz_upload(self):
        """
        Provides direct upload to DGU for users in specific publishers.
        This is specifically for the social investment publishers so that
        they can host their files somewhere.
        """
        import ckan.model as model

        ALLOWED_PUBLISHERS = set([
            'seedbed'
            'health-social-ventures',
            'big-issue-cooperate',
            'social-incubator-east',
            'young-academy',
            'dotforge-social-ventures',
            'wayra-unltd',
            'social-incubator-north',
            'bethnal-green-ventures',
            'hub-launchpad',
            'the-social-investment-business-group',
        ])

        # Check auth .. user must be in one of selected groups.
        context = {"model": model, "session": model.Session, "user": c.user}

        if dgu_helpers.is_sysadmin():
            user_orgs = ALLOWED_PUBLISHERS
        else:
            res = get_action("organization_list_for_user")(context, {"permission": "create_dataset"})
            user_orgs = set([o['name'] for o in res]) & ALLOWED_PUBLISHERS

        if not user_orgs:
            abort(401)

        publisher_q = " OR ".join(["publisher:{}".format(o) for o in user_orgs])
        res = get_action("package_search")(context, {"fq": "({})".format(publisher_q), 'rows': 100})

        c.package_names = [(p['name'],u"{} ({})".format(p['title'], p['organization']['title']),) for p in res['results']]
        if not c.package_names:
            flash_error("There are no datasets available in your organisation. You will be unable to upload.")
            return render('viz/upload.html')

        c.package_names = sorted(c.package_names)

        if request.method == 'POST':
            success, errors = self._validate_viz_upload(request.POST)
            c.title = request.POST.get('title', '')
            c.format = request.POST.get('format', '')
            c.dataset = request.POST.get('dataset', '')

            if not success:
                error_list = "<li>" + "</li><li>".join(errors) + "</li>"
                flash_error('There was a problem with your submission<br/><ul>{}</ul>'.format(error_list), allow_html=True)
                return render('viz/upload.html')

            extension, url = self._store_file(request.POST['upload'], c.dataset)
            if not c.format:
                c.format = extension[1:].upper()

            # Create resource
            resource = {
                u'description': c.title,
                u'url': url,
                u'format': c.format
            }

            # Show and update package
            pkg = get_action('package_show')(context, {'id': c.dataset})
            pkg['resources'].append(resource)
            res = get_action('package_update')(context, pkg)
            log.info('Added viz to dataset %s: %s', pkg['name'], resource)

            flash_success('The file has been uploaded and added to the dataset. <a href="/dataset/{}" style="text-decoration:underline;">View dataset</a>'.format(c.dataset), allow_html=True)
            return redirect('/data/viz/upload')

        return render('viz/upload.html')

    def _store_file(self, fileobj, dataset_name):
        """ Given a file upload, and a dataset name, this method will work
            out where to save the file and return a tuple of the extension
            and the url where it will be served from
        """
        root = config.get('ckan.resource.store', '/tmp')

        _, filename = os.path.split(fileobj.filename)
        url_target = os.path.join( dataset_name, str(uuid.uuid4()), filename)
        target = os.path.join( root, url_target)

        _, extension = os.path.splitext(target)

        directory = os.path.dirname(target)
        if not os.path.exists(directory):
            os.makedirs(directory)

        input_file = request.POST['upload'].file
        input_file.seek(0)

        with open(target, 'wb') as output_file:
            shutil.copyfileobj(input_file, output_file)

        return (extension, "{}/data/resource/{}".format(config['ckan.site_url'], url_target),)

    def _validate_viz_upload(self, data_dict):
        errors = []

        if not 'upload' in data_dict or not hasattr(data_dict['upload'], "filename"):
            errors.append("No file was selected for upload")
        if not data_dict.get('title'):
            errors.append("No title was provided")
        if not data_dict.get('dataset'):
            errors.append("No dataset was selected")
        return len(errors) == 0, errors


