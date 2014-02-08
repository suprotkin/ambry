"""
Created on Jun 30, 2012

@author: eric
"""

import unittest
import os.path
from  testbundle.bundle import Bundle
from sqlalchemy import *
from ambry.run import  get_runconfig
from ambry.library.query import QueryCommand
from ambry.library import new_library
import logging
import ambry.util

from test_base import  TestBase

logger = ambry.util.get_logger(__name__)
logger.setLevel(logging.DEBUG) 

class Test(TestBase):
 
    def setUp(self):
        import testbundle.bundle
        from ambry.run import RunConfig

        self.bundle_dir = os.path.dirname(testbundle.bundle.__file__)
        self.rc = get_runconfig((os.path.join(self.bundle_dir,'warehouse-test-config.yaml'),
                                 os.path.join(self.bundle_dir,'bundle.yaml'),
                                 RunConfig.USER_ACCOUNTS))

        self.copy_or_build_bundle()

        self.bundle = Bundle()    

        print "Deleting: {}".format(self.rc.group('filesystem').root_dir)
        ambry.util.rm_rf(self.rc.group('filesystem').root_dir)

    def tearDown(self):
        pass

    def resolver(self,name):
        if name == self.bundle.identity.name or name == self.bundle.identity.vname:
            return self.bundle
        else:
            return False

    def get_library(self, name='default'):
        """Clear out the database before the test run"""
        from ambry.library import new_library

        config = self.rc.library(name)

        l = new_library(config, reset=True)

        return l

    
    def progress_cb(self, lr, type_,name,n):
        if n:
            lr("{} {}: {}".format(type, name, n))
        else:
            self.bundle.log("{} {}".format(type_, name))

    def get_warehouse(self, l, name):
        from  ambry.util import get_logger
        from ambry.warehouse import new_warehouse

        w = new_warehouse(self.rc.warehouse(name), l)
        w.logger = get_logger('unit_test')
        w.database.enable_delete = True

        lr = self.bundle.init_log_rate(10000)
        w.progress_cb = lambda type_, name, n: self.progress_cb(lr, type_, name, n)

        p = w.database.path
        if os.path.exists(p):
            os.remove(p)

        w.create()

        return w

    def test_local_install(self):

        l = self.get_library('local')

        w = self.get_warehouse(l, 'sqlite')

        l.put_bundle(self.bundle)

        for p in self.bundle.partitions.all:
            w.install(p)

    def test_remote_install(self):

        self.start_server(self.rc.library('server'))

        l = self.get_library('client')

        w = self.get_warehouse(l, 'sqlite')

        print "Warehouse", w.library.database.dsn

        l.put_bundle(self.bundle)

        for p in self.bundle.partitions.all:
            if p.identity.format == 'db':
                w.install(p)

        print


    def x_test_install(self):
        
        def resolver(name):
            if name == self.bundle.identity.name or name == self.bundle.identity.vname:
                return self.bundle
            else:
                return False
        
        def progress_cb(lr, type,name,n):
            if n:
                lr("{} {}: {}".format(type, name, n))
            else:
                self.bundle.log("{} {}".format(type, name))
        
        from ambry.warehouse import new_warehouse
        from functools import partial
        print "Getting warehouse"
        w = new_warehouse(self.rc.warehouse('postgres'))

        print "Re-create database"
        w.database.enable_delete = True
        w.resolver = resolver
        w.progress_cb = progress_cb
        
        try: w.drop()
        except: pass
        
        w.create()

        ps = self.bundle.partitions.all
        
        print "{} partitions".format(len(ps))
        
        for p in self.bundle.partitions:
            lr = self.bundle.init_log_rate(10000)
            w.install(p, progress_cb = partial(progress_cb, lr) )

        self.assertTrue(w.has(self.bundle.identity.vname))

        for p in self.bundle.partitions:
            self.assertTrue(w.has(p.identity.vname))

        for p in self.bundle.partitions:
            w.remove(p.identity.vname)

        print w.get(self.bundle.identity.name)
        print w.get(self.bundle.identity.vname)
        print w.get(self.bundle.identity.id_)
        
        w.install(self.bundle)
         
        print w.get(self.bundle.identity.name)
        print w.get(self.bundle.identity.vname)
        print w.get(self.bundle.identity.id_)

        for p in self.bundle.partitions:
            lr = self.bundle.init_log_rate(10000)
            w.install(p, progress_cb = partial(progress_cb, lr))
             

def suite():
    suite = unittest.TestSuite()
    suite.addTest(unittest.makeSuite(Test))
    return suite
      
if __name__ == "__main__":
    unittest.TextTestRunner().run(suite())