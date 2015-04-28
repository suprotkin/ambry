"""Copyright (c) 2013 Clarinova.

This file is licensed under the terms of the Revised BSD License,
included in this distribution as LICENSE.txt

"""

from ..cli import prt, warn, fatal
from ..identity import LocationRef

# If the devel module exists, this is a development system.
try:
    from ambry.support.devel import *
except ImportError as e:
    from ambry.support.production import *

default_locations = [LocationRef.LOCATION.LIBRARY, LocationRef.LOCATION.REMOTE]


def root_parser(cmd):
    import argparse
    from ..identity import LocationRef

    lr = LocationRef.LOCATION

    sp = cmd.add_parser('list', help='List bundles and partitions')
    sp.set_defaults(command='root')
    sp.set_defaults(subcommand='list')
    sp.add_argument(
        '-P',
        '--plain',
        default=False,
        action="store_true",
        help="Print only vids")
    sp.add_argument(
        '-F',
        '--fields',
        type=str,
        help="Specify fields to use. "
             "One of: 'locations', 'vid', 'status', 'vname', 'sname', 'fqname")
    sp.add_argument(
        '-p',
        '--partitions',
        default=False,
        action="store_true",
        help="Show partitions")
    sp.add_argument(
        '-t',
        '--tables',
        default=False,
        action="store_true",
        help="Show tables")
    sp.add_argument(
        '-a',
        '--all',
        default=False,
        action="store_true",
        help='List everything')
    sp.add_argument(
        '-l',
        '--library',
        default=False,
        action="store_const",
        const=lr.LIBRARY,
        help='List only the library')
    sp.add_argument(
        '-r',
        '--remote',
        default=False,
        action="store_const",
        const=lr.REMOTE,
        help='List only the remote')
    sp.add_argument(
        '-s',
        '--source',
        default=False,
        action="store_const",
        const=lr.SOURCE,
        help='List only the source')
    sp.add_argument(
        '-w',
        '--warehouse',
        default=False,
        action="store_const",
        const='warehouse',
        help='List warehouses')
    sp.add_argument(
        '-c',
        '--collection',
        default=False,
        action="store_const",
        const='collection',
        help='List collections')
    sp.add_argument(
        'term',
        nargs='?',
        type=str,
        help='Name or ID of the bundle or partition')

    sp = cmd.add_parser('info', help='Information about a bundle or partition')
    sp.set_defaults(command='root')
    sp.set_defaults(subcommand='info')
    sp.add_argument(
        '-l',
        '--library',
        default=False,
        action="store_const",
        const=lr.LIBRARY,
        help='Search only the library')
    sp.add_argument(
        '-r',
        '--remote',
        default=False,
        action="store_const",
        const=lr.REMOTE,
        help='Search only the remote')
    sp.add_argument(
        '-s',
        '--source',
        default=False,
        action="store_const",
        const=lr.SOURCE,
        help='Search only the source')
    sp.add_argument(
        '-p',
        '--partitions',
        default=False,
        action="store_true",
        help="Show partitions")
    sp.add_argument(
        'term',
        type=str,
        nargs='?',
        help='Name or ID of the bundle or partition')

    sp = cmd.add_parser('meta', help='Dump the metadata for a bundle')
    sp.set_defaults(command='root')
    sp.set_defaults(subcommand='meta')
    sp.add_argument(
        'term',
        type=str,
        nargs='?',
        help='Name or ID of the bundle or partition')
    sp.add_argument(
        '-k',
        '--key',
        default=False,
        type=str,
        help='Return the value of a specific key')
    group = sp.add_mutually_exclusive_group()
    group.add_argument(
        '-y',
        '--yaml',
        default=False,
        action='store_true',
        help='Output yaml')
    group.add_argument(
        '-j',
        '--json',
        default=False,
        action='store_true',
        help='Output json')
    group.add_argument(
        '-r',
        '--rows',
        default=False,
        action='store_true',
        help='Output key/value pair rows')
    sp.add_argument(
        'terms',
        type=str,
        nargs=argparse.REMAINDER,
        help='Query commands to find packages with. ')

    sp = cmd.add_parser('doc', help='Start the documentation server')
    sp.set_defaults(command='root')
    sp.set_defaults(subcommand='doc')

    sp.add_argument(
        '-c',
        '--clean',
        default=False,
        action="store_true",
        help='When used with --reindex, delete the index and old files first. ')
    sp.add_argument('-d', '--debug', default=False, action="store_true",
                    help='Debug mode ')
    sp.add_argument(
        '-p',
        '--port',
        help='Run on a sepecific port, rather than pick a random one')

    sp = cmd.add_parser('search', help='Search the full-text index')
    sp.set_defaults(command='root')
    sp.set_defaults(subcommand='search')
    sp.add_argument(
        'term',
        type=str,
        nargs=argparse.REMAINDER,
        help='Query term')
    sp.add_argument(
        '-l',
        '--list',
        default=False,
        action="store_true",
        help='List documents instead of search')
    sp.add_argument(
        '-d',
        '--datasets',
        default=False,
        action="store_true",
        help='Search only the dataset index')
    sp.add_argument(
        '-i',
        '--identifiers',
        default=False,
        action="store_true",
        help='Search only the identifiers index')
    sp.add_argument(
        '-p',
        '--partitions',
        default=False,
        action="store_true",
        help='Search only the partitions index')
    sp.add_argument(
        '-R',
        '--reindex',
        default=False,
        action="store_true",
        help='Generate documentation files and index the full-text search')


