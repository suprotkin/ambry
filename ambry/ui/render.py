"""Support for creating web pages and text representations of schemas."""

import os
from flask.json import JSONEncoder as FlaskJSONEncoder
from . import memoize
from flask.json import dumps
from flask import Response

import jinja2.tests

##
# These are in later versions of jinja, but we need them in earlier ones.
if 'equalto' not in jinja2.tests.TESTS:
    def test_equalto(value, other):
        return value == other

    jinja2.tests.TESTS['equalto'] = test_equalto

if 'isin' not in jinja2.tests.TESTS:
    def test_isin(value, other):
        return value in other

    jinja2.tests.TESTS['isin'] = test_isin


def pretty_time(s):
    """Pretty print time in seconds.

    From:
    http://stackoverflow.com/a/24542445/1144479

    """

    intervals = (
        ('weeks', 604800),  # 60 * 60 * 24 * 7
        ('days', 86400),  # 60 * 60 * 24
        ('hours', 3600),  # 60 * 60
        ('minutes', 60),
        ('seconds', 1),
    )

    def display_time(seconds, granularity=2):
        result = []

        for name, count in intervals:
            value = seconds // count
            if value:
                seconds -= value * count
                if value == 1:
                    name = name.rstrip('s')
                result.append("{} {}".format(value, name))

        return ', '.join(result[:granularity])

    for i, (name, limit) in enumerate(intervals):

        if s > limit:
            return display_time(int(s), 4 - i)


def resolve(t):

    from ambry.identity import Identity
    from ambry.orm import Table
    from ambry.warehouse.manifest import Manifest

    if isinstance(t, basestring):
        return t
    elif isinstance(t, (Identity, Table)):
        return t.vid
    elif isinstance(t, (Identity, Table)):
        return t.vid
    elif isinstance(t, Manifest):
        return t.uid
    elif isinstance(t, dict):
        if 'identity' in t:
            return t['identity'].get('vid', None)
        else:
            return t.get('vid', None)
    else:
        return None

# Path functions, for generating URL paths.


def bundle_path(b):
    return "/bundles/{}.html".format(resolve(b))


def schema_path(b, format):
    return "/bundles/{}/schema.{}".format(resolve(b), format)


def table_path(b, t):
    return "/bundles/{}/tables/{}.html".format(resolve(b), resolve(t))


def proto_vid_path(pvid):

    b, t, c = deref_tc_ref(pvid)

    return table_path(str(b), str(t))


def deref_tc_ref(ref):
    """Given a column or table, vid or id, return the object."""
    from ambry.identity import ObjectNumber

    on = ObjectNumber.parse(ref)

    b = str(on.as_dataset)

    try:
        c = on
        t = on.as_table
    except AttributeError:
        t = on
        c = None

    if not on.revision:
        # The table does not have a revision, so we need to get one, just get
        # the latest one
        from . import renderer

        r = renderer()
        dc = r.doc_cache

        tm = dc.table_version_map()

        t_vid = reversed(sorted(tm.get(str(t)))).next()

        t = ObjectNumber.parse(t_vid)
        b = t.as_dataset

        if c:
            c = c.rev(t.revision)

    return b, t, c


def tc_obj(ref):
    """Return an object for a table or column."""
    from . import renderer

    b, t, c = deref_tc_ref(ref)

    dc = renderer().doc_cache

    table = dc.table(str(t))

    if c:

        if not table:
            print '!!! in tc_obj, No table for ', str(t)

        try:
            return table['columns'][str(c.rev(0))]
        except KeyError:
            return None
        except TypeError:

            return None
    else:
        return table


def partition_path(b, p=None):

    if p is None:
        from ambry.identity import ObjectNumber
        p = b
        on = ObjectNumber.parse(p)
        try:
            b = str(on.as_dataset)
        except AttributeError:
            # b = str(on)
            raise
    return "/bundles/{}/partitions/{}.html".format(resolve(b), resolve(p))


def manifest_path(m):
    return "/manifests/{}.html".format(m)


def store_path(s):
    return "/stores/{}.html".format(s)


