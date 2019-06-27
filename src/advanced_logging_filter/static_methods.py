import io
import logging
import sys


formatter = logging.Formatter(fmt='[%(levelname)-8s][%(asctime)s.%(msecs)03d] %(message)s [%(module)s.%(funcName)s@%(lineno)d]', datefmt='%H:%M:%S')


def set_verbose_formatter(logger):
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    logger.addHandler(handler)


def print_to_logger(func):
    def wrapped_func(*args, **kwargs):
        logger = logging.getLogger()

        def my_print(*args, **kwargs):
            file = kwargs.pop('file', None)
            if file is None or file is sys.stdout:
                log_function = logger.info
            elif file is sys.stderr:
                log_function = logger.error
            else:
                log_function = file
            output = io.StringIO()
            __builtins__.print(*args, file=output, end='', **kwargs)
            log_function(output.getvalue())

        global print
        old_print = print
        print = my_print
        func(*args, **kwargs)
        print = old_print  # print = __builtins__.print
    wrapped_func.__name__ = func.__name__
    wrapped_func.__qualname__ = func.__qualname__
    return wrapped_func
