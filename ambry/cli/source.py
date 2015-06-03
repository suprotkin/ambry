"""Copyright (c) 2013 Clarinova.

This file is licensed under the terms of the Revised BSD License,
included in this distribution as LICENSE.txt

"""

import shutil

from ..cli import prt, fatal, warn
from ..cli import load_bundle, _print_bundle_list
import os


def source_command(args, rc, reset_lib=False):
    from ..library import new_library
    from . import global_logger

    l = new_library(rc.library(args.name), reset=reset_lib)
    l.logger = global_logger

    st = l.source
    globals()['source_' + args.subcommand](args, l, st, rc)


def source_parser(cmd):
    import argparse

    src_p = cmd.add_parser('source', help='Manage bundle source files')
    src_p.set_defaults(command='source')
    src_p.add_argument('-n', '--name', default='default',
                       help='Select the name for the repository. Defaults to "default" ')
    asp = src_p.add_subparsers(title='source commands', help='command help')

    sp = asp.add_parser('new', help='Create a new bundle')
    sp.set_defaults(subcommand='new')
    sp.set_defaults(revision=1)  # Needed in Identity.name_parts
    sp.add_argument('-s', '--source', required=True, help='Source, usually a domain name')
    sp.add_argument('-d', '--dataset', required=True, help='Name of the dataset')
    sp.add_argument('-b', '--subset', default=None, help='Name of the subset')
    sp.add_argument('-t', '--time', default=None, help='Time period. Use ISO Time intervals where possible. ')
    sp.add_argument('-p', '--space', default=None, help='Spatial extent name')
    sp.add_argument('-v', '--variation', default=None, help='Name of the variation')
    sp.add_argument('-c', '--creator', required=False, help='Id of the creator')
    sp.add_argument('-n', '--dryrun', action="store_true", default=False, help='Dry run')
    sp.add_argument('-k', '--key', help='Number server key. Use \'self\' for a random, self-generated key.')
    sp.add_argument('args', nargs=argparse.REMAINDER)  # Get everything else.

    sp = asp.add_parser('info', help='Information about the source configuration')
    sp.set_defaults(subcommand='info')
    sp.add_argument('terms', type=str, nargs=argparse.REMAINDER,
                    help='Name or ID of the bundle or partition to print information for')

    sp = asp.add_parser('deps', help='Print the depenencies for all source bundles')
    sp.set_defaults(subcommand='deps')
    # sp.add_argument('ref', type=str,nargs='?',help='Name or id of a bundle to generate a sorted dependency list for.')
    sp.add_argument('-d', '--detail', default=False, action="store_true",
                    help='Display details of locations for each bundle')
    sp.add_argument('-F', '--fields', type=str, help="Specify fields to use")
    # group = sp.add_mutually_exclusive_group()
    # group.add_argument('-f', '--forward',  default='f', dest='direction',
    # action='store_const', const='f', help='Display bundles that this one depends on')
    # group.add_argument('-r', '--reverse',  default='f', dest='direction',
    # action='store_const', const='r', help='Display bundles that depend on this one')
    sp.add_argument('terms', type=str, nargs=argparse.REMAINDER,
                    help='Name or ID of the bundle or partition as the root of the dependency tree')

    sp = asp.add_parser('init', help='Intialize the local and remote git repositories')
    sp.set_defaults(subcommand='init')
    sp.add_argument('dir', type=str, nargs='?', help='Directory')

    sp = asp.add_parser('list', help='List the source dirctories')
    sp.set_defaults(subcommand='list')
    sp.add_argument('-F', '--fields', type=str, help="Specify fields to use")

    sp = asp.add_parser('buildable', help='List source bundles that can be built')
    sp.set_defaults(subcommand='buildable')
    sp.add_argument('-F', '--fields', type=str, help="Specify fields to use")

    sp = asp.add_parser('build', help='Build sources')
    sp.set_defaults(subcommand='build')

    sp.add_argument('-f', '--force', default=False, action="store_true", help='Build even if built or in library')
    sp.add_argument('-c', '--clean', default=False, action="store_true", help='Clean first')
    sp.add_argument('-i', '--install', default=False, action="store_true", help='Install after build')
    sp.add_argument('-n', '--dryrun', default=False, action="store_true", help='Only display what would be built')

    sp.add_argument('dir', type=str, nargs='?', help='Directory to start search for sources in. ')

    sp = asp.add_parser('edit', help='Run the editor defined in the EDITOR env var on the bundle directory')
    sp.set_defaults(subcommand='edit')
    sp.add_argument('term', type=str, help='Name or ID of the bundle or partition to print information for')

    sp = asp.add_parser('run', help='Run a shell command in source directories passed in on stdin')
    sp.set_defaults(subcommand='run')

    sp.add_argument('-P', '--python', default=None,
                    help='Path to a python class file to run. Loads as module and calls run(). '
                         'The run() function can have any combination of arguments of these names: '
                         'bundle_dir, bundle, repo')
    sp.add_argument('-m', '--message', nargs='+', default='.', help='Directory to start recursing from ')
    sp.add_argument('terms', nargs=argparse.REMAINDER, type=str, help='Bundle refs to run command on')

    group = sp.add_mutually_exclusive_group()
    group.add_argument('-i', '--install', default=False, dest='repo_command', action='store_const', const='install',
                       help='Install the bundle')
    group.add_argument('-s', '--shell', default=False, dest='repo_command', action='store_const', const='shell',
                       help='Run a shell command')

    sp = asp.add_parser('number', help='Return the next dataset number from the number server')
    sp.set_defaults(subcommand='number')
    sp.add_argument('-k', '--key', help='Number server key')
    sp.add_argument('-s', '--set',
                    help='Set the number in the bundle in the specified directory')


