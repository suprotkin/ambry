__author__ = "Roman Suprotkin"
__email__ = "roman.suprotkin@developex.org"
import argparse
import contextlib
import logging
import importlib
import sys
import subprocess

import ambry.cli
from ambry.run import RunConfig, get_runconfig
from test_base import TestBase
from test_cli import TestCLIMixin, TestLoggingFileHandlerMixin

@contextlib.contextmanager
def capture():
    from cStringIO import StringIO
    oldout, olderr = sys.stdout, sys.stderr
    try:
        out = [StringIO(), StringIO()]
        sys.stdout, sys.stderr = out
        yield out
    finally:
        sys.stdout, sys.stderr = oldout, olderr
        out[0] = out[0].getvalue()
        out[1] = out[1].getvalue()


class Test(TestCLIMixin, TestLoggingFileHandlerMixin, TestBase):
    parser = None
    logger_name = 'test_cli_command'
    logging_dir = '/tmp'
    logging_level = logging.INFO
    executers = {}

    def setUp(self):
        super(Test, self).setUp()
        # TODO: Create args to be passed in command
        self.parser = ambry.cli.get_parser()
        ambry.cli.global_logger = self.logger

    def format_args(self, *args):
        """
            @rtype: argparse.Namespace
        """
        return self.parser.parse_args(args, namespace=argparse.Namespace(config=self.config_file))

    def updateRC(self):
        self.rc = get_runconfig((self.config_file, RunConfig.USER_ACCOUNTS))

    def cmd(self, command, reset_lib=False, print_args=False):
        if isinstance(command, basestring):
            command = filter(bool, command.split(' '))
        args = self.format_args(*command)
        if print_args:
            print '== %s' % args
        try:
            executer = self.executers[args.command]
        except KeyError:
            try:
                self.executers[args.command] = executer = importlib.import_module('ambry.cli.%s' % args.command)
            except ImportError:
                raise ImportError('Unknown command "%s" or module is not imported' % args.command)
        kwargs = reset_lib and {'reset_lib': True} or {}

        with capture() as out:
            getattr(executer, '%s_command' % args.command)(args, self.rc, **kwargs)
        return out[0]

    def test_source_buildable(self):
        print self.cmd('info')
        print self.cmd('library drop')
        print self.cmd('library sync -s', reset_lib=True)

        bundle_list = self.cmd('list')
        print bundle_list
        self.assertIn(' S     dIjqPRbrGq001', bundle_list)
        self.assertNotIn('LS     d00H003', bundle_list)
        self.assertIn('example.com-simple-0.1.3', bundle_list)
        self.assertIn('example.com-random-0.0.2', bundle_list)
        buildable = [x.strip() for x in self.cmd('source buildable -Fvid').splitlines()]
        for vid in buildable:
            print self.cmd('bundle -d {} build --clean --install '.format(vid), print_args=True)

        bundle_list = self.cmd('list')
        print bundle_list
        self.assertIn(' S     dHSyDm4MNR002     example.com-random-0.0.2', bundle_list)
        self.assertIn('LS     d042001           example.com-downloads-0.0.1', bundle_list)

        self.cmd('library push')

        # Can't rebuild an installed bundle.
        with self.assertRaises(subprocess.CalledProcessError):
            self.cmd('bundle -d d042001 prepare --clean ')


