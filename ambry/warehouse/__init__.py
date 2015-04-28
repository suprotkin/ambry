from __future__ import absolute_import
from ..library import Library
from ..library.database import LibraryDb
from ckcache import new_cache, Cache
from ..database import new_database
import os
from ..util import Constant, memoize
from ambry.util import init_log_rate
from ..library.files import Files
from ..identity import TopNumber


class NullCache(Cache):

    def has(self, rel_path, md5=None, use_upstream=True):
        return False


class NullLogger(object):

    def __init__(self):
        pass

    def progress(self, type_, name, n, message=None):
        pass

    def progress(self, o, t):
        pass

    def log(self, message):
        pass

    def info(self, message):
        pass

    def error(self, message):
        pass

    def warn(self, message):
        pass


class WLibrary(Library):

    """Extends the Library class to remove the Location parameter on identity
    resolution."""

    def resolve(self, ref, location=None):

        return super(WLibrary, self).resolve(ref, location=location)


def new_warehouse(config, elibrary, logger=None):

    assert elibrary is not None

    if isinstance(config, basestring):
        config = database_config(config)

    service = config['service'] if 'service' in config else 'relational'

    if 'database' in config:
        # making a copy so we can alter it.
        db_config = dict(config['database'].items())
    else:
        db_config = dict(config.items())

    database = new_database(db_config, class_='warehouse')

    # If the warehouse specifies a seperate external library, use it, otherwise,
    # use the warehouse database for the library
    library_database = LibraryDb(
        **config['library']) if 'library' in config else LibraryDb(**db_config)

    # This library instance is only for the warehouse database.
    wlibrary = WLibrary(
        cache=NullCache(),
        database=library_database
    )

    args = dict(
        database=database,
        wlibrary=wlibrary,
        elibrary=elibrary,
        logger=logger)

    if service == 'sqlite':
        from .sqlite import SqliteWarehouse
        w = SqliteWarehouse(**args)

    elif service == 'spatialite':

        from .sqlite import SpatialiteWarehouse

        w = SpatialiteWarehouse(**args)

    elif service == 'postgres':
        from .postgres import PostgresWarehouse

        w = PostgresWarehouse(**args)

    elif service == 'postgis':
        from .postgis import PostgisWarehouse

        w = PostgisWarehouse(**args)

    else:
        raise Exception("Unknown warehouse type: {}".format(service))

    return w


class ResolutionError(Exception):
    pass