def source_info(args, l, st, rc):
    from . import _print_bundle_info

    if not args.terms:
        prt("Source dir: {}", st.base_dir)
        return

    if args.terms[0] == '-':  # Read terms from stdin, one per line.
        import sys

        for line in sys.stdin.readlines():
            args.terms = [line.strip()]
            source_info(args, st, rc)

    else:
        from ..identity import Identity

        term = args.terms.pop(0)

        ident = l.resolve(term, location=None)

        if not ident:
            fatal(
                "Didn't find source for term '{}'. (Maybe need to run 'source sync')",
                term)

        try:
            bundle = st.resolve_bundle(ident.id_)
            _print_bundle_info(bundle=bundle)
        except ImportError:
            ident = l.resolve(term)
            _print_bundle_info(ident=ident)


def source_list(args, l, st, rc, names=None):
    """List all of the source packages."""

    if args.fields:
        fields = args.fields.split(',')
    else:
        fields = ['locations', 'vid', 'vname']

    s_lst = st.list()

    _print_bundle_list(s_lst.values(), fields=fields, sort=False)


def source_get(args, l, st, rc):
    """Clone one or more registered source packages ( via sync ) into the
    source directory."""
    from ..orm import Dataset

    for term in args.terms:
        from ..dbexceptions import ConflictError

        if term.startswith('http'):
            prt("Loading bundle from {}".format(term))
            try:
                bundle = st.clone(term)
                if bundle:
                    prt("Loaded {} into {}".format(
                        bundle.identity.sname, bundle.bundle_dir))
            except ConflictError as e:
                fatal(e.message)

        else:
            ident = l.resolve(term, location=Dataset.LOCATION.SREPO)

            if not ident:
                fatal("Could not find bundle for term: {} ".format(term))

            f = l.files.query.type(Dataset.LOCATION.SREPO).ref(ident.vid).one

            if not f.source_url:
                fatal("Didn't get a git URL for reference: {} ".format(term))

            args.terms = [f.source_url]
            return source_get(args, l, st, rc)


def source_number(args, l, st, rc):
    from ..identity import NumberServer

    nsconfig = rc.group('numbers')

    if args.key:
        nsconfig['key'] = args.key

    ns = NumberServer(**nsconfig)

    n = str(ns.next())

    if args.set:
        # TODO: Where is ambry.bundle.config?
        from ..bundle.config import BundleFileConfig
        d = args.set
        if os.path.isfile(d):
            d = os.path.dirname(d)

        c = BundleFileConfig(d, n)
        c.rewrite()
        prt("Stored number {} into bundle at {}", n, d)
    else:
        print n