def root_command(args, rc):
    from ..library import new_library
    from . import global_logger
    from ..dbexceptions import ConfigurationError

    l = new_library(rc.library(args.library_name))
    l.logger = global_logger

    globals()['root_' + args.subcommand](args, l, rc)


def root_list(args, l, rc):
    from ..cli import _print_bundle_list
    from ambry.warehouse.manifest import Manifest
    from . import global_logger
    ##
    # Listing warehouses and collections is different

    if args.collection:

        for f in l.manifests:

            try:
                m = Manifest(f.content)
                print "{:10s} {:25s}| {}".format(m.uid, m.title,
                                                 m.summary['summary_text'])
            except Exception as e:
                warn("Failed to parse manifest {}: {}".format(f.ref, e))
                continue

        return

    if args.warehouse:

        if args.plain:
            fields = []
        else:
            fields = ['title', 'dsn', 'summary', 'url', 'cache']

        format = '{:5s}{:10s}{}'

        def _get(s, f):

            if f == 'dsn':
                f = 'path'

            try:
                return s.data[f] if f in s.data else getattr(s, f)
            except AttributeError:
                return ''

        for s in l.stores:
            print s.ref

            for f in fields:
                if _get(s, f):
                    print format.format('', f, _get(s, f))
        return
    ##
    # The remainder are for listing bundles and partitions.

    if args.tables:
        for table in l.tables:
            print table.name, table.vid, table.dataset.identity.fqname

        return

    if args.plain:
        fields = ['vid']

    elif args.fields:
        fields = args.fields.split(',')

    else:
        fields = ['locations', 'vid', 'vname']

        if args.source:
            fields += ['status']

    locations = filter(bool, [args.library, args.remote, args.source])

    key = lambda ident: ident.vname

    if 'pcount' in fields:
        with_partitions = True
    else:
        with_partitions = args.partitions

    idents = sorted(l.list(with_partitions=with_partitions).values(), key=key)

    if args.term:
        idents = [ident for ident in idents if args.term in ident.fqname]

    if locations:
        idents = [ident for ident in idents if ident.locations.has(locations)]

    _print_bundle_list(idents,
                       fields=fields,
                       show_partitions=args.partitions)


def root_info(args, l, rc):
    from ..cli import _print_info
    from ..dbexceptions import NotFoundError, ConfigurationError
    import ambry

    locations = filter(bool, [args.library, args.remote, args.source])

    if not locations:
        locations = default_locations

    if not args.term:
        print "Version:  {}, {}".format(ambry._meta.__version__, 'production' if IN_PRODUCTION else 'development')
        print "Root dir: {}".format(rc.filesystem('root')['dir'])

        try:
            if l.source:
                print "Source :  {}".format(l.source.base_dir)
        except ConfigurationError:
            print "Source :  No source directory"

        print "Configs:  {}".format(rc.dict['loaded'])

        return

    ident = l.resolve(args.term, location=locations)

    if not ident:
        fatal("Failed to find record for: {}", args.term)
        return

    try:
        b = l.get(ident.vid)

        if not ident.partition:
            for p in b.partitions.all:
                ident.add_partition(p.identity)

    except NotFoundError:
        # fatal("Could not find bundle file for '{}'".format(ident.path))
        pass

    _print_info(l, ident, list_partitions=args.partitions)