class Warehouse(object):

    FILE_TYPE = Constant()

    FILE_TYPE.MANIFEST = 'manifest'
    FILE_TYPE.HTML = 'text/html'
    FILE_TYPE.EXTRACT = Files.TYPE.EXTRACT

    FILE_GROUP = Constant()

    FILE_GROUP.MANIFEST = Files.TYPE.MANIFEST
    FILE_GROUP.DOC = Files.TYPE.DOC

    # Override these in dialect specific subclasses.
    drop_view_sql = 'DROP VIEW  IF EXISTS "{name}"'
    create_view_sql = 'CREATE VIEW "{name}" AS {sql}'

    def __init__(self,
                 database,
                 wlibrary=None,  # Warehouse library
                 elibrary=None,  # external Library
                 cache=None,
                 logger=None,
                 base_dir=None,
                 test=False):
        from ..util import qualified_class_name

        assert wlibrary is not None
        assert elibrary is not None
        assert database is not None

        self.database = database
        self.wlibrary = wlibrary
        self.elibrary = elibrary
        self.test = test
        self._cache = cache

        logger = logger if logger else NullLogger()

        self.logger = Logger(logger, init_log_rate(logger.info, N=2000))

        self.database_class = qualified_class_name(self.database)

    def info(self, location, message=None):

        if not message:
            message = location
            location = None

        if location:
            self.logger.info("{}:{} {}", location[0], location[1], message)
        else:
            self.logger.info(message)

    def create(self):
        from datetime import datetime
        from ..orm import Dataset
        from sqlalchemy.orm.exc import NoResultFound

        self.database.create()
        self.wlibrary.database.create()

        # Create the uid from the DSN.
        self._meta_set(
            'uid', str(
                TopNumber.from_string(
                    self.database.dsn, 'd')))

        # Create the dataset record for the database. This will be the dataset for tables and
        # partitions created in the database.
        s = self.database.session
        try:
            s.query(Dataset).filter(Dataset.id_ == self.vid).order_by(Dataset.revision.desc()).one()
        except NoResultFound:
            from ..identity import Identity

            ident = Identity.from_dict(
                dict(
                    id=self.vid,
                    revision=1,
                    source='ambry',
                    dataset=self.vid))

            ds = Dataset(
                data=dict(dsn=self.dsn),
                creator='ambry',
                fqname=ident.fqname,
                **ident.dict)

            s.add(ds)

            s.commit()

            self.wlibrary.files.install_data_store(self)

        self._meta_set('created', datetime.now().isoformat())

    def clean(self):

        self.database.clean()
        self.wlibrary.clean()

    def delete(self):
        self.database.enable_delete = True
        self.database.drop()

        self.database.delete()
        self.wlibrary.database.enable_delete = True
        self.wlibrary.database.drop()
        # self.wlibrary.database.delete()

    def exists(self):
        return self.database.exists()

    def close(self):
        self.database.close()
        self.library.close()

    @property
    def library(self):
        return self.wlibrary

    @property
    def bundle(self):
        """Return a LibraryBundle based on the library, and the dataset
        specified by the warehouse uid.

        This bundle holds the partition and table definitions for data
        created though SQL in the warehouse

        """
        from ..bundle import LibraryDbBundle
        from ..identity import ObjectNumber

        # If the uid doesn't have a version, its because we haven't implemened
        # versioning yet.
        on = ObjectNumber.parse(self.uid)

        if on.revision is None:
            on.revision = 1

        return LibraryDbBundle(self.library.database, str(on))

    ##
    # Metadata
    ##

    def _meta_set(self, key, value):
        from ..orm import Config
        return self.library.database.set_config_value('warehouse', key, value)

        # Also write to the file, since when the warehouse is installed in a library,
        # it's the file that is used for storing information about the title,
        # summary, etc.
        f = self.wlibrary.store(self.uid)
        f['data']['key'] = value
        self.wlibrary.commit()

    def _meta_get(self, key):
        from ..orm import Config

        try:
            return self.library.database.get_config_value(
                'warehouse',
                key).value
        except AttributeError:
            return None

    configurable = ('uid', 'title', 'name', 'summary', 'cache_path', 'url')

    @property
    @memoize
    def uid(self):
        """UID of the warehouse."""
        return self._meta_get('uid')

    @property
    @memoize
    def vid(self):
        """The versioned id of the warehouse."""
        from ..identity import ObjectNumber

        # Until we support versioning warehouses
        on = ObjectNumber.parse(self.uid)
        if on.revision is None:
            on.revision = 1

        return str(on)

    @property
    def title(self):
        """Title of the warehouse."""
        return self._meta_get('title')

    @title.setter
    def title(self, v):
        return self._meta_set('title', v)

    @property
    def summary(self):  # Everything else names this property summary
        """Short description of the warehouse."""
        return self._meta_get('summary')

    @summary.setter
    def summary(self, v):
        return self._meta_set('summary', v)

    @property
    def name(self):
        """name of the warehouse."""
        return self._meta_get('name')

    @name.setter
    def name(self, v):
        return self._meta_set('name', v)

    @property
    def url(self):
        """Url of the management application for the warehouse."""
        return self._meta_get('url')

    @url.setter
    def url(self, v):

        return self._meta_set('url', v)

    @property
    def dsn(self):
        return self.database.dsn

    @property
    def cache(self):

        if self._cache:
            return self._cache
        else:
            assert self.uid
            return self.elibrary.warehouse_cache.subcache(self.uid)

    @property
    def dict(self):
        """Return information about the warehouse as a dictionary."""

        from ambry.warehouse.manifest import Manifest

        from ambry.util import filter_url

        d = {}

        for k, v in self.library.database.get_config_group('warehouse').items():
            if k in self.configurable:
                d[k] = v

        d['dsn'] = filter_url(
            self.database.dsn,
            password=None)  # remove the password

        d['tables'] = {t.vid: t.nonull_col_dict for t in self.library.tables}

        d['partitions'] = {p.vid: p.dict for p in self.library.partitions}

        d['manifests'] = {mf.ref: mf.dict for mf in self.library.manifests}

        return d

    @property
    def manifests(self):
        """Return the parsed manifests that have been installed."""
        from .manifest import Manifest

        return self.library.files.query.type(
            self.FILE_TYPE.MANIFEST).group(
            self.FILE_GROUP.MANIFEST).all

    @property
    def bundles(self):
        """Metadata for bundles, each with the partitions that are installed
        here.

        This extracts the bundle information that is in the partitions
        list, but it requires that the add_bundle() method has been run
        first, because the manifest doesn't usually have access to a
        library

        """

        l = self.library.list(with_partitions=True)

        for k, v in l.items():

            d = {
                e.key.replace(
                    '.',
                    '_'): e.value for e in self.library.database.get_bundle_values(
                    k,
                    'config')}
            v.data.update(d)

        return l

    @property
    def extracts(self):
        """Return an array of dicts of the extract files."""

        for f in self.library.files.query.group(self.FILE_GROUP.MANIFEST).type(self.FILE_TYPE.EXTRACT).all:
            self.library.database.session.expunge(f)
            f.source_url = self.uid
            f.oid = None
            yield f

    def table_meta(self, identity, table_name):
        """Get the metadata directly from the database.

        This requires that table_name be the same as the table as it is
        in stalled in the database

        """
        from ..schema import Schema

        assert identity.is_partition

        self._to_vid(identity)
        d_vid = self._partition_to_dataset_vid(identity)

        meta, table = Schema.get_table_meta_from_db(self.library.database,
                                                    table_name,
                                                    d_vid=d_vid,
                                                    driver=self.database.driver,
                                                    use_fq_col_names=True,
                                                    alt_name=self.augmented_table_name(identity, table_name)[0],
                                                    session=self.library.database.session)
        return meta, table

    def table(self, table_name):
        """Get table metadata from the database."""
        from sqlalchemy import Table

        table = self._table_meta_cache.get(table_name, False)

        if table is not False:
            r = table
        else:
            metadata = self.metadata  # FIXME Will probably fail ..
            table = Table(table_name, metadata, autoload=True)
            self._table_meta_cache[table_name] = table
            r = table

        return r

    @property
    def tables(self):
        from ..orm import Table

        for table in self.library.database.session.query(Table).all():
            yield table

    def orm_table(self, vid):
        from ..orm import Table

        return self.library.database.session.query(
            Table).filter(Table.vid == vid).first()

    def orm_table_by_name(self, name):
        from ..orm import Table

        return self.library.database.session.query(
            Table).filter(Table.name == name).first()

    @property
    def partitions(self):
        from ..orm import Partition

        for p in self.library.database.session.query(Partition).all():
            yield p

    def partition(self, vid):
        from ..orm import Partition

        return self.library.database.session.query(
            Partition).filter(Partition.vid == vid).first()

    ##
    # Installation
    ##

    def digest_manifest(self, manifest, force=None):
        """Digest manifest into a list of commands for the installer."""
        from ..orm import Partition

        commands = []

        commands.append(
            ('about',
             manifest.title,
             manifest.summary['summary_text']))

        # First pass
        for line, section in manifest.sorted_sections:

            tag = section.tag

            if tag in ('partitions', 'sql', 'index', 'mview', 'view'):
                self.logger.info(
                    "== Processing manifest '{}' section '{}' at line {}" .format(
                        manifest.path,
                        section.tag,
                        section.linenumber))

            if tag == 'partitions':
                for pd in section.content['partitions']:

                    # Tables that were specified on the parittion line; install
                    # only these
                    tables = pd['tables']

                    p_vid = self._to_vid(pd['partition'])

                    p_orm = self.wlibrary.database.session.query(
                        Partition).filter(Partition.vid == p_vid).first()

                    if p_orm and p_orm.installed == 'y':
                        self.logger.info(
                            "Skipping {}; already installed".format(
                                p_orm.vname))
                        continue
                    else:
                        dataset = self.elibrary.resolve(p_vid)

                        if not dataset:
                            raise ResolutionError(
                                "Library does not have object for reference: {}".format(
                                    pd['partition']))

                        ident = dataset.partition

                        if not ident:
                            raise ResolutionError(
                                "Ref resolves to a bundle, not a partition. Can only install partitions: {}".format(
                                    p_orm))

                        if ident.format not in ('db', 'geo'):
                            self.logger.warn(
                                "Skipping {}; uninstallable format: {}".format(
                                    ident.vname,
                                    ident.format))
                            continue

                        commands.append(
                            ('install', dataset, tables, pd['where']))

            elif tag == 'sql':
                sql = section.content

                if self.database.driver in sql:
                    commands.append(('sql', sql[self.database.driver]))

            elif tag == 'index':
                c = section.content
                commands.append(('index', c['name'], c['table'], c['columns']))

            elif tag == 'mview' or tag == 'view':
                commands.append(
                    (tag,
                     section.args,
                     section.content['text'],
                     dict(
                         tc_names=section.content['tc_names'],
                         summary=section.doc.get(
                             'summary_text',
                             '') if section.doc else '',
                         doc=section.doc,
                         manifests=[
                             manifest.uid],
                         sql_formatted=section.content['html']),
                        force))

            elif tag == 'extract':

                d = section.content
                doc = manifest.doc_for(section)
                if doc:
                    d['doc'] = doc.content['html']

                extract_path = os.path.join('extracts', d['rpath'])

                # self.wlibrary.files.install_extract()
                commands.append(('extract', extract_path, manifest.uid, d))

            elif tag == 'include':
                from .manifest import Manifest

                m = Manifest(section.content['path'])
                for command in self.install_manifest(m, force=force):
                    commands.append(command)

        return commands

    def execute_commands(self, commands):
        """Execute a set of installation commands, which are usually from a
        digested manifest."""
        from ..dbexceptions import NotFoundError, ConfigurationError

        installed_partitions = []
        installed_tables = []

        # First pass
        for command_set in commands:

            command_set = list(command_set)
            command = command_set.pop(0)

            if command == 'install':

                dataset, tables, where = command_set

                if where and len(tables) == 1:
                    tables = [(tables[0], "WHERE (" + where + ")")]

                try:
                    tables, p = self.install_partition(
                        dataset.partition.vid, tables)
                except NotFoundError as e:
                    self.logger.error("Failed to install partition {}: {}".format(dataset.partition, e))
                    continue

                installed_tables += tables
                installed_partitions.append(p)
            elif command == 'about':

                title, summary = command_set

                if title and not self.title:
                    self.title = title

                if summary and not self.summary:
                    self.summary = summary

            elif command == 'sql':
                sql, = command_set
                self.run_sql(sql)

            elif command == 'index':
                name, table, columns = command_set
                self.create_index(name, table, columns)

            elif command == 'mview':
                name, sql, data, force = command_set
                self.install_material_view(name, sql, force, data)

            elif command == 'view':
                name, sql, data, force = command_set

                self.install_view(name, sql, data)

            elif command == 'extract':
                extract_path, m_uid, d = command_set
                self.wlibrary.files.install_extract(extract_path, m_uid, d)

        return installed_partitions, installed_tables

    def install_manifest(self, manifest, force=None, reset=False):
        """Install the partitions and views specified in a manifest file."""

        from datetime import datetime

        # Mark all of the files associated with the manifest, so if they aren't in the manifest
        # we can remove them.
        # TODO Should also do this for tables.
        for f in (self.library.files.query.type(self.library.files.TYPE.EXTRACT).source_url(manifest.uid)).all:
            f.state = 'deleteable'
            self.library.files.merge(f)

        # Update the manifest with bundle information, since it doesn't
        # normally have access to a library
        manifest.add_bundles(self.elibrary)

        # Manifest data
        mf = self.wlibrary.files.install_manifest(manifest)

        commands = self.digest_manifest(manifest, force)

        partitions, tables = self.execute_commands(commands)

        # Link the partition to the manifest. Have to re-fetch, because p is in the
        # external library, and the manifest is in the warehouse elibrary

        for p in partitions:
            mf.link_partition(p)
            p.link_manifest(mf)

        for table in tables:
            orm_t = self.orm_table_by_name(table)

            mf.link_table(orm_t)
            orm_t.link_manifest(mf)

        self.database.session.commit()

        # Delete all of the files ( extracts ) that were not installed
        (self.library.files.query.type(
            self.library.files.TYPE.EXTRACT).state('deleteable')).delete()

        # Record the installtion time of the manifest.
        self._meta_set(manifest.uid, datetime.now().isoformat())

        self.post_install()

        return self.database.dsn

    def install_partition(self, p_vid, tables=None, prefix=None):
        """Install a partition and the tables in the partition."""

        from sqlalchemy.exc import OperationalError
        from sqlalchemy import inspect

        dataset = self.elibrary.resolve(p_vid)
        b = self.elibrary.get(dataset)
        # This one gets the ref from the bundle
        p = b.partitions.get(dataset.partition)

        # This one downloads the database.
        self.elibrary.get(dataset.partition)

        self.library.database.install_partition(b, p)

        installed_tables = []

        tables_in_partition = inspect(p.database.engine).get_table_names()

        for source_table_name in p.tables:
            if source_table_name not in tables_in_partition:
                continue
            try:
                # table, meta = self.create_table(p, source_table_name)
                self.create_table(p, source_table_name)
            except Exception as e:
                print e
                raise

            # Compute the installation name, and an alias that does not have
            # the version number
            dest_table_name, alias = self.augmented_table_name(
                p.identity, source_table_name)

            if isinstance(source_table_name, (list, tuple)):
                source_table_name, where = source_table_name
            else:
                where = None

            try:
                # Copy the data to the destination table

                self.elibrary.get(p.vid)  # ensure it is local
                itn = self.load_local(
                    p,
                    source_table_name,
                    dest_table_name,
                    where)

                t_vid = p.get_table(source_table_name).vid
                w_table = self.library.table(t_vid)

                # Create a table entry for the name of the table with the partition in it,
                # and link it to the main table record.
                proto_vid = w_table.vid
                self.install_table(
                    dest_table_name,
                    alt_name=alias,
                    data=dict(
                        type='installed',
                        proto_vid=proto_vid))

                # Link the table name and the alias
                self.install_table_alias(
                    dest_table_name,
                    alias,
                    proto_vid=proto_vid)

                self.library.database.mark_table_installed(
                    p.get_table(source_table_name).vid,
                    itn)

                assert self.augmented_table_name(
                    p.identity,
                    source_table_name)[0] == itn

                w_table.data['source_partition'] = p.identity.dict

                # Set the altname of the column, which is the name the column is generallt know by
                # in the warehouse.

                for c in w_table.columns:
                    c.altname = c.fq_name

                installed_tables.append(w_table.name)

            except OperationalError as e:
                self.logger.error("Failed to install table '{}': {}".format(source_table_name, e))
                raise

        self.library.database.mark_partition_installed(p_vid)

        return installed_tables, p

    def build_sample(self, t):

        if t.type == 'table':
            name = t.data['installed_names'][0]
        else:
            name = t.name

        sql = 'SELECT * FROM "{}" LIMIT 20'.format(name)
        sample = []

        for j, row in enumerate(self.database.connection.execute(sql)):
            if j == 0:
                sample.append(row.keys())
                sample.append(row.values())
            else:
                sample.append(row.values())

        t.data['sample'] = sample

        v = self.database.connection.execute(
            'SELECT count(*) FROM "{}"'.format(name)).fetchone()

        t.data['count'] = int(v[0])

    def build_schema(self, t):

        from ..orm import Column
        from ..identity import ObjectNumber

        s = self.library.database.session

        s.execute("DELETE FROM columns WHERE c_t_vid = :tid", {'tid': t.vid})
        s.commit()

        # Have to re-fetch the session, in order to get the "SET search_path" run again on postgres,
        # which apparently gets clearedin the commit()
        s = self.library.database.session
        t = self.library.table(t.vid)

        sql = 'SELECT * FROM "{}" LIMIT 1'.format(t.name)

        row = self.database.connection.execute(sql).fetchone()

        if row:
            for i, (col_name, v) in enumerate(row.items(), 1):

                try:
                    c_id, plain_name = col_name.split('_', 1)
                    cn = ObjectNumber.parse(c_id)

                    orig_table = self.library.table(str(cn.as_table))

                    if not orig_table:
                        self.logger.error(
                            "Unable to find table '{}' while trying to create schema".format(str(cn.as_table)))
                        continue

                    orig_column = orig_table.column(c_id)

                    orig_column.data['col_datatype'] = Column.convert_python_type(
                        type(v),
                        col_name)
                    d = orig_column.dict

                    d['description'] = "{}; {}".format(
                        orig_table.description,
                        d['description'])

                # Coudn't split the col name, probl b/c the user added it in
                # SQL
                except ValueError:
                    d = dict(name=col_name)

                d['sequence_id'] = i
                d['derivedfrom'] = c_id
                try:
                    del d['t_vid']
                    del d['t_id']
                    del d['vid']
                    del d['id_']
                except KeyError:
                    # Unsplit names ( cols added in SQL ) don't have any of the
                    # keys
                    pass

                if d.get('altname', False):
                    d['name'], d['altname'] = d['altname'], d['name']

                if 'datatype' not in d:
                    d['datatype'] = Column.convert_python_type(
                        type(v),
                        col_name)

                t.add_column(**d)

            s.commit()

    def install_union(self):
        """Combine multiple partition tables of the same table type into a
        single table."""

        # TODO, our use of sqlalchemy is wacked.
        # Some of the install methods commit or flush the session, which invalidated the tables from self.tables,
        # so we have to get just the vid, and look up the object in each
        # iteration.

        for t_vid in [t.vid for t in self.tables]:

            t = self.orm_table(t_vid)

            # Get the table definition that columns are linked to
            if t.type == 'table' and t.installed:

                # Create table aliases for the vid of the tables.
                installed_tables = [
                    it for it in self.library.derived_tables(
                        t.vid) if it.type == 'installed']

                # col_names = t.vid_select() # Get to this later ...

                col_names = '*'

                if len(installed_tables) == 1:
                    sql = 'SELECT {} FROM "{}" '.format(
                        col_names,
                        installed_tables[0].name)

                else:

                    sql = "SELECT {} FROM ({}) as subquery ".format(
                        col_names,
                        ' UNION '.join(' SELECT * FROM "{}" '.format(table.name)
                                       for table in installed_tables)
                    )

                self.install_view(
                    t_vid,
                    sql,
                    data=dict(
                        type='alias',
                        proto_vid=t_vid))

    def post_install(self):
        """Perform operations after the manifest install, such as creating
        table views for all of the installed tables.

        For each table, it also installs a vid-based view, which replaces all of the column
        names with their vid. This allows for tracing columns through views, linking
        them back to their source

        """

        # TODO, our use of sqlalchemy is wacked.
        # Some of the install methods commit or flush the session, which invalidated the tables from self.tables,
        # so we have to get just the vid, and look up the object in each
        # iteration.

        for t_vid in [t.vid for t in self.tables]:
            t = self.orm_table(t_vid)
            # Get the table definition that columns are linked to
            if t.type == 'table' and t.installed:
                self.install_table(
                    t_vid,
                    data=dict(
                        type='alias',
                        proto_vid=t_vid))

        s = self.library.database.session

        for t in self.tables:
            if t.type == 'table' and t.installed:
                # derived_tables checks the proto_id, used to link  aliases to
                # base tables.
                for dt in sorted(self.library.derived_tables(t.vid), key=lambda x: x.name):

                    t.add_installed_name(dt.name)
                    s.add(t)

            if (t.type == 'table' and t.installed) or t.type in ('view', 'mview'):
                if 'sample' not in t.data or not t.data['sample']:

                    self.build_sample(t)
                    s.add(t)

        s.commit()

        self.install_union()

        # Update the documentation files in the library

    def install_material_view(self, name, sql, clean=False, data=None):
        from pysqlite2.dbapi2 import OperationalError

        import time

        if not (clean or self.mview_needs_update(name, sql)):
            self.logger.info(
                'Skipping materialized view {}: update not required'.format(name))
            return False, False
        else:
            self.logger.info('Installing materialized view {}'.format(name))

            if not self.orm_table_by_name(name):
                self.logger.info('mview_remove {}'.format(name))
                drop = True
            else:
                drop = False

        data = data if data else {}

        data['sql'] = sql
        data['type'] = 'mview'
        data['updated'] = time.time()

        if drop:
            self.database.connection.execute(
                'DROP TABLE IF EXISTS "{}"'.format(name))

        if not data:
            return False

        sql = """CREATE TABLE {name} AS {sql}""".format(name=name, sql=sql)

        try:
            self.database.connection.execute(sql)

        except OperationalError as e:
            if 'exists' not in str(e).lower():
                raise

            self.logger.info('mview_exists {}'.format(name))
            # Ignore if it already exists.

        t = self.install_table(name, data=data)

        self.build_schema(t)

    def mview_needs_update(self, name, sql):
        """Return True if an mview needs to be regnerated, because it's SQL changed,
         or one of its predecessors was re-generated

         NOTE. This probably only works property when the MVIEWS are listed in the manifest in an order
         where dependent views are listed after depenencies.
         """

        t = self.orm_table_by_name(name)

        if not t:
            return True

        if t.data.get('sql') != sql:
            return True

        update_time = int(t.data.get('updated', None))

        if not update_time:
            return True

        if t:
            for tc_name in t.data.get('tc_names'):
                tc = self.orm_table_by_name(tc_name)

                if (tc and tc.dict.get('updated', False)
                        and (int(tc.dict.get('updated')) > int(t.data.get('updated')))):
                    return True

        return False

    def install_view(self, name, sql, data=None):
        import time

        assert name
        assert sql
        from sqlalchemy.exc import OperationalError

        t = self.orm_table_by_name(name)

        if t and t.data.get('sql') == sql:
            self.logger.info(
                "Skipping view {}; SQL hasn't changed".format(name))
            return
        else:
            self.logger.info('Installing view {}'.format(name))

        data = data if data else {}

        data = data if data else {}
        data['type'] = data['type'] if 'type' in data else 'view'

        data['sql'] = sql
        data['updated'] = time.time()

        data['sample'] = None

        sqls = [
            self.drop_view_sql.format(
                name=name), self.create_view_sql.format(
                name=name, sql=sql)]

        try:
            for sql in sqls:
                # Creates the table in the database
                self.database.connection.execute(sql)

            t = self.install_table(
                name,
                data=data)  # Creates the table library record

            self.build_schema(t)

        except Exception:
            self.logger.error("Failed to install view: \n{}".format(sql))
            raise

        except OperationalError:
            self.logger.error("Failed to execute: {} ".format(sql))
            raise

    def install_table_alias(self, table_name, alias, proto_vid=None):
        """Install a view that allows referencing a table by another name."""
        self.install_view(alias, "SELECT * FROM \"{}\" ".format(table_name),
                          data=dict(type='alias', proto_vid=proto_vid))

    def install_table(self, name, alt_name=None, data=None):
        """Install a view, mview or alias as a Table record.

        Real tables are copied

        """

        from ..orm import Table, Config, Dataset

        from sqlalchemy import func
        from sqlalchemy.orm.exc import NoResultFound

        s = self.library.database.session

        try:
            from sqlalchemy.orm import lazyload

            q = (
                s.query(Table).filter(
                    Table.d_vid == self.vid,
                    Table.name == name) .options(
                    lazyload('columns')))

            t = q.one()

        except NoResultFound:
            # Create a new table, attached to to the warehouse dataset
            # Search for the table by the vid

            ds = s.query(Dataset).filter(
                Dataset.vid == self.vid).one()  # Get the Warehouse dataset.

            q = (
                s.query(
                    func.max(
                        Table.sequence_id)) .filter(
                    Table.d_vid == self.vid))

            seq = q.one()[0]

            seq = 0 if not seq else seq

            seq += 1

            t = Table(ds, name=name, sequence_id=seq, preserve_case=True)

        assert bool(t)

        if alt_name is not None:
            t.altname = str(alt_name)

        if data and 'type' in data:
            t.type = data['type']
            del data['type']

        if data and 'summary' in data:

            t.description = data['summary']

            del data['summary']

        if data and 'proto_vid' in data:
            if not t.proto_vid:
                t.proto_vid = data['proto_vid']
            del data['proto_vid']

        if t.data:
            d = dict(t.data.items())
            d.update(data if data else {})
            t.data = d
        else:
            t.data = data

        if data and 'doc' in data:
            t.data.doc = data['doc']

        t.installed = 'y'

        s.merge(t)
        s.commit()

        return t

    def load_local(
            self,
            partition,
            source_table_name,
            dest_table_name,
            where=None):
        return self.load_insert(
            partition,
            source_table_name,
            dest_table_name,
            where=where)

    def load_insert(
            self,
            partition,
            source_table_name,
            dest_table_name,
            where=None):
        from ..database.inserter import ValueInserter
        from sqlalchemy import Table, MetaData
        from sqlalchemy.dialects.postgresql.base import BYTEA
        import psycopg2

        replace = False

        self.logger.info('load_insert {}'.format(partition.identity.vname))

        if self.database.driver == 'mysql':
            cache_size = 5000

        elif self.database.driver == 'postgres' or self.database.driver == 'postgis':
            cache_size = 5000

        else:
            cache_size = 50000

        self.logger.info('populate_table {}'.format(source_table_name))

        dest_metadata = MetaData()
        dest_table = Table(
            dest_table_name,
            dest_metadata,
            autoload=True,
            autoload_with=self.database.engine)

        insert_statement = dest_table.insert()

        source_metadata = MetaData()
        source_table = Table(
            source_table_name,
            source_metadata,
            autoload=True,
            autoload_with=partition.database.engine)

        if replace:
            insert_statement = insert_statement.prefix_with('OR REPLACE')

        cols = [
            ' {} AS "{}" '.format(
                c[0].name if c[0].name != 'geometry' else 'AsText(geometry)',
                c[1].name) for c in zip(
                source_table.columns,
                dest_table.columns)]

        select_statement = " SELECT {} FROM {} ".format(
            ','.join(cols),
            source_table.name)

        if where:
            select_statement += " WHERE " + where

        binary_cols = []
        for c in dest_table.columns:
            if isinstance(c.type, BYTEA):
                binary_cols.append(c.name)

        # Psycopg executemany function doesn't use the multiple insert syntax of Postgres,
        # so it is fantastically slow. So, we have to do it ourselves.
        # Using multiple row inserts is more than 100 times faster.
        import re

        # For Psycopg's mogrify(), we need %(var)s parameters, not :var
        insert_statement = re.sub(
            r':([\w_-]+)',
            r'%(\1)s',
            str(insert_statement))

        conn = self.database.engine.raw_connection()

        with conn.cursor() as cur:

            def execute_many(insert_statement, values):

                mogd_values = []

                inst, vals = insert_statement.split("VALUES")

                for value in values:
                    mogd = cur.mogrify(insert_statement, value)
                    # Hopefully, including the parens will make it unique enough to not
                    # cause problems. Using just 'VALUES' files when there is a
                    # column of the same name.
                    _, vals = mogd.split(") VALUES (", 1)

                    mogd_values.append("(" + vals)

                sql = inst + " VALUES " + ','.join(mogd_values)

                cur.execute(sql)

            cache = []

            for i, row in enumerate(partition.database.session.execute(select_statement)):

                self.logger.progress('add_row', source_table_name, i)

                if binary_cols:
                    # This is really horrible. To insert a binary column property, it has to be run rhough
                    # function.
                    cache.append(
                        {k: psycopg2.Binary(v) if k in binary_cols else v for k, v in row.items()})

                else:
                    cache.append(dict(row))

                if len(cache) >= cache_size:
                    self.logger.info('committing {} rows'.format(len(cache)))
                    execute_many(insert_statement, cache)
                    cache = []

            if len(cache):
                self.logger.info('committing {} rows'.format(len(cache)))
                execute_many(insert_statement, cache)

        conn.commit()

        self.logger.info('done {}'.format(partition.identity.vname))

        return dest_table_name

    def remove(self, name):
        from ..orm import Dataset
        from ..bundle import LibraryDbBundle
        from ..identity import PartitionNameQuery
        from sqlalchemy.exc import NoSuchTableError, ProgrammingError

        dataset = self.wlibrary.resolve(name)

        if dataset.partition:
            b = LibraryDbBundle(self.library.database, dataset.vid)
            p = b.partitions.find(id_=dataset.partition.vid)
            self.logger.info(
                "Dropping tables in partition {}".format(
                    p.identity.vname))
            for table_name in p.tables:  # Table name without the id prefix

                table_name, alias = self.augmented_table_name(
                    p.identity, table_name)

                try:
                    self.database.drop_table(table_name)
                    self.logger.info("Dropped table: {}".format(table_name))

                except NoSuchTableError:
                    self.logger.info(
                        "Table does not exist (a): {}".format(table_name))

                except ProgrammingError:
                    self.logger.info(
                        "Table does not exist (b): {}".format(table_name))

            self.library.database.remove_partition(dataset.partition)

        elif dataset:

            b = LibraryDbBundle(self.library.database, dataset.vid)
            for p in b.partitions:
                self.remove(p.identity.vname)

            self.logger.info('Removing bundle {}'.format(dataset.vname))
            self.library.database.remove_bundle(b)
        else:
            self.logger.error(
                "Failed to find partition or bundle by name '{}'".format(name))

    def run_sql(self, sql_text):

        self.database.connection.execute(sql_text)

    ##
    # users
    ##

    def get(self, name_or_id):
        """Return true if the warehouse already has the referenced bundle or
        partition."""

        return self.library.resolve(name_or_id)

    def has(self, ref):
        r = self.library.resolve(ref)

        if bool(r):
            return True
        else:
            return False

    def has_table(self, table_name):
        return table_name in self.database.inspector.get_table_names()

    def create_table(self, partition, table_name):
        """Create the table in the warehouse, using an augmented table name."""
        from ..schema import Schema

        meta, table = self.table_meta(partition.identity, table_name)

        if not self.has_table(table.name):
            table.create(bind=self.database.engine)
            self.logger.info('create_table {}'.format(table.name))
        else:
            self.logger.info('table_exists {}'.format(table.name))

        return table, meta

        # def create_index(self, name, table, columns):
        #
        #     from sqlalchemy.exc import OperationalError, ProgrammingError
        #
        #     sql = 'CREATE INDEX {} ON "{}" ({})'.format(
        #         name,
        #         table,
        #         ','.join(columns))
        #
        #     try:
        #         self.database.connection.execute(sql)
        #         self.logger.info('create_index {}'.format(name))
        #     except (OperationalError, ProgrammingError) as e:
        #
        #         if 'exists' not in str(e).lower():
        #             raise
        #
        #         self.logger.info('index_exists {}'.format(name))
        #         # Ignore if it already exists.

    def _to_vid(self, partition):
        from ..partition import PartitionBase
        from ..identity import Identity
        from ..dbexceptions import NotFoundError

        if isinstance(partition, basestring):
            dsid = self.elibrary.resolve(partition)

            if not dsid:
                raise NotFoundError(
                    "Didn't find {} in external library".format(partition))

            if not dsid.partition:
                raise ResolutionError(
                    "Term referred to a dataset, not a partition: {}".format(partition))

            pid = dsid.partition.vid

        elif isinstance(partition, PartitionBase):
            pid = partition.identity.vid
        elif isinstance(partition, Identity):
            pid = partition.vid
        else:
            pid = partition

        return pid

    def _partition_to_dataset_vid(self, partition):
        from ..partition import PartitionBase
        from ..identity import Identity

        if isinstance(partition, PartitionBase):
            did = partition.identity.as_dataset().vid
        elif isinstance(partition, Identity):
            did = partition.as_dataset().vid
        else:
            from ..identity import ObjectNumber

            did = str(ObjectNumber(str(partition)).dataset)

        return did

    def augmented_table_name(self, identity, table_name):
        """Create a table name that is prefixed with the dataset number and the
        partition grain, if it has one."""

        name = identity.vid.replace('/', '_') + '_' + table_name

        if identity.grain:
            name = name + '_' + identity.grain

        alias = identity.id_.replace('/', '_') + '_' + table_name

        if identity.grain:
            alias = alias + '_' + identity.grain

        return name, alias

    def _ogr_args(self, partition):
        """Return a arguments for ogr2ogr to connect to the database."""
        raise NotImplementedError()

    def list(self):
        from ..orm import Partition
        from ..identity import LocationRef

        orms = self.wlibrary.database.session.query(
            Partition).filter(Partition.installed == 'y').all()

        idents = []

        for p in orms:
            ident = p.identity
            ident.locations.set(LocationRef.LOCATION.WAREHOUSE)
            idents.append(ident)

        return sorted(idents, key=lambda x: x.fqname)

    def info(self):
        config = self.config.to_dict()

        if 'password' in config['database']:
            del config['database']['password']
        return config

    ##
    # Extracts
    ###

    def extract_all(self, force=False):
        """Generate the extracts and return a struture listing the extracted
        files."""
        from contextlib import closing

        from .extractors import new_extractor
        import time
        from ..util import md5_for_file

        # Get the URL to the root. The public_utl arg only affects S3, and
        # gives a URL without a signature.
        root = self.cache.path('', missing_ok=True, public_url=True)

        extracts = []

        # Generate the file etracts

        for f in self.library.files.query.group('manifest').type('extract').all:

            t = self.orm_table_by_name(f.data['table'])

            if (t and t.data.get('updated') and
                f.modified and
                    int(t.data.get('updated')) > f.modified) or (not f.modified):
                force = True

            ex = new_extractor(
                f.data.get('format'),
                self,
                self.cache,
                force=force)

            e = ex.extract(f.data['table'], self.cache, f.path)

            extracts.append(e)

            if e.time:
                f.modified = e.time

                if os.path.exists(e.abs_path):
                    f.hash = md5_for_file(e.abs_path)
                    f.size = os.path.getsize(e.abs_path)

                self.library.files.merge(f)

        return extracts

    def extract_table(self, tid, content_type='csv'):
        from .extractors import new_extractor
        from os.path import basename, dirname
        from ..dbexceptions import NotFoundError

        t = self.orm_table(tid)  # For installed tables

        if not t:
            t = self.orm_table_by_name(tid)  # For views

        if not t:
            raise NotFoundError("Didn't get table for '{}' ".format(tid))

        e = new_extractor(content_type, self, self.cache.subcache('extracts'))

        ref = t.name if t.type in ('view', 'mview') else t.vid

        ee = e.extract(
            ref, '{}.{}'.format(
                tid, content_type), t.data.get(
                'updated', None))

        return ee.abs_path, "{}_{}.{}".format(t.vid, t.name, content_type)


