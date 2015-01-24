""" Bundle variants that directly load files with little additional processing.
"""


from  ambry.bundle import BuildBundle

class LoaderBundle(BuildBundle):

    def source_cache_key(self, fn):
        return  "{}/{}/{}".format(self.identity.source, self.identity.name, fn)

    def copy_sources(self):
        """Copy all of the sources to the build directory. If there is asource_store cache, also copy the
        file to the source store.


        """
        import shutil, os

        data = self.filesystem.build_path('data')

        cache = self.filesystem.source_store

        if not os.path.exists(data):
            os.makedirs(data)

        for k, v in self.metadata.sources.items():
            fn = self.filesystem.download(k)
            print fn

            base = os.path.basename(fn)
            dest = os.path.join(data, base)

            cache_key = self.source_cache_key(base)

            shutil.copyfile(fn , dest)

            if cache and not cache.has(cache_key):
                self.log("Putting: {}".format(cache_key))
                cache.put(fn, cache_key,  metadata=dict(vname=self.identity.vname))

class CsvBundle(LoaderBundle):
    """A Bundle variant for loading CSV files"""

    def get_source(self, source):
        """Get the source file. If the file does nto end in a CSV file, replace it with a CSV extension
        and look in the source store cache """
        import os

        if not source:
            source = self.metadata.sources.keys()[0]

        fn = self.filesystem.download(source)

        if fn.endswith('.zip'):
            fn = self.filesystem.unzip(fn)


        if not fn.lower().endswith('.csv'):
            cache = self.filesystem.source_store


            if cache:
                bare_fn, ext = os.path.splitext(os.path.basename(fn))

                fn_ck = self.source_cache_key(bare_fn+".csv")

                if cache.has(fn_ck):
                    if not self.filesystem.download_cache.has(fn_ck):
                        with cache.get_stream(fn_ck) as s:

                            self.filesystem.download_cache.put(s, fn_ck )

                    return self.filesystem.download_cache.path(fn_ck)


        return fn

    def gen_rows(self, source=None, as_dict=False):
        """Generate rows for a source file. The source value ust be specified in the sources config"""
        import csv

        fn = self.get_source(source)

        self.log("Generating rows from {}".format(fn))

        with open(fn) as f:

            if as_dict:
                r = csv.DictReader(f)
                for row in r:
                    row['id'] = None
                    yield row
            else:
                # It might seem inefficient to return the header every time, but it really adds only a
                # fraction of a section for millions of rows.
                r = csv.reader(f)
                header = ['id'] + r.next()

                header = [ x if x else "column{}".format(i) for i, x in enumerate(header)]

                for row in r:

                     yield header, [None] + row

    def source_header(self, source):
        import csv

        fn = self.get_source(source)

        with open(fn) as f:
            r = csv.reader(f)

            return ['id'] + r.next()

    def meta(self):

        self.database.create()

        if not self.run_args.get('clean', None):
            self._prepare_load_schema()

        for source_name, source in self.metadata.sources.items():

            table_name = source.table if source.table else  source_name

            table_desc = source.description if source.description else "Table generated from {}".format(source.url)

            data = {}

            if source.time: data['time'] = source.time
            if source.space: data['space'] = source.space
            if source.grain: data['grain'] = source.grain

            with self.session:
                table = self.schema.add_table(table_name, description=table_desc, data = data)

            header, row = self.gen_rows(source_name, as_dict=False).next()

            header = [ x for x in header if x]

            def itr():
                for header, row in self.gen_rows(source_name, as_dict=False):
                    yield row

            self.schema.update_from_iterator(table_name,
                               header = header,
                               iterator=itr(),
                               max_n=1000,
                               logger=self.init_log_rate(500))


        return True

    def build(self):

        for source in self.metadata.sources:

            p = self.partitions.find_or_new(table=source)

            p.clean()

            self.log("Loading source '{}' into partition '{}'".format(source, p.identity.name))

            lr = self.init_log_rate(print_rate = 5)

            header = [c.name for c in p.table.columns]

            with p.inserter() as ins:
               for _, row in self.gen_rows(source):
                   lr(str(p.identity.name))

                   d = dict(zip(header, row))

                   ins.insert(d)


        return True

class ExcelBuildBundle(CsvBundle):

    workbook = None # So the derived classes can et to the workbook, esp for converting dates

    def __init__(self, bundle_dir=None):
        '''
        '''

        super(ExcelBuildBundle, self).__init__(bundle_dir)

        if not self.metadata.build.requirements or not 'xlrd' in self.metadata.build.requirements:
            self.metadata.load_all()
            self.metadata.build.requirements.xlrd = 'xlrd'
            self.update_configuration()

    def srow_to_list(self, row_num, s):
        """Convert a sheet row to a list"""

        values = []

        for col in range(s.ncols):
            values.append(s.cell(row_num, col).value)

        return values

    def get_wb_sheet(self, source):

        if not source:
            source = self.metadata.sources.keys()[0]

        sheet_num = self.metadata.sources.get(source).segment
        sheet_num = 0 if not sheet_num else sheet_num

        return self.get_source(source), sheet_num

    def source_header(self, source):
        from xlrd import open_workbook

        fn, sheet_num = self.get_wb_sheet(source)

        with open(fn) as f:
            wb = open_workbook(fn)

            s = wb.sheets()[sheet_num]

            return ['id'] + self.srow_to_list(0, s)

    def gen_rows(self, source=None, as_dict=False):
        """Generate rows for a source file. The source value ust be specified in the sources config"""
        from xlrd import open_workbook

        fn, sheet_num = self.get_wb_sheet(source)

        header = self.source_header(source) if as_dict else None

        with open(fn) as f:

            wb = open_workbook(fn)

            self.log("Generate rows for: "+fn)

            self.workbook = wb

            s = wb.sheets()[sheet_num]

            for i in range(1,s.nrows):

                if as_dict:
                    yield dict(zip(header, [None] + self.srow_to_list(i, s)))
                else:
                    # It might seem inefficient to return the header every time, but it really adds only a
                    # fraction of a section for millions of rows.
                    yield header, [None] + self.srow_to_list(i, s)


class GeoBuildBundle(LoaderBundle):
    """A Bundle variant that loads zipped Shapefiles"""
    def __init__(self, bundle_dir=None):
        '''
        '''

        super(GeoBuildBundle, self).__init__(bundle_dir)


    def meta(self):
        from ambry.geo.sfschema import copy_schema

        self.database.create()

        self._prepare_load_schema()

        def log(x):
            self.log(x)

        for table, item in self.metadata.sources.items():

            with self.session:
                copy_schema(self.schema, table_name=table, path=item.url, logger=log)

        self.schema.write_schema()

        return True


    def build(self):

        for table, item in self.metadata.sources.items():
            self.log("Loading table {} from {}".format(table, item.url))

            # Set the source SRS, if it was not set in the input file
            if self.metadata.build.get('s_srs', False):
                s_srs = self.metadata.build.s_srs
            else:
                s_srs = None

            lr = self.init_log_rate(print_rate=10)

            p = self.partitions.new_geo_partition(table=table, shape_file=item.url, s_srs=s_srs, logger=lr)
            self.log("Loading table {}. Done".format(table))

        for p in self.partitions:
            print p.info

        return True