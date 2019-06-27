#!/usr/bin/python3

import argparse
import logging
import subprocess
import os
from collections import defaultdict
from sys import exit, stdout
from signal import signal, SIGINT, SIGTERM
import threading
import time
import importlib
import importlib.util
import inspect


logger = logging.getLogger()


class FuncNameFilter(logging.Filter):
    def __init__(self, func_name):
        self.func_names = set()
        self.add_func_name(func_name)
        super().__init__()

    def add_func_name(self, func_name):
        self.func_names.add(func_name)

    def filter(self, record):
        # True will propagate the record, False will filter out the record
        return record.funcName in self.func_names


def main():
    _init_logger()
    signal(SIGINT, __sigterm_handler)
    signal(SIGTERM, __sigterm_handler)

    parser = argparse.ArgumentParser()
    parser.add_argument('--verbose',
                        dest='verbose',
                        metavar='namespace',
                        nargs='*',
                        help='Sets the logging level to INFO. '
                             'It\'s a shortcut for "--set-logging-level INFO". See also there for details.')
    parser.add_argument('--debug',
                        dest='debug',
                        metavar='namespace',
                        nargs='*',
                        help='Sets the logging level to DEBUG. '
                             'It\'s a shortcut for "--set-logging-level DEBUG". See also there for details.')
    parser.add_argument('--set_logging_level',
                        dest='set_logging_level',
                        metavar='<LEVEL> [namespace,[namespace,...]]',
                        nargs='+',
                        help='Sets the logging level to <LEVEL> which can be chosen from [CRITICAL, ERROR, WARNING, '
                             'INFO, DEBUG, NOTSET]. If namespaces are given behind a <LEVEL> only these specific '
                             'modules or packages are affective with this <LEVEL>. '
                             'A namespace represents a dotted module hierarchy like "<a>.<b>.<c>" whereat the last '
                             'part <c> could be either the bottom-module of the hierarchy or the function <c> within '
                             'the module <b>. '
                             'Multiple sets are possible as "<LEVEL> [namespace,...] <LEVEL> [namespace,...]". '
                             'Namespace notations like "<a>.[<b>,<c>.[<d>,<e>]]" will be resolved to "<a.b> <a.c.d> '
                             '<a.c.e>".')
    args = parser.parse_args()

    if args.verbose is not None:
        _apply_logging_level(logging.INFO, args.verbose)
    if args.debug is not None:
        _apply_logging_level(logging.DEBUG, args.debug)
    if args.set_logging_level is not None:
        logging_level_name = args.set_logging_level[0]
        if not logging_level_name.isupper():
            raise ValueError(f'<LEVEL>="{logging_level_name}" needs to be a upper case string!')
        logging_level = logging.getLevelName(logging_level_name)  # also recovers the LevelNumber for a given LevelName

        namespaces_by_level = defaultdict(list)
        namespaces_by_level[logging_level] = []  # in case no optional namespaces are given
        for arg in args.set_logging_level[1:]:
            if arg.isupper():
                logging_level = logging.getLevelName(arg)  # also recovers the LevelNumber for a given LevelName
            else:
                namespaces_by_level[logging_level].append(arg)
        for lvl, namespaces in namespaces_by_level.items():
            _apply_logging_level(lvl, namespaces)


def _init_logger():
    sh = logging.StreamHandler(stdout)

    class FrameNumberFormatter(logging.Formatter):
        def format(self, record):
            global event_distributor
            if event_distributor is not None:
                return f'{event_distributor.frame_number}. {super().format(record)}'
            else:
                return super().format(record)
    sh.setFormatter(FrameNumberFormatter('%(levelname)s, %(module)s@%(lineno)d - %(funcName)s(), %(asctime)s:\n'
                                         '  %(message)s'))
    logger.addHandler(sh)
    logger.setLevel(logging.WARNING)