def database_config(db, base_dir=''):
    import urlparse
    import os
    from ..dbexceptions import ConfigurationError

    parts = urlparse.urlparse(db)

    path = parts.path

    scheme = parts.scheme

    if '+' in scheme:
        scheme, _ = scheme.split('+', 1)

    if scheme in ('sqlite', "spatialite"):
        # Sqlalchemy expects 4 slashes for absolute paths, 3 for relative,
        # which is hard to manage reliably. So, fixcommon problems.

        if parts.netloc or (path and path[0] != '/'):
            raise ConfigurationError(
                'DSN Parse error. For Sqlite and Sptialite, the DSN should have 3 or 4 slashes')

        if path:
            path = path[1:]

            if path[0] != '/':
                path = os.path.join(base_dir, path)

    if scheme == 'sqlite':
        config = dict(
            service='sqlite',
            database=dict(
                dbname=os.path.join(
                    base_dir,
                    path),
                driver='sqlite'))

    elif scheme == 'spatialite':

        config = dict(
            service='spatialite',
            database=dict(
                dbname=os.path.join(
                    base_dir,
                    path),
                driver='spatialite'))

    elif scheme == 'postgres' or scheme == 'postgresql':
        config = dict(service='postgres',
                      database=dict(driver='postgres',
                                    server=parts.hostname,
                                    username=parts.username,
                                    password=parts.password,
                                    dbname=path.strip('/')
                                    ))

    elif scheme == 'postgis':
        config = dict(service='postgis',
                      database=dict(driver='postgis',
                                    server=parts.hostname,
                                    username=parts.username,
                                    password=parts.password,
                                    dbname=parts.path.strip('/')
                                    ))
    else:
        raise ValueError(
            "Unknown database connection scheme for  {}".format(db))

    return config


class Logger(object):

    def __init__(self, logger, lr):
        self.lr = lr
        self.logger = logger
        self.lr('Init warehouse logger')

    def progress(self, type_, name, n, message=None):
        self.lr("{} {}: {}".format(type_, name, n))

    def copy(self, o, t):
        self.lr("{} {}".format(o, t))

    def info(self, message):
        self.logger.info(message)

    def log(self, message):
        self.logger.info(message)

    def error(self, message):
        self.logger.error(message)

    def fatal(self, message):
        self.logger.fatal(message)

    def warn(self, message):
        self.logger.warn(message)
