import argparse
import json
import os
import sys
import time
from collections import defaultdict
from collections.abc import Sequence

try:
    from configparser import NoSectionError
except ImportError:  # python 2
    from ConfigParser import NoSectionError

try:
    import pygments
    from pygments.lexers import JsonLexer, XmlLexer
    from pygments.styles import get_style_by_name
    from pygments.formatters import Terminal256Formatter
except ImportError:
    pygments = None

from .client import read_config, CloudStack, CloudStackException  # noqa


__all__ = ['read_config', 'CloudStack', 'CloudStackException']

if sys.version_info >= (3, 5):
    try:
        import aiohttp  # noqa
    except ImportError:
        pass
    else:
        from ._async import AIOCloudStack  # noqa
        __all__.append('AIOCloudStack')

if sys.version_info >= (3, 6):
    try:
        import lxml.etree
    except ImportError:
        pass


def _format_json(data, theme):
    """Pretty print a dict as a JSON, with colors if pygments is present."""
    output = json.dumps(data, indent=2, sort_keys=True)

    if pygments and sys.stdout.isatty():
        style = get_style_by_name(theme)
        formatter = Terminal256Formatter(style=style)
        return pygments.highlight(output, JsonLexer(), formatter)

    return output


def _format_xml(data):
    """Pretty print the XML struct, with colors if pygments is present."""
    if isinstance(data, Sequence):
        output = []
        for elem in data:
            output.append(_format_xml(elem))
        return ''.join(output)

    output = lxml.etree.tostring(data.lxml, encoding=data.encoding,
                                 pretty_print=True)

    if pygments and sys.stdout.isatty():
        return pygments.highlight(output, XmlLexer(), TerminalFormatter())

    return output


def _parser():
    """Build the argument parser"""
    parser = argparse.ArgumentParser(description='Cloustack client.')
    parser.add_argument('--region', metavar='REGION',
                        help='Cloudstack region in ~/.cloudstack.ini',
                        default=os.environ.get('CLOUDSTACK_REGION',
                                               'cloudstack'))
    parser.add_argument('--theme', metavar='THEME',
                        help='Pygments style',
                        default=os.environ.get('CLOUDSTACK_THEME',
                                               'default'))
    parser.add_argument('--post', action='store_true', default=False,
                        help='use POST instead of GET')
    parser.add_argument('--async', action='store_true', default=False,
                        help='do not wait for async result')
    parser.add_argument('--quiet', '-q', action='store_true', default=False,
                        help='do not display additional status messages')
    parser.add_argument('command', metavar="COMMAND",
                        help='Cloudstack API command to execute')

    def parse_option(x):
        if '=' not in x:
            raise ValueError("{!r} is not a correctly formatted "
                             "option".format(x))
        return x.split('=', 1)

    parser.add_argument('arguments', metavar="OPTION=VALUE",
                        nargs='*', type=parse_option,
                        help='Cloudstack API argument')

    return parser


def mainx():
    """Just like main, but better"""
    parser = _parser()

    parser.add_argument('--xpath', metavar='XPATH',
                        help='XPath query into the result')

    options = parser.parse_args()
    command = options.command
    kwargs = defaultdict(set)
    for arg in options.arguments:
        key, value = arg
        kwargs[key].add(value.strip(" \"'"))

    try:
        config = read_config(ini_group=options.region)
    except NoSectionError:
        raise SystemExit("Error: region '%s' not in config" % options.region)

    if options.post:
        config['method'] = 'post'
    config['response'] = 'xml'

    cs = CloudStack(**config)
    ok = True
    try:
        response = getattr(cs, command)(**kwargs)
    except CloudStackException as e:
        response = e.args[1]
        if not options.quiet:
            sys.stderr.write("Cloudstack error: HTTP response "
                             "{0}\n".format(response.status_code))

        sys.stderr.write(response.text)
        sys.stderr.write("\n")
        sys.exit(1)

    if options.xpath:
        response = response.xpath(options.xpath)

    sys.stdout.write(_format_xml(response))
    sys.exit(not ok)


def main():
    parser = _parser()
    options = parser.parse_args()
    command = options.command
    kwargs = defaultdict(set)
    for arg in options.arguments:
        key, value = arg
        kwargs[key].add(value.strip(" \"'"))

    try:
        config = read_config(ini_group=options.region)
    except NoSectionError:
        raise SystemExit("Error: region '%s' not in config" % options.region)

    theme = config.pop('theme', 'default')

    if options.post:
        config['method'] = 'post'
    cs = CloudStack(**config)
    ok = True
    try:
        response = getattr(cs, command)(**kwargs)
    except CloudStackException as e:
        response = e.args[1]
        if not options.quiet:
            sys.stderr.write("Cloudstack error: HTTP response "
                             "{0}\n".format(response.status_code))

        try:
            response = json.loads(response.text)
        except ValueError:
            sys.stderr.write(response.text)
            sys.stderr.write("\n")
            sys.exit(1)

    if 'Async' not in command and 'jobid' in response and not getattr(
            options, 'async'):
        if not options.quiet:
            sys.stderr.write("Polling result... ^C to abort\n")
        while True:
            try:
                res = cs.queryAsyncJobResult(**response)
                if res['jobstatus'] != 0:
                    response = res
                    if res['jobresultcode'] != 0:
                        ok = False
                    break
                time.sleep(3)
            except KeyboardInterrupt:
                if not options.quiet:
                    sys.stderr.write("Result not ready yet.\n")
                break

    sys.stdout.write(_format_json(response, theme=theme))
    sys.stdout.write('\n')
    sys.exit(not ok)