def _apply_logging_level(logging_level, namespaces=None):
    logging_level_name = logging.getLevelName(logging_level)
    if not namespaces:
        print(f'{logging_level_name} logging level is set.')
        logger.setLevel(logging_level)
    else:
        print(f'{logging_level_name} logging level is set for:')
        indent = '  '

        if not type(namespaces) in (list, tuple):
            namespaces = [namespaces]
        root_module_name = 'capore_tuio_server'
        for namespace in namespaces:
            resolved_namespaces = _resolve_bracketed_logging_namespace(namespace)
            if resolved_namespaces != namespace:
                namespaces.extend(resolved_namespaces)
                continue

            namespace = root_module_name + '.' + namespace

            module_obj = None
            module_name = None
            function_name = None
            try:
                module_obj = importlib.import_module(namespace)
            except ModuleNotFoundError:  # check if ending is a function within namespace
                module_name, function_name = namespace.rsplit('.', maxsplit=1)
                try:
                    module_obj = importlib.import_module(module_name)
                except ModuleNotFoundError:
                    function_name = None
                namespace = module_name

            if not module_obj:
                print(f'{indent}! MODULE NOT FOUND "{namespace}"')
                continue

            # check if function_name exists
            if function_name:
                all_classes_within_module = []
                for _, value in inspect.getmembers(module_obj):
                    if inspect.isclass(value) and value.__module__ == module_name:
                        all_classes_within_module.append(value)
                if not all_classes_within_module:
                    raise ValueError(f'"{module_name}" has no classes!')

                for cls in all_classes_within_module:
                    try:
                        function_obj = getattr(cls, function_name)
                        is_existing = False
                        if inspect.isfunction(function_obj):
                            is_existing = True
                        elif isinstance(function_obj, property):
                            is_existing = True
                            f_get = function_obj.fget
                            f_set = function_obj.fset
                            if f_get is not None:
                                function_name = f_get.__name__
                            elif f_set is not None:
                                function_name = f_set.__name__
                            else:
                                is_existing = False
                        if not is_existing:
                            raise ValueError(f'"{function_name}" should be a function within "{namespace}!"')
                        break
                    except AttributeError:
                        continue
                else:
                    raise ValueError(f'Can\'t find "{function_name}" within "{namespace}"!')

            child_logger = logger.getChild(namespace)
            prev_level = child_logger.getEffectiveLevel()
            child_logger.setLevel(logging_level)

            if prev_level == logging.WARNING:
                print(f'{indent}{namespace}')
            elif prev_level != logging_level:
                print(f'{indent}{namespace} '
                      f'(overrides previous level {logging.getLevelName(prev_level)})')

            if function_name:
                existing_filters = child_logger.filters
                if not existing_filters:
                    child_logger.addFilter(FuncNameFilter(function_name))
                    print(f'{2*indent}|  (filtering following function(s):)')
                else:
                    existing_filters[0].add_func_name(function_name)
                print(f'{2*indent}|- {function_name}')


def _resolve_bracketed_logging_namespace(namespace):
    # namespaces like "<a>.[<b>,<c>.[<d>,<e>]]" will resolved to ["<a.b>", "<a.c.d>", "<a.c.e>"]
    if '[' not in namespace:
        return namespace

    prefix, suffix = namespace.split('[', maxsplit=1)
    if not prefix.endswith('.'):
        raise ValueError(f'"{namespace}" looks like a bracketed namespace declaration but '
                         f'the package separator "." between "{prefix}" and "[{suffix}" is missing!')
    if not suffix.endswith(']'):
        raise ValueError(f'"{namespace}" looks like a bracketed namespace declaration but '
                         f'the trailing "]" after "{prefix}[{suffix}" is missing!')
    suffix = suffix[:-1]
    result = []
    while suffix:
        idx = suffix.find(',')
        if idx == -1:
            idx = len(suffix)
        a = suffix[:idx]
        b = suffix[idx+1:]
        if '[' in a:
            idx = suffix.rfind(']')
            if idx == -1:
                idx = len(suffix)
            c = suffix[:idx+1]
            d = suffix[idx+1:]
            for n in _resolve_bracketed_logging_namespace(c):
                result.append(prefix + n)
            if d and d[0] not in [',', ']']:
                raise ValueError(f'"{namespace}" looks like a bracketed namespace declaration but '
                                 f'there is a syntax problem between "{namespace[0:namespace.find(d)]}" and "{d}"!')
            suffix = d[1:]
        else:
            result.append(prefix + a)
            suffix = b
    return result