def source_new(args, l, st, rc):
    """Clone one or more registered source packages ( via sync ) into the
    source directory."""
    from ..identity import DatasetNumber, Identity
    from ..identity import NumberServer
    from requests.exceptions import HTTPError
    from ..bundle.bundle import BuildBundle
    from ambry.bundle.meta import Top
    from ..dbexceptions import ConflictError

    d = vars(args)
    d['revision'] = 1

    d['btime'] = d.get('time', None)
    d['bspace'] = d.get('space', None)

    if args.dryrun or args.key in ('rand', 'self'):

        prt("Using self-generated id")

        d['id'] = str(DatasetNumber())

    else:
        try:

            nsconfig = rc.service('numbers')
            if args.key:
                nsconfig['key'] = args.key

            ns = NumberServer(**nsconfig)

            d['id'] = str(ns.next())
            prt("Got number from number server: {}".format(d['id']))
        except HTTPError as e:
            warn("Failed to get number from number server. Config = {}: {}".format( nsconfig,e.message))
            warn("Using self-generated number. "
                 "There is no problem with this, but they are longer than centrally generated numbers.")
            d['id'] = str(DatasetNumber())

    try:
        ambry_account = rc.group('accounts').get('ambry', {})
    except:
        ambry_account = None

    if not ambry_account:
        fatal("Failed to get an accounts.ambry entry from the configuration. ( It's usually in {}. ) ".format(
                rc.USER_ACCOUNTS))

    if not ambry_account.get('name') or not ambry_account.get('email'):
        from ambry.run import RunConfig as rc

        fatal("Must set accounts.ambry.email and accounts.ambry.name, usually in {}".format(rc.USER_ACCOUNTS))

    ident = Identity.from_dict(d)

    bundle_dir = os.path.join(os.getcwd(), ident.source_path)

    if args.dryrun:
        prt("Creating  {}".format(ident.fqname))
        prt("Directory {}".format(bundle_dir))

        return

    if not os.path.exists(bundle_dir):
        os.makedirs(bundle_dir)

    elif os.path.isdir(bundle_dir):
        fatal("Directory already exists: " + bundle_dir)

    metadata = Top(path=bundle_dir)

    metadata.identity = ident.ident_dict
    metadata.names = ident.names_dict
    metadata.write_to_dir(write_all=True)

    # Now that the bundle has an identity, we can load the config through the
    # bundle.

    b = BuildBundle(bundle_dir)

    b.metadata.contact_bundle.creator.email = ambry_account.get('email')
    b.metadata.contact_bundle.creator.name = ambry_account.get('name')
    b.metadata.contact_bundle.creator.url = ambry_account.get('url', '')
    b.metadata.contact_bundle.creator.org = ambry_account.get('org', '')

    b.metadata.sources.example = {
        'url': 'http://example.com',
        'description': 'description'}

    b.metadata.external_documentation.download = {
        'url': 'http://example.com',
        'title': "Download Page",
        'description': 'Web page that links to the source files.'
    }

    b.metadata.external_documentation.dataset = {
        'url': 'http://example.com',
        'title': "Dataset Page",
        'description': 'Main webpage for the dataset.'
    }

    b.metadata.external_documentation.documentation = {
        'url': 'http://example.com',
        'title': "Main Documentation",
        'description': 'The primary documentation file'
    }

    b.update_configuration()

    p = lambda x: os.path.join(os.path.dirname(__file__), '..', 'support', x)
    shutil.copy(p('bundle.py'), bundle_dir)
    # shutil.copy(p('README.md'),bundle_dir)
    shutil.copy(p('schema.csv'), os.path.join(bundle_dir, 'meta'))
    shutil.copy(p('documentation.md'), os.path.join(bundle_dir, 'meta'))

    try:
        l.sync_source_dir(b.identity, bundle_dir)

    except ConflictError as e:

        from ..util import rm_rf

        rm_rf(bundle_dir)
        fatal("Failed to sync bundle at {}  ; {}. Bundle deleted".format(bundle_dir, e.message))
    else:
        prt("CREATED: {}, {}", ident.fqname, bundle_dir)


