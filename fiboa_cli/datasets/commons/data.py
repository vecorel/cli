from csv import DictReader
from os.path import dirname, join


def read_data_csv(name, **kwargs):
    return list(DictReader(open(join(dirname(dirname(__file__)), "data-files", name), 'r'), **kwargs))
