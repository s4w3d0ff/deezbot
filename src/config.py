import yaml

DEFAULT_WRITE_TABLES = ('joke', 'ignore', 'channels')


def loadYAML(filename):
    with open(filename) as f:
        return yaml.safe_load(f) or {}