def source_build(args, l, st, rc):
    """Build a single bundle, or a set of bundles in a directory.

    The build process will build all dependencies for each bundle before
    buildng the bundle.

    """

    from ambry.identity import Identity
    from ..source.repository import new_repository

    repo = new_repository(rc.sourcerepo(args.name))

    dir_ = None
    name = None

    if args.dir:
        if os.path.exists(args.dir):
            dir_ = args.dir
            name = None
        else:
            name = args.dir
            try:
                Identity.parse_name(name)
            except:
                fatal("Argument '{}' must be either a bundle name or a directory".format(name))
                return

    if not dir_:
        dir_ = rc.sourcerepo.dir

    def build(bundle_dir):
        from ambry.library import new_library

        # Import the bundle file from the directory

        bundle_class = load_bundle(bundle_dir)
        bundle = bundle_class(bundle_dir)

        l = new_library(rc.library(args.library_name))

        if l.get(bundle.identity.vid) and not args.force:
            prt("{} Bundle is already in library", bundle.identity.name)
            return
        elif bundle.is_built and not args.force and not args.clean:
            prt("{} Bundle is already built", bundle.identity.name)
            return
        else:

            if args.dryrun:
                prt("{} Would build but in dry run ", bundle.identity.name)
                return

            repo.bundle = bundle

            if args.clean:
                bundle.clean()

            # Re-create after cleaning is important for something ...

            bundle = bundle_class(bundle_dir)

            prt("{} Building ", bundle.identity.name)

            if not bundle.run_prepare():
                fatal("{} Prepare failed", bundle.identity.name)

            if not bundle.run_build():
                fatal("{} Build failed", bundle.identity.name)

        if args.install and not args.dryrun:
            if not bundle.run_install(force=True):
                fatal('{} Install failed', bundle.identity.name)

    build_dirs = {}

    # Find all of the dependencies for the named bundle, and make those first.
    for root, _, files in os.walk(rc.sourcerepo.dir):
        if 'bundle.yaml' in files:
            bundle_class = load_bundle(root)
            bundle = bundle_class(root)
            build_dirs[bundle.identity.name] = root

    if name:
        deps = repo.bundle_deps(name)
        deps.append(name)

    else:

        deps = []

        # Walk the subdirectory for the files to build, and
        # add all of their dependencies
        for root, _, files in os.walk(dir_):
            if 'bundle.yaml' in files:

                bundle_class = load_bundle(root)
                bundle = bundle_class(root)

                for dep in repo.bundle_deps(bundle.identity.name):
                    if dep not in deps:
                        deps.append(dep)

                deps.append(bundle.identity.name)

    for n in deps:
        try:
            dir_ = build_dirs[n]
        except KeyError:
            fatal("Failed to find directory for bundle {}".format(n))

        prt('')
        prt("{} Building in {}".format(n, dir_))
        build(dir_)


def source_run(args, l, st, rc):
    from ..orm import Dataset

    import sys

    if args.terms and args.repo_command != 'shell':
        def yield_term():
            for t in args.terms:
                yield t
    else:
        def yield_term():
            for line in sys.stdin.readlines():
                yield line.strip()

    for term in yield_term():

        ident = l.resolve(term, Dataset.LOCATION.SOURCE)

        if not ident:
            warn(
                "Didn't get source bundle for term '{}'; skipping ".format(term))
            continue

        do_source_run(ident, args, l, st, rc)


def do_source_run(ident, args, l, st, rc):
    from ambry.run import import_file
    # from ambry.source.repository.git import GitRepository

    root = ident.bundle_path

    if args.python:

        import inspect

        try:
            mod = import_file(args.python)
        except ImportError:
            import ambry.cli.source_run as sr

            f = os.path.join(os.path.dirname(sr.__file__), args.python + ".py")
            try:
                mod = import_file(f)
            except ImportError:
                raise
                # fatal("Could not get python file neither '{}', nor '{}'".format( args.python,f))

        run_args = inspect.getargspec(mod.run)

        a = {}

        if 'bundle_dir' in run_args.args:
            a['bundle_dir'] = root

        if 'args' in run_args.args:
            a['args'] = args.terms

        if 'bundle' in run_args.args:
            rp = os.path.join(root, 'bundle.py')
            bundle_mod = import_file(rp)
            dir_ = os.path.dirname(rp)
            try:
                a['bundle'] = bundle_mod.Bundle(dir_)
            except Exception as e:
                warn("Failed to load bundle from dir: {}: {}", dir_, str(e))
                raise

        mod.run(**a)

    elif args.repo_command == 'install':
        prt("--- {} {}", args.repo_command, root)
        bundle_class = load_bundle(root)
        bundle = bundle_class(root)

        bundle.run_install()

    elif args.repo_command == 'shell':

        cmd = ' '.join(args.terms)

        saved_path = os.getcwd()
        os.chdir(root)
        prt('----- {}', root)
        prt('----- {}', cmd)

        os.system(cmd)
        prt('')
        os.chdir(saved_path)


