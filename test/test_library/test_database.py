# -*- coding: utf-8 -*-
import inspect
import os
import shutil
import unittest
from tempfile import mkdtemp

import fudge
from fudge.inspector import arg

from sqlalchemy.engine.reflection import Inspector
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.query import Query

from ambry.library.database import LibraryDb, ROOT_CONFIG_NAME_V, ROOT_CONFIG_NAME
from ambry.orm import Dataset, Config, Partition, File, Column, ColumnStat, Table, Code
from ambry.dbexceptions import ConflictError
from ambry.database.inserter import ValueInserter

from test.test_library.factories import DatasetFactory, ConfigFactory,\
    TableFactory, ColumnFactory, FileFactory, PartitionFactory, CodeFactory,\
    ColumnStatFactory

TEST_TEMP_DIR = 'test-library-'


class LibraryDbTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_temp_dir = mkdtemp(prefix=TEST_TEMP_DIR)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.test_temp_dir)

    def setUp(self):
        self.test_temp_dir = self.__class__.test_temp_dir
        library_db_file = os.path.join(self.test_temp_dir, 'test_database.db')
        self.sqlite_db = LibraryDb(driver='sqlite', dbname=library_db_file)
        self.sqlite_db.enable_delete = True

        # each factory requires db session. Populate all of them here, because we know the session.
        DatasetFactory._meta.sqlalchemy_session = self.sqlite_db.session
        TableFactory._meta.sqlalchemy_session = self.sqlite_db.session
        ColumnFactory._meta.sqlalchemy_session = self.sqlite_db.session
        PartitionFactory._meta.sqlalchemy_session = self.sqlite_db.session
        ColumnStatFactory._meta.sqlalchemy_session = self.sqlite_db.session
        ConfigFactory._meta.sqlalchemy_session = self.sqlite_db.session
        FileFactory._meta.sqlalchemy_session = self.sqlite_db.session
        CodeFactory._meta.sqlalchemy_session = self.sqlite_db.session

    def tearDown(self):
        fudge.clear_expectations()
        fudge.clear_calls()
        try:
            os.remove(self.sqlite_db.dbname)
        except OSError:
            pass

    # helpers
    def _assert_exists(self, model_class, **filter_kwargs):
        query = self.sqlite_db.session.query(model_class)\
            .filter_by(**filter_kwargs)
        assert query.first() is not None

    def _assert_does_not_exist(self, model_class, **filter_kwargs):
        query = self.sqlite_db.session.query(model_class)\
            .filter_by(**filter_kwargs)
        assert query.first() is None

    @unittest.skip('Will implement it just before merge.')
    def test_initialization_raises_exception_if_driver_not_found(self):
        with self.assertRaises(ValueError):
            LibraryDb(driver='1')

    def test_initialization_populates_port(self):
        db = LibraryDb(driver='postgres', port=5232)
        self.assertIn('5232', db.dsn)

    def test_initialization_uses_library_schema_for_postgres(self):
        db = LibraryDb(driver='postgres')
        self.assertEquals(db._schema, 'library')

    def test_initialization_uses_library_schema_for_postgis(self):
        db = LibraryDb(driver='postgis')
        self.assertEquals(db._schema, 'library')

    @fudge.patch(
        'sqlalchemy.create_engine')
    def test_engine_creates_new_sqlalchemy_engine(self, fake_create):
        engine_stub = fudge.Fake().is_a_stub()
        fake_create.expects_call()\
            .returns(engine_stub)
        db = LibraryDb(driver='postgis')
        self.assertEquals(db.engine, engine_stub)

    @fudge.patch(
        'sqlalchemy.create_engine',
        'sqlalchemy.event',
        'ambry.database.sqlite._on_connect_update_sqlite_schema')
    def test_engine_listens_to_connect_signal_for_sqlite_driver(self, fake_create,
                                                                fake_event, fake_on):
        fake_event\
            .provides('listen')
        engine_stub = fudge.Fake().is_a_stub()
        fake_create.expects_call()\
            .returns(engine_stub)
        fake_on.expects_call()
        db = LibraryDb(driver='sqlite')
        self.assertEquals(db.engine, engine_stub)

    def test_connection_creates_new_sqlalchemy_connection(self):
        fake_connection = fudge.Fake()

        fake_engine = fudge.Fake()\
            .provides('connect')\
            .returns(fake_connection)

        db = LibraryDb(driver='sqlite')
        db._engine = fake_engine
        self.assertEquals(db.connection, fake_connection)

    def test_connection_sets_path_to_library_for_postgres(self):
        fake_connection = fudge.Fake('connection')\
            .provides('execute')\
            .with_args('SET search_path TO library')\
            .expects_call()

        fake_engine = fudge.Fake()\
            .provides('connect')\
            .returns(fake_connection)

        db = LibraryDb(driver='postgres')
        db._engine = fake_engine
        self.assertEquals(db.connection, fake_connection)

    def test_connection_sets_path_to_library_for_postgis(self):
        fake_connection = fudge.Fake('connection')\
            .provides('execute')\
            .with_args('SET search_path TO library')\
            .expects_call()

        fake_engine = fudge.Fake()\
            .provides('connect')\
            .returns(fake_connection)

        db = LibraryDb(driver='sqlite')
        db._engine = fake_engine
        self.assertEquals(db.connection, fake_connection)

    # .close tests
    def test_closes_session_and_connection(self):
        db = LibraryDb(driver='sqlite')
        db.session.close = fudge.Fake('session.close').expects_call()
        db.connection.close = fudge.Fake('connection.close').expects_call()
        db.close()
        fudge.verify()
        self.assertIsNone(db._session)
        self.assertIsNone(db._connection)

    # .commit tests
    def test_commit_commits_session(self):
        fake_session = fudge.Fake('session')\
            .provides('commit')\
            .expects_call()
        db = LibraryDb(driver='sqlite')
        db.Session = fake_session
        db._session = fake_session
        db.commit()

    def test_commit_raises_session_commit_exception(self):
        fake_session = fudge.Fake('session')\
            .provides('commit')\
            .expects_call()\
            .raises(ValueError)
        db = LibraryDb(driver='sqlite')
        db.Session = fake_session
        db._session = fake_session
        with self.assertRaises(ValueError):
            db.commit()

    # .rollback tests
    def test_rollbacks_session(self):
        self.sqlite_db.session.rollback = fudge.Fake('session.rollback').expects_call()
        self.sqlite_db.rollback()
        fudge.verify()

    # .inspector tests
    def test_contains_engine_inspector(self):
        db = LibraryDb(driver='sqlite')
        self.assertIsInstance(db.inspector, Inspector)
        self.assertEquals(db.engine, db.inspector.engine)

    # .exists tests
    def test_sqlite_database_does_not_exists_if_file_not_found(self):
        db = LibraryDb(driver='sqlite', dbname='no-such-file.db')
        self.assertFalse(db.exists())

    # clean tests
    def test_clean_deletes_all_instances(self):
        self.sqlite_db.create_tables()

        conf1 = ConfigFactory()
        ds1 = DatasetFactory()
        file1 = FileFactory()
        code1 = CodeFactory()
        partition1 = PartitionFactory(dataset=ds1)

        table1 = TableFactory(dataset=ds1)
        column1 = ColumnFactory(table=table1)
        colstat1 = ColumnStatFactory(partition=partition1, column=column1)

        self.sqlite_db.session.commit()

        models = [
            (Code, dict(oid=code1.oid)),
            (Column, dict(vid=column1.vid)),
            (ColumnStat, dict(id=colstat1.id)),
            (Config, dict(d_vid=conf1.d_vid)),
            (Dataset, dict(vid=ds1.vid)),
            (File, dict(path=file1.path)),
            (Partition, dict(vid=partition1.vid)),
            (Table, dict(vid=table1.vid))
        ]

        # validate existance
        for model, kwargs in models:
            self._assert_exists(model, **kwargs)

        self.sqlite_db.clean()

        for model, kwargs in models:
            self._assert_does_not_exist(model, **kwargs)

    def _assert_spec(self, fn, expected_args):
        """ Matches function arguments to the expected arguments. Raises AssertionError on
            mismatch.
        """
        fn_args = inspect.getargspec(fn).args
        msg = '{} function requires {} args, but you expect {}'\
            .format(fn, fn_args, expected_args)
        self.assertEquals(fn_args, expected_args, msg)

    # .create tests
    def test_creates_new_database(self):
        # first assert signatures of the functions we are going to mock did not change.
        self._assert_spec(self.sqlite_db._create_path, ['self'])
        self._assert_spec(self.sqlite_db.exists, ['self'])
        self._assert_spec(self.sqlite_db.create_tables, ['self'])
        self._assert_spec(self.sqlite_db._add_config_root, ['self'])

        # prepare state
        self.sqlite_db.exists = fudge.Fake('exists').expects_call().returns(False)
        self.sqlite_db._create_path = fudge.Fake('_create_path').expects_call()
        self.sqlite_db.create_tables = fudge.Fake('create_tables').expects_call()
        self.sqlite_db._add_config_root = fudge.Fake('_add_config_root').expects_call()
        ret = self.sqlite_db.create()
        self.assertTrue(ret)
        fudge.verify()

    def test_returns_false_if_database_exists(self):
        # first assert signatures of the functions we are going to mock did not change.
        self._assert_spec(self.sqlite_db.exists, ['self'])

        # prepare state
        self.sqlite_db.exists = fudge.Fake('exists').expects_call().returns(True)
        ret = self.sqlite_db.create()
        self.assertFalse(ret)
        fudge.verify()

    # ._create_path tests
    def test_makes_database_directory(self):
        # first assert signatures of the functions we are going to mock did not change.
        self._assert_spec(os.makedirs, ['name', 'mode'])
        self._assert_spec(os.path.exists, ['path'])

        # prepare state
        fake_makedirs = fudge.Fake('makedirs').expects_call()
        fake_exists = fudge.Fake('exists')\
            .expects_call()\
            .returns(False)\
            .next_call()\
            .returns(True)
        library_db_file = os.path.join(self.test_temp_dir, 'no-such-dir', 'test_database1.db')

        # test
        with fudge.patched_context(os, 'makedirs', fake_makedirs):
            with fudge.patched_context(os.path, 'exists', fake_exists):
                db = LibraryDb(driver='sqlite', dbname=library_db_file)
                db._create_path()
        fudge.verify()

    def test_ignores_exception_if_makedirs_failed(self):
        # first assert signatures of the functions we are going to mock did not change.
        self._assert_spec(os.makedirs, ['name', 'mode'])

        fake_makedirs = fudge.Fake('makedirs')\
            .expects_call()\
            .raises(Exception('My fake exception'))

        fake_exists = fudge.Fake('exists')\
            .expects_call()\
            .returns(False)\
            .next_call()\
            .returns(True)
        library_db_file = os.path.join(self.test_temp_dir, 'no-such-dir', 'test_database1.db')

        # test
        with fudge.patched_context(os, 'makedirs', fake_makedirs):
            with fudge.patched_context(os.path, 'exists', fake_exists):
                db = LibraryDb(driver='sqlite', dbname=library_db_file)
                db._create_path()
        fudge.verify()

    def test_raises_exception_if_dir_does_not_exists_after_creation_attempt(self):
        # first assert signatures of the functions we are going to mock did not change.
        self._assert_spec(os.makedirs, ['name', 'mode'])
        self._assert_spec(os.path.exists, ['path'])

        # prepare state
        fake_makedirs = fudge.Fake('makedirs')\
            .expects_call()

        fake_exists = fudge.Fake('exists')\
            .expects_call()\
            .returns(False)\
            .next_call()\
            .returns(False)
        library_db_file = os.path.join(self.test_temp_dir, 'no-such-dir', 'test_database1.db')

        # test
        with fudge.patched_context(os, 'makedirs', fake_makedirs):
            with fudge.patched_context(os.path, 'exists', fake_exists):
                try:
                    db = LibraryDb(driver='sqlite', dbname=library_db_file)
                    db._create_path()
                except Exception as exc:
                    self.assertIn('Couldn\'t create directory', exc.message)
        fudge.verify()

    # .drop tests
    def test_does_not_allow_to_delete_if_deleting_disabled(self):
        self.sqlite_db.enable_delete = False
        try:
            self.sqlite_db.drop()
        except Exception as exc:
            self.assertIn('Deleting not enabled', exc.message)

    # .clone tests
    def test_clone_returns_new_instance(self):
        db = LibraryDb(driver='sqlite')
        new_db = db.clone()
        self.assertNotEquals(db, new_db)
        self.assertEquals(db.driver, new_db.driver)
        self.assertEquals(db.server, new_db.server)
        self.assertEquals(db.dbname, new_db.dbname)
        self.assertEquals(db.username, new_db.username)
        self.assertEquals(db.password, new_db.password)

    # .create_tables test
    def test_creates_dataset_table(self):
        self.sqlite_db.create_tables()

        # Now all tables are created. Can we use ORM to create datasets?
        DatasetFactory()
        self.sqlite_db.session.commit()

    def test_creates_config_table(self):
        self.sqlite_db.create_tables()

        # Now all tables are created. Can we use ORM to create configs?
        ConfigFactory(key='a', value='b')
        self.sqlite_db.session.commit()

    def test_creates_table_table(self):
        self.sqlite_db.create_tables()

        # Now all tables are created. Can we use ORM to create datasets?
        ds1 = DatasetFactory()
        self.sqlite_db.session.commit()
        TableFactory(dataset=ds1)
        self.sqlite_db.session.commit()

    def test_creates_column_table(self):
        self.sqlite_db.create_tables()

        # Now all tables are created. Can we use ORM to create columns?

        # Column requires table and dataset.
        ds1 = DatasetFactory()
        self.sqlite_db.session.commit()

        table1 = TableFactory(dataset=ds1)
        self.sqlite_db.session.commit()

        ColumnFactory(table=table1)
        self.sqlite_db.session.commit()

    def test_creates_file_table(self):
        self.sqlite_db.create_tables()
        FileFactory()

        self.sqlite_db.session.commit()

    def test_creates_partition_table(self):
        self.sqlite_db.create_tables()

        ds1 = DatasetFactory()
        PartitionFactory(dataset=ds1)
        self.sqlite_db.session.commit()

    def test_creates_code_table(self):
        self.sqlite_db.create_tables()
        CodeFactory()
        self.sqlite_db.session.commit()

    def test_creates_columnstat_table(self):
        self.sqlite_db.create_tables()

        ds1 = DatasetFactory()
        self.sqlite_db.session.commit()
        partition1 = PartitionFactory(dataset=ds1)

        table1 = TableFactory(dataset=ds1)
        self.sqlite_db.session.commit()

        column1 = ColumnFactory(table=table1)

        ColumnStatFactory(partition=partition1, column=column1)
        self.sqlite_db.session.commit()

    # ._add_config_root
    def test_creates_new_root_config(self):
        # prepare state
        self.sqlite_db.create_tables()
        datasets = self.sqlite_db.session.query(Dataset).all()
        self.assertEquals(len(datasets), 0)

        # testing
        self.sqlite_db._add_config_root()
        datasets = self.sqlite_db.session.query(Dataset).all()
        self.assertEquals(len(datasets), 1)
        self.assertEquals(datasets[0].name, ROOT_CONFIG_NAME)
        self.assertEquals(datasets[0].vname, ROOT_CONFIG_NAME_V)

    def test_closes_session_if_root_config_exists(self):
        # first assert signatures of the functions we are going to mock did not change.
        self._assert_spec(self.sqlite_db.close_session, ['self'])

        # prepare state
        self.sqlite_db.create_tables()
        ds = DatasetFactory(vid=ROOT_CONFIG_NAME)
        ds.vid = ROOT_CONFIG_NAME
        self.sqlite_db.session.merge(ds)
        self.sqlite_db.close_session = fudge.Fake('close_session').expects_call()

        # testing
        self.sqlite_db._add_config_root()
        fudge.verify()

    # ._clean_config_root tests
    def tests_resets_instance_fields(self):
        self.sqlite_db.create_tables()
        ds = DatasetFactory()
        ds.id_ = ROOT_CONFIG_NAME
        ds.name = 'name'
        ds.vname = 'vname'
        ds.source = 'source'
        ds.dataset = 'dataset'
        ds.creator = 'creator'
        ds.revision = 33
        self.sqlite_db.session.merge(ds)
        self.sqlite_db.commit()

        self.sqlite_db._clean_config_root()

        # refresh dataset
        ds = self.sqlite_db.session.query(Dataset).filter(
            Dataset.id_ == ROOT_CONFIG_NAME).one()
        self.assertEquals(ds.name, ROOT_CONFIG_NAME)
        self.assertEquals(ds.vname, ROOT_CONFIG_NAME_V)
        self.assertEquals(ds.source, ROOT_CONFIG_NAME)
        self.assertEquals(ds.dataset, ROOT_CONFIG_NAME)
        self.assertEquals(ds.creator, ROOT_CONFIG_NAME)
        self.assertEquals(ds.revision, 1)

    # .inserter test
    # TODO: ValueInserter does not work without bundle. Fix it.
    @unittest.skip('ValueInserter requires bundle, but inserter method gives None instead.')
    def test_returns_value_inserter(self):
        self.sqlite_db.create_tables()
        ret = self.sqlite_db.inserter('datasets')
        self.assertIsInstance(ret, ValueInserter)

    # set_config_value tests
    def test_creates_new_config_if_config_does_not_exists(self):
        self.sqlite_db.create_tables()
        self.sqlite_db.commit()
        group = 'group-1'
        key = 'key-1'
        value = 'value-1'
        self.sqlite_db.set_config_value(group, key, value)
        self._assert_exists(Config, group=group, key=key, value=value)

    def test_changes_existing_config(self):
        self.sqlite_db.create_tables()
        self.sqlite_db.commit()
        group = 'group-1'
        key = 'key-1'
        value = 'value-1'

        ConfigFactory(group=group, key=key, value=value, d_vid=ROOT_CONFIG_NAME_V)
        self._assert_exists(Config, group=group, key=key, value=value)

        new_value = 'value-2'
        self.sqlite_db.set_config_value(group, key, new_value)
        self._assert_exists(Config, group=group, key=key, value=new_value)
        self._assert_does_not_exist(Config, value=value)

    # get_config_value tests
    def test_returns_config(self):
        self.sqlite_db.create_tables()
        self.sqlite_db.commit()
        group = 'group-1'
        key = 'key-1'
        value = 'value-1'

        ConfigFactory(group=group, key=key, value=value, d_vid=ROOT_CONFIG_NAME_V)
        ret = self.sqlite_db.get_config_value(group, key)
        self.assertIsNotNone(ret)
        self.assertEquals(ret.value, value)

    def test_returns_none_if_config_does_not_exist(self):
        self.sqlite_db.create_tables()
        self.sqlite_db.commit()
        ret = self.sqlite_db.get_config_value('group1', 'key1')
        self.assertIsNone(ret)

    def test_returns_none_if_config_query_failed(self):
        self.sqlite_db.create_tables()
        self.sqlite_db.commit()
        fake_filter = fudge.Fake()\
            .expects_call()\
            .raises(Exception('MyFakeException'))
        with fudge.patched_context(Query, 'filter', fake_filter):
            ret = self.sqlite_db.get_config_value('group1', 'key1')
            self.assertIsNone(ret)

    # get_config_group tests
    def test_returns_dict_with_key_and_values(self):
        self.sqlite_db.create_tables()
        self.sqlite_db.commit()
        group1 = 'group-1'
        key1 = 'key-1'
        value1 = 'value-1'

        key2 = 'key-2'
        value2 = 'value-2'

        ConfigFactory(group=group1, key=key1, value=value1, d_vid=ROOT_CONFIG_NAME_V)
        ConfigFactory(group=group1, key=key2, value=value2, d_vid=ROOT_CONFIG_NAME_V)

        ret = self.sqlite_db.get_config_group(group1)
        self.assertIn(key1, ret)
        self.assertIn(key2, ret)

        self.assertEquals(ret[key1], value1)
        self.assertEquals(ret[key2], value2)

    def test_returns_empty_dict_if_group_does_not_exist(self):
        self.sqlite_db.create_tables()
        self.sqlite_db.commit()

        group1 = 'group-1'
        self._assert_does_not_exist(Config, group=group1)

        ret = self.sqlite_db.get_config_group(group1)
        self.assertEquals(ret, {})

    # .get_config_rows tests
    def test_returns_config_config_with_key_splitted_by_commas(self):
        self.sqlite_db.create_tables()
        self.sqlite_db.commit()
        group1 = 'config'
        key1 = '1.2.3.5.6'

        config1 = ConfigFactory(group=group1, key=key1)
        ret = self.sqlite_db.get_config_rows(config1.d_vid)
        self.assertEquals(len(ret), 1)
        conf1 = ret[0]

        # check splitted key
        key = conf1[0]
        self.assertEquals(key[0], '1')
        self.assertEquals(key[1], '2')
        self.assertEquals(key[2], '3')

        # check value
        value = conf1[1]
        self.assertEquals(value, config1.value)

    def test_returns_process_with_key_splitted_by_commas(self):
        self.sqlite_db.create_tables()
        self.sqlite_db.commit()
        group1 = 'process'
        key1 = '1.2.3.5.6'

        config1 = ConfigFactory(group=group1, key=key1)
        ret = self.sqlite_db.get_config_rows(config1.d_vid)
        self.assertEquals(len(ret), 1)
        conf1 = ret[0]

        # check splitted key
        key = conf1[0]
        self.assertEquals(key[0], 'process')
        self.assertEquals(key[1], '1')
        self.assertEquals(key[2], '2')

        # check value
        value = conf1[1]
        self.assertEquals(value, config1.value)

    # .get_bundle_value
    def test_returns_config_value(self):
        # TODO: Strange method. Isn't .get_config().value the same?
        self.sqlite_db.create_tables()
        self.sqlite_db.commit()
        group = 'group-1'
        key = 'key-1'
        value = 'value-1'
        ConfigFactory(group=group, key=key, value=value, d_vid=ROOT_CONFIG_NAME_V)
        self.assertEquals(
            self.sqlite_db.get_bundle_value(ROOT_CONFIG_NAME_V, group, key),
            value)

    def test_returns_none_if_config_does_not_exists(self):
        # TODO: Strange method. Isn't .get_config().value the same?
        self.sqlite_db.create_tables()
        self.sqlite_db.commit()
        group = 'group-1'
        key = 'key-1'
        self.assertIsNone(self.sqlite_db.get_bundle_value(ROOT_CONFIG_NAME_V, group, key))

    # get_bundle_values
    def test_returns_configs_of_the_group(self):
        self.sqlite_db.create_tables()
        self.sqlite_db.commit()
        group = 'group-1'
        key1 = 'key-1'
        value1 = 'value-1'

        key2 = 'key-2'
        value2 = 'value-2'

        ConfigFactory(group=group, key=key1, value=value1, d_vid=ROOT_CONFIG_NAME_V)
        ConfigFactory(group=group, key=key2, value=value2, d_vid=ROOT_CONFIG_NAME_V)
        ret = self.sqlite_db.get_bundle_values(ROOT_CONFIG_NAME_V, group)
        self.assertEquals(len(ret), 2)
        values = [x.value for x in ret]
        self.assertIn(value1, values)
        self.assertIn(value2, values)

    def test_returns_empty_list_if_group_configs_do_not_exists(self):
        self.sqlite_db.create_tables()
        self.sqlite_db.commit()
        group = 'group-1'

        self.assertEquals(
            self.sqlite_db.get_bundle_values(ROOT_CONFIG_NAME_V, group),
            [])

    # .config_values property tests
    def test_contains_dict_with_groups_keys_and_values(self):
        self.sqlite_db.create_tables()
        self.sqlite_db.commit()
        group = 'group-1'
        key1 = 'key-1'
        value1 = 'value-1'

        group2 = 'group-2'
        key2 = 'key-2'
        value2 = 'value-2'

        ConfigFactory(group=group, key=key1, value=value1, d_vid=ROOT_CONFIG_NAME_V)
        ConfigFactory(group=group2, key=key2, value=value2, d_vid=ROOT_CONFIG_NAME_V)
        self.assertIn(
            (group, key1),
            self.sqlite_db.config_values)
        self.assertIn(
            (group2, key2),
            self.sqlite_db.config_values)

        self.assertEquals(
            self.sqlite_db.config_values[(group, key1)],
            value1)
        self.assertEquals(
            self.sqlite_db.config_values[(group2, key2)],
            value2)

    # ._mark_update test
    def test_updates_config(self):
        # first assert signatures of the functions we are going to mock did not change.
        self._assert_spec(self.sqlite_db.set_config_value, ['self', 'group', 'key', 'value'])

        self.sqlite_db.set_config_value = fudge.Fake('set_config_value')\
            .expects_call()\
            .with_args('activity', 'change', arg.any())

        self.sqlite_db._mark_update()
        fudge.verify()

    def test_contains_empty_dict(self):
        self.sqlite_db.create_tables()
        self.sqlite_db.commit()
        self.assertEquals(self.sqlite_db.config_values, {})

    # .install_dataset_identity tests
    def tests_installs_new_dataset_identity(self):
        self.sqlite_db.create_tables()

        class FakeIdentity(object):
            dict = {
                'source': 'source',
                'dataset': 'dataset',
                'revision': 1,
                'version': '0.1.1'}
            sname = 'sname'
            vname = 'vname'
            fqname = 'fqname'
            cache_key = 'cache_key'

        self.sqlite_db.install_dataset_identity(FakeIdentity())

        self._assert_exists(Dataset, name='sname')
        # TODO: test other fields

    def tests_raises_ConflictError_exception_if_save_failed(self):
        self.sqlite_db.create_tables()
        fake_commit = fudge.Fake('commit')\
            .expects_call()\
            .raises(IntegrityError('a', 'a', 'a'))
        self.sqlite_db.commit = fake_commit

        class FakeIdentity(object):
            dict = {
                'source': 'source',
                'dataset': 'dataset',
                'revision': 1,
                'version': '0.1.1'}
            vid = '1'
            sname = 'sname'
            vname = 'vname'
            fqname = 'fqname'
            cache_key = 'cache_key'

        with self.assertRaises(ConflictError):
            self.sqlite_db.install_dataset_identity(FakeIdentity(), overwrite=True)