def store_table_path(s, t):
    return "/stores/{}/tables/{}.html".format(s, t)


def extract_url(s, t, format):

    from flask import url_for

    return url_for('get_extract', wid=s, tid=t, ct=format)


def db_download_url(base, s):
    return os.path.join(base, 'download', s + '.db')


def extractor_list(t):
    from . import renderer

    return ['csv', 'json'] + \
        (['kml', 'geojson'] if t.get('is_geo', False) else [])


class extract_entry(object):

    def __init__(self, extracted, completed, rel_path, abs_path, data=None):
        self.extracted = extracted
        # For deleting files where exception thrown during generation
        self.completed = completed
        self.rel_path = rel_path
        self.abs_path = abs_path
        self.data = data

    def __str__(self):
        return 'extracted={} completed={} rel={} abs={} data={}'.format(
            self.extracted,
            self.completed,
            self.rel_path,
            self.abs_path,
            self.data)


class JSONEncoder(FlaskJSONEncoder):

    def default(self, o):

        return str(type(o))

        # return FlaskJSONEncoder.default(self, o)


class Renderer(object):

    def __init__(self, content_type='html', blueprints=None):

        from jinja2 import Environment, PackageLoader

        try:
            from ambry.library import new_library

            self.library = new_library()
            self.doc_cache = self.library.doc_cache
        except:
            raise

        self.css_files = ['css/style.css', 'css/pygments.css']

        self.env = Environment(loader=PackageLoader('ambry.ui', 'templates'))

        self.extracts = []

        # Set to true to get Render to return json instead
        self.content_type = content_type

        self.blueprints = blueprints

        # Monkey patch to get the equalto test

    def maybe_render(self, rel_path, render_lambda, metadata={}, force=False):
        """Check if a file exists and maybe render it."""

        if rel_path[0] == '/':
            rel_path = rel_path[1:]

        if rel_path.endswith('.html'):
            metadata['content-type'] = 'text/html'

        elif rel_path.endswith('.css'):
            metadata['content-type'] = 'text/css'

        try:
            if not self.cache.has(rel_path) or force:

                with self.cache.put_stream(rel_path, metadata=metadata) as s:
                    t = render_lambda()
                    if t:
                        s.write(t.encode('utf-8'))
                extracted = True
            else:
                extracted = False

            completed = True

        except:
            completed = False
            extracted = True
            raise

        finally:
            self.extracts.append(
                extract_entry(
                    extracted,
                    completed,
                    rel_path,
                    self.cache.path(rel_path)))

    def cc(self):
        """return common context values."""
        from functools import wraps

        # Add a prefix to the URLs when the HTML is generated for the local
        # filesystem.
        # def prefix_root(r, f):
        #     @wraps(f)
        #     def wrapper(*args, **kwds):
        #         return os.path.join(r, f(*args, **kwds))
        #     return wrapper

        return {
            'pretty_time': pretty_time,
            'from_root': lambda x: x,
            'bundle_path': bundle_path,
            'schema_path': schema_path,
            'table_path': table_path,
            'partition_path': partition_path,
            'manifest_path': manifest_path,
            'store_path': store_path,
            'store_table_path': store_table_path,
            'proto_vid_path': proto_vid_path,
            'extractors': extractor_list,
            'tc_obj': tc_obj,
            'extract_url': extract_url,
            'db_download_url': db_download_url,
            'bundle_sort': lambda l,
            key: sorted(l, key=lambda x: x['identity'][key])}

    def render(self, template, *args, **kwargs):

        if self.content_type == 'json':
            return Response(dumps(dict(**kwargs), cls=JSONEncoder, indent=4), mimetype='application/json')
        else:
            return template.render(*args, **kwargs)

    def compiled_times(self):
        """Compile all of the time entried from cache calls to one per key."""
        return self.doc_cache.compiled_times()

    def clean(self):
        """Clean up the extracts on failures."""
        for e in self.extracts:
            if e.completed is False and os.path.exists(e.abs_path):
                os.remove(e.abs_path)

    def error500(self, e):
        template = self.env.get_template('500.html')

        return self.render(template, e=e, **self.cc())

    def index(self, term=None):

        template = self.env.get_template('index.html')

        return self.render(
            template,
            l=self.doc_cache.library_info(),
            **self.cc())

    def bundles_index(self):
        """Render the bundle Table of Contents for a library."""
        template = self.env.get_template('toc/bundles.html')

        bundles = self.doc_cache.bundle_index()

        return self.render(template, bundles=bundles, **self.cc())

    def tables_index(self):

        template = self.env.get_template('toc/tables.html')

        tables = self.doc_cache.get_tables()

        return self.render(template, tables=tables, **self.cc())

    def bundle(self, vid):
        """Render documentation for a single bundle."""

        template = self.env.get_template('bundle/index.html')

        b = self.doc_cache.bundle(vid)

        for p in b['partitions'].values():
            p['description'] = b['tables'][
                p['table_vid']].get(
                'description',
                '')

        return self.render(template, b=b, **self.cc())

    def bundle_summary(self, vid):
        """Render documentation for a single bundle."""

        template = self.env.get_template('bundle/index.html')

        b = self.doc_cache.bundle_summary(vid)

        return self.render(template, b=b, **self.cc())

    def schemacsv(self, vid):
        """Render documentation for a single bundle."""
        from flask import make_response

        response = make_response(self.doc_cache.get_schemacsv(vid))

        response.headers[
            "Content-Disposition"] = "attachment; filename={}-schema.csv".format(vid)

        return response

    def schema(self, vid):
        """Render documentation for a single bundle."""
        from csv import reader
        from StringIO import StringIO
        import json

        template = self.env.get_template('bundle/schema.html')

        b_data = self.doc_cache.bundle(vid)

        b = self.library.bundle(vid)

        reader = reader(StringIO(b.schema.as_csv()))

        del b_data['partitions']
        del b_data['tables']

        schema = dict(header=reader.next(), rows=[x for x in reader])

        return self.render(template, b=b_data, schema=schema, **self.cc())

    def table(self, bvid, tid):

        template = self.env.get_template('table.html')

        b = self.doc_cache.bundle(bvid)

        del b['partitions']
        del b['tables']

        t = self.doc_cache.table(tid)

        return self.render(template, b=b, t=t, **self.cc())

    def partition(self, pvid):
        from geoid.civick import GVid

        template = self.env.get_template('bundle/partition.html')

        p = self.doc_cache.partition(pvid)

        p['table'] = self.doc_cache.table(p['table_vid'])

        if 'geo_coverage' in p:

            all_idents = self.library.search.identifier_map

            for gvid in p['geo_coverage']['vids']:
                try:
                    p['geo_coverage']['names'].append(all_idents[gvid])
                except KeyError:
                    g = GVid.parse(gvid)
                    try:
                        phrase = "All {} in {} ".format(
                            g.level_plural.title(), all_idents[str(g.promote())])
                        p['geo_coverage']['names'].append(phrase)
                    except KeyError:
                        pass

        return self.render(template, p=p, **self.cc())

    def store(self, uid):

        template = self.env.get_template('store/index.html')

        store = self.doc_cache.warehouse(uid)

        assert store

        # Update the manifest to get the whole object
        store['manifests'] = {
            uid: self.doc_cache.manifest(uid) for uid in store['manifests']}

        return self.render(template, s=store, **self.cc())

    def store_table(self, uid, tid):

        template = self.env.get_template('store/table.html')

        # Copy so we don't modify the cached version
        store = dict(self.doc_cache.warehouse(uid).items())

        t = store['tables'][tid]

        del store['partitions']
        del store['manifests']
        del store['tables']

        return self.render(template, s=store, t=t, **self.cc())

    def info(self, app_config, run_config):

        template = self.env.get_template('info.html')

        return self.render(template, app_config=app_config, **self.cc())

    def manifest(self, muid):
        """F is the file object associated with the manifest."""
        from ambry.warehouse.manifest import Manifest
        from ambry.identity import ObjectNumber

        template = self.env.get_template('manifest/index.html')

        m_dict = self.doc_cache.get_manifest(muid)

        m = Manifest(m_dict['text'])

        return self.render(template, m=m,
                           md=m_dict,
                           **self.cc())

    def collections_index(self):
        """Collections/Warehouses."""
        template = self.env.get_template('toc/collections.html')

        collections = {f.ref: dict(
            title=f.data['title'],
            summary=f.data['summary'] if f.data['summary'] else '',
            dsn=f.path,
            manifests=[m.ref for m in f.linked_manifests],
            cache=f.data['cache'],
            class_type=f.type_) for f in self.library.stores}

        return self.render(template, collections=collections, **self.cc())

    @property
    def css_dir(self):
        import ambry.ui.templates as tdir

        return os.path.join(os.path.dirname(tdir.__file__), 'css')

    def css_path(self, name):
        import ambry.ui.templates as tdir

        return os.path.join(os.path.dirname(tdir.__file__), 'css', name)

    @property
    def js_dir(self):
        import ambry.ui.templates as tdir

        return os.path.join(os.path.dirname(tdir.__file__), 'js')

    def place_search(self, term):
        """Incremental search, search as you type."""

        results = []
        for score, gvid, name in self.library.search.search_identifiers(term):
            # results.append({"label":name, "value":gvid})
            results.append({"label": name})

        return Response(
            dumps(
                results,
                cls=JSONEncoder,
                indent=4),
            mimetype='application/json')

    def bundle_search(self, terms):
        """Incremental search, search as you type."""

        from geoid.civick import GVid

        results = []

        (b_query, p_query, terms), bp_set = self.library.search.search_bundles(
            {k: v.strip() for k, v in terms.items()})

        pvid_limit = 5

        all_idents = self.library.search.identifier_map

        for bvid, pvids in bp_set.items():

            d = self.doc_cache.dataset(bvid)

            d['partition_count'] = len(pvids)
            d['partitions'] = {}

            for pvid in pvids[:pvid_limit]:

                p = self.doc_cache.partition(pvid)

                p['table'] = self.doc_cache.table(p['table_vid'])

                if 'geo_coverage' in p:
                    for gvid in p['geo_coverage']['vids']:
                        try:

                            p['geo_coverage']['names'].append(all_idents[gvid])

                        except KeyError:
                            g = GVid.parse(gvid)
                            try:
                                phrase = "All {} in {} ".format(
                                    g.level_plural.title(), all_idents[str(g.promote())])
                                p['geo_coverage']['names'].append(phrase)
                            except KeyError:
                                pass

                d['partitions'][pvid] = p

            results.append(d)

        template = self.env.get_template('search/results.html')

        results = sorted(results, key=lambda x: x['vname'])

        # Collect facets to display to the user, for additional sorting
        facets = {
            'years': set(),
            'sources': set(),
            'states': set()
        }

        for r in results:
            facets['sources'].add(r['source'])
            for p in r['partitions'].values():
                if 'time_coverage' in p and p['time_coverage']:
                    facets['years'] |= set(p['time_coverage']['years'])

                if 'geo_coverage' in p:
                    for gvid in p['geo_coverage']['vids']:
                        g = GVid.parse(gvid)

                        if g.level == 'state' and not g.is_summary:
                            # facets['states'].add( (gvid, all_idents[gvid]))
                            facets['states'].add(all_idents[gvid])

        return self.render(
            template,
            queries=dict(
                b_query=b_query,
                p_query=p_query,
                terms=terms),
            results=results,
            facets=facets,
            **self.cc())

    def generate_sources(self):

        lj = self.doc_cache.get_library()

        sources = {}
        for vid, b in lj['bundles'].items():

            source = b['identity']['source']

            if source not in sources:
                sources[source] = {
                    'bundles': {}
                }

            sources[source]['bundles'][vid] = b

        return sources

    def sources(self):

        template = self.env.get_template('sources/index.html')

        sources = self.generate_sources()

        return self.render(template, sources=sources, **self.cc())