def source_init(args, l, st, rc):
    from ..source.repository import new_repository

    dir_ = args.dir

    if not dir_:
        dir_ = os.getcwd()

    repo = new_repository(rc.sourcerepo(args.name))
    repo.bundle_dir = dir_

    repo.delete_remote()
    import time

    time.sleep(3)
    repo.init_descriptor()
    repo.init_remote()

    repo.push()

    st.sync_bundle(dir_)


def source_deps(args, l, st, rc):
    """Produce a list of dependencies for all of the source bundles."""

    # if args.fields:
    #     fields = args.fields.split(',')
    # else:
    #     fields = ['locations', 'vid', 'vname', 'order']

    # term = args.terms[0] if args.terms else None

    from collections import defaultdict

    deps = defaultdict(set)
    for e in st.list():
        b = st.resolve_bundle(e)
        for d in b.metadata.dependencies.values():

            db = l.resolve(d, location=None)

            if db:
                deps[b.identity.vid].add(db.vid)
            else:
                print "F", d

        b.close()

    for k, d in deps.items():
        kr = l.resolve(k, location=None)
        print kr
        for e in d:
            er = l.resolve(e, location=None)
            print '   ', er

    return

    # try:
    # graph, errors = st.dependencies(term)
    # except NotFoundError:
    #     fatal("Didn't find source bundle for term: {}".format(term))

    # if errors and not args.fields:
    #     print "----ERRORS"
    #     for name, errors in errors.items():
    #         print '=', name
    #         for e in errors:
    #             print '    ', e
    #     print "----"

    # identities = []

    # return

    # for i, level in enumerate(graph):
    #     for j, name in enumerate(level):
    #         if not name:
    #             continue
    #
    #         ident = l.resolve(name, location=Dataset.LOCATION.SOURCE)
    #         if ident:
    #             ident.data['order'] = dict(major=i, minor=j)
    #             identities.append(ident)
    #
    # _print_bundle_list(identities, fields=fields, sort=False)


def source_watch(args, l, st, rc):
    st.watch()


def source_edit(args, l, st, rc):
    from ambry.orm import Dataset
    from os import environ
    from subprocess import Popen

    if not args.term:
        fatal("Must supply a bundle term")

    term = args.term

    editor = environ['EDITOR']

    try:
        ident = l.resolve(term, Dataset.LOCATION.SOURCE)
    except ValueError:
        ident = None

    if not ident:
        fatal("Didn't find a source bundle for term: {} ".format(term))

    root = ident.bundle_path

    prt("Running: {} {}".format(editor, root))
    prt("Build with: ambry bundle -d {} build".format(ident.sname))
    prt("Directory : {}".format(ident.bundle_path))
    Popen(['env', editor, root])


def source_buildable(args, l, st, rc):
    from ambry.dbexceptions import DependencyError

    if args.fields:
        fields = args.fields.split(',')
    else:
        fields = ['locations', 'vid', 'vname']

    s_lst = st.list()

    buildable = []

    for vid, v in s_lst.items():

        try:
            bundle = st.resolve_bundle(vid)
            bundle.library.check_dependencies(download=False)

            if not bundle.is_built and not bundle.is_installed:
                buildable.append(v)

        except DependencyError:
            pass
        finally:
            bundle.close()

    if not buildable:
        import sys

        sys.exit(1)

    _print_bundle_list(buildable, fields=fields, sort=False)


def source_test(args, l, st, rc):
    """Development text code."""

    from sqlalchemy.orm.attributes import InstrumentedAttribute
    import inspect

    for e in l.list():
        b = l.get(e)

        print b

        d = b.get_dataset()

        for k, v in inspect.getmembers(d.__class__, lambda x: isinstance(x, InstrumentedAttribute)):
            print k, type(v)

        break