def root_meta(args, l, rc):

    ident = l.resolve(args.term)

    if not ident:
        fatal("Failed to find record for: {}", args.term)
        return

    b = l.get(ident.vid)

    meta = b.metadata

    if not args.key:
        # Return all of the rows
        if args.yaml:
            print meta.yaml

        elif args.json:
            print meta.json

        elif args.key:
            for row in meta.rows:
                print '.'.join([e for e in row[0] if e]) + '=' + str(row[1] if row[1] else '')
        else:
            print meta.yaml

    else:

        v = None
        from ..util import AttrDict
        o = AttrDict()
        count = 0

        for row in meta.rows:
            k = '.'.join([e for e in row[0] if e])
            if k.startswith(args.key):
                v = row[1]
                o.unflatten_row(row[0], row[1])
                count += 1

        if count == 1:
            print v

        else:
            if args.yaml:
                print o.dump()

            elif args.json:
                print o.json()

            elif args.rows:
                for row in o.flatten():
                    print '.'.join([e for e in row[0] if e]) + '=' + str(row[1] if row[1] else '')

            else:
                print o.dump()


def root_search(args, l, config):
    # This will fetch the data, but the return values aren't quite right

    term = ' '.join(args.term)

    if args.reindex:

        print 'Updating the identifier'

        # sources = ['census.gov-index-counties', 'census.gov-index-places', 'census.gov-index-states']
        # sources = ['census.gov-index-counties', 'census.gov-index-states']

        records = []

        source = 'civicknowledge.com-terms-geoterms'

        p = l.get(source).partition
        # type = p.table.name

        for row in p.rows:
            records.append(dict(identifier=row['gvid'], type=row['type'], name=row['name']))
        l.search.index_identifiers(records)

        print "Reindexing docs"
        l.search.index_datasets()

        return

    if args.identifiers:

        if args.list:
            for x in l.search.identifiers:
                print x

        else:
            for score, gvid, name in l.search.search_identifiers(term, limit=30):
                print "{:6.2f} {:9s} {}".format(score, gvid, name)

    elif args.datasets or not (args.identifiers or args.partitions):

        if args.list:

            for x in l.search.datasets:
                ds = l.dataset(x)
                print x, ds.name, ds.data.get('title')

        else:

            print "search for ", term

            for x in l.search.search_datasets(term):
                ds = l.dataset(x)
                print x, ds.name, ds.data.get('title')

    elif args.partitions:

        if args.list:
            for x in l.search.partitions:
                p = l.partition(x)
                print p.vid, p.vname
        else:

            from ..identity import ObjectNumber
            from collections import defaultdict

            bundles = defaultdict(set)

            for x in l.search.search_partitions(term):
                bvid = ObjectNumber.parse(x).as_dataset

                bundles[str(bvid)].add(x)

            for bvid, pvids in bundles.items():

                ds = l.dataset(str(bvid))

                print ds.vid, ds.name, len(pvids), ds.data.get('title')


def root_doc(args, l, rc):

    from ambry.ui import app, configure_application, setup_logging
    import ambry.ui.views as views
    import os

    import logging
    from logging import FileHandler
    import webbrowser

    port = args.port if args.port else 8085

    cache_dir = l._doc_cache.path('', missing_ok=True)

    config = configure_application(dict(port=port))

    file_handler = FileHandler(os.path.join(cache_dir, "web.log"))
    file_handler.setLevel(logging.WARNING)
    app.logger.addHandler(file_handler)

    print 'Serving documentation for cache: ', cache_dir

    if not args.debug:
        # Don't open the browser on debugging, or it will re-open on every
        # application reload
        webbrowser.open("http://localhost:{}/".format(port))

    app.run(host=config['host'], port=int(port), debug=args.debug)
