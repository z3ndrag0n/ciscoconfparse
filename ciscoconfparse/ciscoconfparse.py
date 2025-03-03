from __future__ import absolute_import
from operator import methodcaller, attrgetter
from colorama import Fore, Back, Style
from difflib import SequenceMatcher
import logging
import inspect
import json
import time
import copy
import sys
import re
import os

if sys.version_info >= (
    3,
    0,
    0,
):
    from collections.abc import MutableSequence, Iterator
else:
    ## This syntax is not supported in Python 3...
    from collections import MutableSequence, Iterator


from ciscoconfparse.models_cisco import IOSHostnameLine, IOSRouteLine
from ciscoconfparse.models_cisco import IOSIntfLine
from ciscoconfparse.models_cisco import IOSAccessLine, IOSIntfGlobal
from ciscoconfparse.models_cisco import IOSAaaLoginAuthenticationLine
from ciscoconfparse.models_cisco import IOSAaaEnableAuthenticationLine
from ciscoconfparse.models_cisco import IOSAaaCommandsAuthorizationLine
from ciscoconfparse.models_cisco import IOSAaaCommandsAccountingLine
from ciscoconfparse.models_cisco import IOSAaaExecAccountingLine
from ciscoconfparse.models_cisco import IOSAaaGroupServerLine
from ciscoconfparse.models_cisco import IOSCfgLine

from ciscoconfparse.models_nxos import NXOSHostnameLine, NXOSRouteLine, NXOSIntfLine
from ciscoconfparse.models_nxos import NXOSAccessLine, NXOSIntfGlobal
from ciscoconfparse.models_nxos import NXOSAaaLoginAuthenticationLine
from ciscoconfparse.models_nxos import NXOSAaaEnableAuthenticationLine
from ciscoconfparse.models_nxos import NXOSAaaCommandsAuthorizationLine
from ciscoconfparse.models_nxos import NXOSAaaCommandsAccountingLine
from ciscoconfparse.models_nxos import NXOSAaaExecAccountingLine
from ciscoconfparse.models_nxos import NXOSAaaGroupServerLine
from ciscoconfparse.models_nxos import NXOSvPCLine
from ciscoconfparse.models_nxos import NXOSCfgLine

from ciscoconfparse.models_asa import ASAObjGroupNetwork
from ciscoconfparse.models_asa import ASAObjGroupService
from ciscoconfparse.models_asa import ASAHostnameLine
from ciscoconfparse.models_asa import ASAObjNetwork
from ciscoconfparse.models_asa import ASAObjService
from ciscoconfparse.models_asa import ASAIntfGlobal
from ciscoconfparse.models_asa import ASAIntfLine
from ciscoconfparse.models_asa import ASACfgLine
from ciscoconfparse.models_asa import ASAName
from ciscoconfparse.models_asa import ASAAclLine

from ciscoconfparse.models_junos import JunosCfgLine

from ciscoconfparse.ccp_util import junos_unsupported, UnsupportedFeatureWarning

from loguru import logger


r""" ciscoconfparse.py - Parse, Query, Build, and Modify IOS-style configs

     Copyright (C) 2020-2021 Cisco Systems and David Michael Pennington
     Copyright (C) 2019      ThousandEyes and David Michael Pennington
     Copyright (C) 2012-2019 Samsung Data Services and David Michael Pennington
     Copyright (C) 2011-2012 Dell Computer Corp and David Michael Pennington
     Copyright (C) 2007-2011 David Michael Pennington

     This program is free software: you can redistribute it and/or modify
     it under the terms of the GNU General Public License as published by
     the Free Software Foundation, either version 3 of the License, or
     (at your option) any later version.

     This program is distributed in the hope that it will be useful,
     but WITHOUT ANY WARRANTY; without even the implied warranty of
     MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
     GNU General Public License for more details.

     You should have received a copy of the GNU General Public License
     along with this program.  If not, see <http://www.gnu.org/licenses/>.

     If you need to contact the author, you can do so by emailing:
     mike [~at~] pennington [/dot\] net
"""


## Docstring props: http://stackoverflow.com/a/1523456/667301
# __version__ if-else below fixes Github issue #123
metadata_json_path = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "metadata.json"
)
if os.path.isfile(metadata_json_path):
    ## Retrieve the version number from json...
    with open(metadata_json_path) as mh:
        metadata_dict = json.load(mh)
        __author__ = metadata_dict.get("author")
        __author_email__ = metadata_dict.get("author_email")
        __version__ = metadata_dict.get("version")
else:
    # This case is required for importing from a zipfile... Github issue #123
    __version__ = "0.0.0"  # __version__ read failed
__author_email__ = r"mike /at\ pennington [dot] net"
__author__ = "David Michael Pennington <{0}>".format(__author_email__)
__copyright__ = "2007-{0}, {1}".format(time.strftime("%Y"), __author__)
__license__ = "GPLv3"
__status__ = "Production"


logger.remove()
# Send logs to sys.stderr by default
logger.add(
    sink=sys.stderr,
    colorize=True,
    diagnose=True,
    backtrace=True,
    enqueue=True,
    serialize=False,
    catch=True,
    level="DEBUG",
    #format='<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>'
)

class CiscoConfParse(object):
    """Parses Cisco IOS configurations and answers queries about the configs."""

    def __init__(
        self,
        config="",
        comment="!",
        debug=0,
        factory=False,
        linesplit_rgx=r"\r*\n+",
        ignore_blank_lines=True,
        syntax="ios",
    ):
        """
        Initialize CiscoConfParse.

        Parameters
        ----------
        config : list or str
            A list of configuration statements, or a configuration file path to be parsed
        comment : str
            A comment delimiter.  This should only be changed when parsing non-Cisco IOS configurations, which do not use a !  as the comment delimiter.  ``comment`` defaults to '!'.  This value can hold multiple characters in case the config uses multiple characters for comment delimiters; however, the comment delimiters are always assumed to be one character wide
        debug : int
            ``debug`` defaults to 0, and should be kept that way unless you're working on a very tricky config parsing problem.  Debug range goes from 0 (no debugging) to 5 (max debugging).  Debug output is not particularly friendly.
        factory : bool
            ``factory`` defaults to False; if set ``True``, it enables a beta-quality configuration line classifier.
        linesplit_rgx : str
            ``linesplit_rgx`` is used when parsing configuration files to find where new configuration lines are.  It is best to leave this as the default, unless you're working on a system that uses unusual line terminations (for instance something besides Unix, OSX, or Windows)
        ignore_blank_lines : bool
            ``ignore_blank_lines`` defaults to True; when this is set True, ciscoconfparse ignores blank configuration lines.  You might want to set ``ignore_blank_lines`` to False if you intentionally use blank lines in your configuration (ref: Github Issue #2), or you are parsing configurations which naturally have blank lines (such as Cisco Nexus configurations).
        syntax : str
            A string holding the configuration type.  Default: 'ios'.  Must be one of: 'ios', 'nxos', 'asa', 'junos'.  Use 'junos' for any brace-delimited configuration (including F5, Palo Alto, etc...).

        Returns
        -------
        :class:`~ciscoconfparse.CiscoConfParse`

        Examples
        --------
        This example illustrates how to parse a simple Cisco IOS configuration
        with :class:`~ciscoconfparse.CiscoConfParse` into a variable called
        ``parse``.  This example also illustrates what the ``ConfigObjs``
        and ``ioscfg`` attributes contain.

        >>> from ciscoconfparse import CiscoConfParse
        >>> config = [
        ...     'logging trap debugging',
        ...     'logging 172.28.26.15',
        ...     ]
        >>> parse = CiscoConfParse(config)
        >>> parse
        <CiscoConfParse: 2 lines / syntax: ios / comment delimiter: '!' / factory: False>
        >>> parse.ConfigObjs
        <IOSConfigList, comment='!', conf=[<IOSCfgLine # 0 'logging trap debugging'>, <IOSCfgLine # 1 'logging 172.28.26.15'>]>
        >>> parse.ioscfg
        ['logging trap debugging', 'logging 172.28.26.15']
        >>>

        Attributes
        ----------
        comment_delimiter : str
            A string containing the comment-delimiter.  Default: "!"
        ConfigObjs : :class:`~ciscoconfparse.IOSConfigList`
            A custom list, which contains all parsed :class:`~models_cisco.IOSCfgLine` instances.
        debug : int
            An int to enable verbose config parsing debugs. Default 0.
        ioscfg : list
            A list of text configuration strings
        objs
            An alias for `ConfigObjs`
        openargs : dict
            Returns a dictionary of valid arguments for `open()` (these change based on the running python version).
        syntax : str
            A string holding the configuration type.  Default: 'ios'.  Must be one of: 'ios', 'nxos', 'asa', 'junos'.  Use 'junos' for any brace-delimited configuration (including F5, Palo Alto, etc...).


        """

        # all IOSCfgLine object instances...
        self.comment_delimiter = comment
        self.factory = factory
        self.ConfigObjs = None
        self.syntax = syntax
        self.debug = debug

        if isinstance(config, list) or isinstance(config, Iterator):
            if syntax == "ios":
                # we already have a list object, simply call the parser
                if self.debug > 0:
                    logger.debug("parsing from a python list with ios syntax")
                self.ConfigObjs = IOSConfigList(
                    data=config,
                    comment_delimiter=comment,
                    debug=debug,
                    factory=factory,
                    ignore_blank_lines=ignore_blank_lines,
                    syntax="ios",
                    CiscoConfParse=self,
                )
            elif syntax == "nxos":
                # we already have a list object, simply call the parser
                if self.debug > 0:
                    logger.debug("parsing from a python list with nxos syntax")
                self.ConfigObjs = NXOSConfigList(
                    data=config,
                    comment_delimiter=comment,
                    debug=debug,
                    factory=factory,
                    ignore_blank_lines=False,  # NXOS always has blank lines
                    syntax="nxos",
                    CiscoConfParse=self,
                )
            elif syntax == "asa":
                # we already have a list object, simply call the parser
                if self.debug > 0:
                    logger.debug("parsing from a python list with asa syntax")
                self.ConfigObjs = ASAConfigList(
                    data=config,
                    comment_delimiter=comment,
                    debug=debug,
                    factory=factory,
                    ignore_blank_lines=ignore_blank_lines,
                    syntax="asa",
                    CiscoConfParse=self,
                )
            elif syntax == "junos":
                ## FIXME I am shamelessly abusing the IOSConfigList for now...
                # we already have a list object, simply call the parser
                error = "junos parser factory is not yet enabled; use factory=False"
                assert factory is False, error
                config = self.convert_braces_to_ios(config)
                if self.debug > 0:
                    logger.debug("parsing from a python list with junos syntax")
                self.ConfigObjs = IOSConfigList(
                    data=config,
                    comment_delimiter=comment,
                    debug=debug,
                    factory=factory,
                    ignore_blank_lines=ignore_blank_lines,
                    syntax="junos",
                    CiscoConfParse=self,
                )
            else:
                error = "'{}' is an unknown syntax".format(syntax)
                logger.critical(error)
                raise ValueError(error)

        ## Accept either a string, unicode, or a pathlib.Path instance...
        elif getattr(config, "encode", False) or getattr(config, "is_file"):
            # Try opening as a file
            try:
                if syntax == "ios":
                    # string - assume a filename... open file, split and parse
                    if self.debug > 0:
                        logger.debug(
                            "parsing from '{0}' with ios syntax".format(config)
                        )
                    with open(config, **self.openargs) as fh:
                        text = fh.read()
                    rgx = re.compile(linesplit_rgx)
                    self.ConfigObjs = IOSConfigList(
                        rgx.split(text),
                        comment_delimiter=comment,
                        debug=debug,
                        factory=factory,
                        ignore_blank_lines=ignore_blank_lines,
                        syntax="ios",
                        CiscoConfParse=self,
                    )
                elif syntax == "nxos":
                    # string - assume a filename... open file, split and parse
                    if self.debug > 0:
                        logger.debug(
                            "parsing from '{0}' with nxos syntax".format(config)
                        )
                    with open(config, **self.openargs) as fh:
                        text = fh.read()
                    rgx = re.compile(linesplit_rgx)
                    self.ConfigObjs = NXOSConfigList(
                        rgx.split(text),
                        comment_delimiter=comment,
                        debug=debug,
                        factory=factory,
                        ignore_blank_lines=False,
                        syntax="nxos",
                        CiscoConfParse=self,
                    )
                elif syntax == "asa":
                    # string - assume a filename... open file, split and parse
                    if self.debug > 0:
                        logger.debug(
                            "parsing from '{0}' with asa syntax".format(config)
                        )
                    with open(config, **self.openargs) as fh:
                        text = fh.read()
                    rgx = re.compile(linesplit_rgx)
                    self.ConfigObjs = ASAConfigList(
                        rgx.split(text),
                        comment_delimiter=comment,
                        debug=debug,
                        factory=factory,
                        ignore_blank_lines=ignore_blank_lines,
                        syntax="asa",
                        CiscoConfParse=self,
                    )

                elif syntax == "junos":
                    # string - assume a filename... open file, split and parse
                    if self.debug > 0:
                        logger.debug(
                            "parsing from '{0}' with junos syntax".format(config)
                        )
                    with open(config, **self.openargs) as fh:
                        text = fh.read()
                    rgx = re.compile(linesplit_rgx)

                    config = self.convert_braces_to_ios(rgx.split(text))
                    ## FIXME I am shamelessly abusing the IOSConfigList for now...
                    self.ConfigObjs = IOSConfigList(
                        config,
                        comment_delimiter=comment,
                        debug=debug,
                        factory=factory,
                        ignore_blank_lines=ignore_blank_lines,
                        syntax="junos",
                        CiscoConfParse=self,
                    )
                else:
                    error = "'{}' is an unknown syntax".format(syntax)
                    logger.critical(error)
                    raise ValueError(error)

            except (IOError or FileNotFoundError):
                error = "CiscoConfParse could not open() the filepath '%s'" % config
                logger.critical(error)
                raise RuntimeError
        else:
            error = "CiscoConfParse() received an invalid argument\n"
            logger.critical(error)
            raise RuntimeError(error)

        self.ConfigObjs.CiscoConfParse = self

    def __repr__(self):
        return (
            "<CiscoConfParse: %s lines / syntax: %s / comment delimiter: '%s' / factory: %s>"
            % (len(self.ConfigObjs), self.syntax, self.comment_delimiter, self.factory)
        )

    @property
    def openargs(self):
        """Fix for Py3.5 deprecation of universal newlines - Ref Github #114
        also see https://softwareengineering.stackexchange.com/q/298677/23144
        """
        if sys.version_info >= (
            3,
            5,
            0,
        ):
            retval = {"mode": "r", "newline": None}
        else:
            retval = {"mode": "rU"}
        return retval

    @property
    def ioscfg(self):
        """A list containing all text configuration statements"""
        ## I keep this here to emulate the legacy ciscoconfparse behavior
        return list(map(attrgetter("text"), self.ConfigObjs))

    @property
    def objs(self):
        """An alias to the ``ConfigObjs`` attribute"""
        return self.ConfigObjs

    def atomic(self):
        """Call :func:`~ciscoconfparse.CiscoConfParse.atomic` to manually fix
        up ``ConfigObjs`` relationships
        after modifying a parsed configuration.  This method is slow; try to
        batch calls to :func:`~ciscoconfparse.CiscoConfParse.atomic()` if
        possible.

        Warnings
        --------
        If you modify a configuration after parsing it with
        :class:`~ciscoconfparse.CiscoConfParse`, you *must* call
        :func:`~ciscoconfparse.CiscoConfParse.commit` or
        :func:`~ciscoconfparse.CiscoConfParse.atomic` before searching
        the configuration again with methods such as
        :func:`~ciscoconfparse.CiscoConfParse.find_objects` or
        :func:`~ciscoconfparse.CiscoConfParse.find_lines`.  Failure to
        call :func:`~ciscoconfparse.CiscoConfParse.commit` or
        :func:`~ciscoconfparse.CiscoConfParse.atomic` on config
        modifications could lead to unexpected search results.

        See Also
        --------
        :func:`~ciscoconfparse.CiscoConfParse.commit`

        """
        self.ConfigObjs._bootstrap_from_text()

    def commit(self):
        """Alias for calling the :func:`~ciscoconfparse.CiscoConfParse.atomic`
        method.  This method is slow; try to batch calls to
        :func:`~ciscoconfparse.CiscoConfParse.commit()` if possible.

        Warnings
        --------
        If you modify a configuration after parsing it with
        :class:`~ciscoconfparse.CiscoConfParse`, you *must* call
        :func:`~ciscoconfparse.CiscoConfParse.commit` or
        :func:`~ciscoconfparse.CiscoConfParse.atomic` before searching
        the configuration again with methods such as
        :func:`~ciscoconfparse.CiscoConfParse.find_objects` or
        :func:`~ciscoconfparse.CiscoConfParse.find_lines`.  Failure to
        call :func:`~ciscoconfparse.CiscoConfParse.commit` or
        :func:`~ciscoconfparse.CiscoConfParse.atomic` on config
        modifications could lead to unexpected search results.

        See Also
        --------
        :func:`~ciscoconfparse.CiscoConfParse.atomic`
        """
        self.atomic()

    def convert_braces_to_ios(self, input_list, stop_width=4):
        """
        Parameters
        ----------
        input_list : list
            A list of plain-text brace-delimited configuration lines
        stop_width: int
            An integer used to mark how many spaces each config level is indented.

        Returns
        -------
        list
            An ios-style configuration list (indented by stop_width for each configuration level).
        """
        ## Note to self, I made this regex fairly junos-specific...
        assert "{" not in set(self.comment_delimiter)
        assert "}" not in set(self.comment_delimiter)

        JUNOS_RE_STR = r"""^
        (?:\s*
            (?P<braces_close_left>\})*(?P<line1>.*?)(?P<braces_open_right>\{)*;*
           |(?P<line2>[^\{\}]*?)(?P<braces_open_left>\{)(?P<condition2>.*?)(?P<braces_close_right>\});*\s*
           |(?P<line3>[^\{\}]*?);*\s*
        )$
        """
        LINE_RE = re.compile(JUNOS_RE_STR, re.VERBOSE)

        COMMENT_RE = re.compile(
            r"^\s*(?P<delimiter>[{0}]+)(?P<comment>[^{0}]*)$".format(
                re.escape(self.comment_delimiter)
            )
        )

        def parse_line_braces(input_str):
            assert input_str is not None
            indent_child = 0
            indent_this_line = 0

            mm = LINE_RE.search(input_str.strip())
            nn = COMMENT_RE.search(input_str.strip())

            if nn is not None:
                results = nn.groupdict()
                return (
                    indent_this_line,
                    indent_child,
                    results.get("delimiter") + results.get("comment", ""),
                )

            elif mm is not None:
                results = mm.groupdict()

                # } line1 { foo bar this } {
                braces_close_left = bool(results.get("braces_close_left", ""))
                braces_open_right = bool(results.get("braces_open_right", ""))

                # line2
                braces_open_left = bool(results.get("braces_open_left", ""))
                braces_close_right = bool(results.get("braces_close_right", ""))

                # line3
                line1_str = results.get("line1", "")
                line3_str = results.get("line3", "")

                if braces_close_left and braces_open_right:
                    # Based off line1
                    #     } elseif { bar baz } {
                    indent_this_line -= 1
                    indent_child += 0
                    retval = results.get("line1", None)
                    return (indent_this_line, indent_child, retval)

                elif (
                    bool(line1_str)
                    and (braces_close_left is False)
                    and (braces_open_right is False)
                ):
                    # Based off line1:
                    #     address 1.1.1.1
                    indent_this_line -= 0
                    indent_child += 0
                    retval = results.get("line1", "").strip()
                    # Strip empty braces here
                    retval = re.sub(r"\s*\{\s*\}\s*", "", retval)
                    return (indent_this_line, indent_child, retval)

                elif (
                    (line1_str == "")
                    and (braces_close_left is False)
                    and (braces_open_right is False)
                ):
                    # Based off line1:
                    #     return empty string
                    indent_this_line -= 0
                    indent_child += 0
                    return (indent_this_line, indent_child, "")

                elif braces_open_left and braces_close_right:
                    # Based off line2
                    #    this { bar baz }
                    indent_this_line -= 0
                    indent_child += 0
                    line = results.get("line2", None) or ""
                    condition = results.get("condition2", None) or ""
                    if condition.strip() == "":
                        retval = line
                    else:
                        retval = line + " {" + condition + " }"
                    return (indent_this_line, indent_child, retval)

                elif braces_close_left:
                    # Based off line1
                    #   }
                    indent_this_line -= 1
                    indent_child -= 1
                    return (indent_this_line, indent_child, "")

                elif braces_open_right:
                    # Based off line1
                    #   this that foo {
                    indent_this_line -= 0
                    indent_child += 1
                    line = results.get("line1", None) or ""
                    return (indent_this_line, indent_child, line)

                elif (line3_str != "") and (line3_str is not None):
                    indent_this_line += 0
                    indent_child += 0
                    return (indent_this_line, indent_child, "")

                else:
                    error = 'Cannot parse junos match:"{0}"'.format(input_str)
                    logger.critical(error)
                    raise ValueError(error)

            else:
                error = 'Cannot parse junos:"{0}"'.format(input_str)
                logger.critical(error)
                raise ValueError(error)

        lines = list()
        offset = 0
        STOP_WIDTH = stop_width
        for idx, tmp in enumerate(input_list):
            if self.debug > 0:
                logger.debug("Parse line {0}:'{1}'".format(idx + 1, tmp.strip()))
            (indent_this_line, indent_child, line) = parse_line_braces(tmp.strip())
            lines.append(
                (" " * STOP_WIDTH * (offset + indent_this_line)) + line.strip()
            )
            offset += indent_child
        return lines

    def find_object_branches(self, branchspec=(), regex_flags=0, allow_none=True):
        r"""This method iterates over a tuple of regular expressions in `branchspec` and returns the matching objects in a list of lists (consider it similar to a table of matching config objects). `branchspec` expects to start at some ancestor and walk through the nested object hierarchy (with no limit on depth).

        Previous CiscoConfParse() methods only handled a single parent regex and single child regex (such as :func:`~ciscoconfparse.CiscoConfParse.find_parents_w_child`).

        This method dives beyond a simple parent-child relationship to include entire family 'branches' (i.e. parents, children, grand-children, great-grand-children, etc).  The result of handling longer regex chains is that it flattens what would otherwise be nested loops in your scripts; this makes parsing heavily-nested configuratations like Palo-Alto and F5 much simpler.  Of course, there are plenty of applications for "flatter" config formats like IOS.

        This method returns a list of lists (of object 'branches') which are nested to the same depth required in `branchspec`.  However, unlike most other CiscoConfParse() methods, it returns an explicit `None` if there is no object match.  Returning `None` allows a single search over configs that may not be uniformly nested in every branch.

        Parameters
        ----------
        branchspec : tuple
            A tuple of python regular expressions to be matched.
        regex_flags :
            Chained regular expression flags, such as `re.IGNORECASE|re.MULTILINE`
        allow_none :
            Set False if you don't want an explicit `None` for missing branch elements (default is allow_none=True)

        Returns
        -------
        list
            A list of lists of matching :class:`~ciscoconfparse.IOSCfgLine` objects

        Examples
        --------

        >>> from operator import attrgetter
        >>> from ciscoconfparse import CiscoConfParse
        >>> config = [
        ...     'ltm pool FOO {',
        ...     '  members {',
        ...     '    k8s-05.localdomain:8443 {',
        ...     '      address 192.0.2.5',
        ...     '      session monitor-enabled',
        ...     '      state up',
        ...     '    }',
        ...     '    k8s-06.localdomain:8443 {',
        ...     '      address 192.0.2.6',
        ...     '      session monitor-enabled',
        ...     '      state down',
        ...     '    }',
        ...     '  }',
        ...     '}',
        ...     'ltm pool BAR {',
        ...     '  members {',
        ...     '    k8s-07.localdomain:8443 {',
        ...     '      address 192.0.2.7',
        ...     '      session monitor-enabled',
        ...     '      state down',
        ...     '    }',
        ...     '  }',
        ...     '}',
        ...     ]
        >>> parse = CiscoConfParse(config, syntax='junos', comment='#')
        >>>
        >>> branchspec = (r'ltm\spool', r'members', r'\S+?:\d+', r'state\sup')
        >>> branches = parse.find_object_branches(branchspec=branchspec)
        >>>
        >>> # We found three branches
        >>> len(branches)
        3
        >>> # Each branch must match the length of branchspec
        >>> len(branches[0])
        4
        >>> # Print out one object 'branch'
        >>> branches[0]
        [<IOSCfgLine # 0 'ltm pool FOO'>, <IOSCfgLine # 1 '    members' (parent is # 0)>, <IOSCfgLine # 2 '        k8s-05.localdomain:8443' (parent is # 1)>, <IOSCfgLine # 5 '            state up' (parent is # 2)>]
        >>>
        >>> # Get the a list of text lines for this branch...
        >>> list(map(attrgetter('text'), branches[0]))
        ['ltm pool FOO', '    members', '        k8s-05.localdomain:8443', '            state up']
        >>>
        >>> # Get the config text of the root object of the branch...
        >>> branches[0][0].text
        'ltm pool FOO'
        >>>
        >>> # Note: `None` in branches[1][-1] because of no regex match
        >>> branches[1]
        [<IOSCfgLine # 0 'ltm pool FOO'>, <IOSCfgLine # 1 '    members' (parent is # 0)>, <IOSCfgLine # 6 '        k8s-06.localdomain:8443' (parent is # 1)>, None]
        >>>
        >>> branches[2]
        [<IOSCfgLine # 10 'ltm pool BAR'>, <IOSCfgLine # 11 '    members' (parent is # 10)>, <IOSCfgLine # 12 '        k8s-07.localdomain:8443' (parent is # 11)>, None]
        """
        assert isinstance(
            branchspec, tuple
        ), "find_object_branches(): Please enclose the regular expressions in a Python tuple"
        assert branchspec != (), "find_object_branches(): branchspec must not be empty"

        def list_matching_children(parent_obj, childspec, regex_flags, allow_none=True):
            ## I'm not using parent_obj.re_search_children() because
            ## re_search_children() doesn't return None for no match...

            # FIXME: Insert debugging here...
            # print("PARENT "+str(parent_obj))

            # Get the child objects from parent objects
            if parent_obj is None:
                children = self._find_line_OBJ(linespec=childspec, exactmatch=False)
            else:
                children = parent_obj.children

            # Find all child objects which match childspec...
            segment_list = [
                cobj
                for cobj in children
                if re.search(childspec, cobj.text, regex_flags)
            ]
            # Return [None] if no children matched...
            if (allow_none is True) and len(segment_list) == 0:
                segment_list = [None]

            # FIXME: Insert debugging here...
            # print("    SEGMENTS "+str(segment_list))
            return segment_list

        branches = list()
        # iterate over the regular expressions in branchspec
        for idx, childspec in enumerate(branchspec):
            # FIXME: Insert debugging here...
            # print("CHILDSPEC "+childspec)
            if idx == 0:
                # Get matching 'root' objects from the config
                next_kids = list_matching_children(
                    parent_obj=None,
                    childspec=childspec,
                    regex_flags=regex_flags,
                    allow_none=allow_none,
                )
                if allow_none is True:
                    # Start growing branches from the segments we received...
                    branches = [[kid] for kid in next_kids]
                else:
                    branches = [[kid] for kid in next_kids if kid is not None]

            else:
                new_branches = list()
                for branch in branches:
                    # Extend existing branches into the new_branches
                    if branch[-1] is not None:
                        # Find children to extend the family branch...
                        next_kids = list_matching_children(
                            parent_obj=branch[-1],
                            childspec=childspec,
                            regex_flags=regex_flags,
                            allow_none=allow_none,
                        )

                        for kid in next_kids:
                            # Fork off a new branch and add each matching kid...
                            # Use copy.copy() for a "shallow copy" of branch:
                            #    https://realpython.com/copying-python-objects/
                            tmp = copy.copy(branch)
                            tmp.append(kid)
                            new_branches.append(tmp)
                    elif allow_none is True:
                        branch.append(None)
                        new_branches.append(branch)

                # Ensure we have the most recent branches...
                branches = new_branches

        return branches

    def find_interface_objects(self, intfspec, exactmatch=True):
        """Find all :class:`~models_cisco.IOSCfgLine` or
        :class:`~models_cisco.NXOSCfgLine` objects whose text
        is an abbreviation for ``intfspec`` and return the
        objects in a python list.

        Notes
        -----
        The configuration *must* be parsed with ``factory=True`` to use this method

        Parameters
        ----------
        intfspec : str
            A string which is the abbreviation (or full name) of the interface
        exactmatch : bool
            Defaults to True; when True, this option requires ``intfspec`` match the whole interface name and number.

        Returns
        -------
        list
            A list of matching :class:`~ciscoconfparse.IOSIntfLine` objects

        Examples
        --------

        >>> from ciscoconfparse import CiscoConfParse
        >>> config = [
        ...     '!',
        ...     'interface Serial1/0',
        ...     ' ip address 1.1.1.1 255.255.255.252',
        ...     '!',
        ...     'interface Serial1/1',
        ...     ' ip address 1.1.1.5 255.255.255.252',
        ...     '!',
        ...     ]
        >>> parse = CiscoConfParse(config, factory=True)
        >>>
        >>> parse.find_interface_objects('Se 1/0')
        [<IOSIntfLine # 1 'Serial1/0' info: '1.1.1.1/30'>]
        >>>

        """
        if (self.factory is not True):
            error = "find_interface_objects() must be called with 'factory=True'"
            logger.error(error)
            raise ValueError(error)

        retval = list()
        if (self.syntax == "ios") or (self.syntax == "nxos"):
            if exactmatch:
                for obj in self.find_objects("^interface"):
                    if intfspec.lower() in obj.abbvs:
                        retval.append(obj)
                        break  # Only break if exactmatch is True
            else:
                error = "This method requires exactmatch set True"
                logger.error(error)
                raise NotImplementedError(error)
        ## TODO: implement ASAConfigLine.abbvs and others
        else:
            error = "This method requires exactmatch set True"
            logger.error(error)
            raise NotImplementedError(error)

        return retval

    def find_objects_dna(self, dnaspec, exactmatch=False):
        """Find all :class:`~models_cisco.IOSCfgLine` objects whose text
        matches ``dnaspec`` and return the :class:`~models_cisco.IOSCfgLine`
        objects in a python list.

        Notes
        -----
        :func:`~ciscoconfparse.CiscoConfParse.find_objects_dna` requires the configuration to be parsed with factory=True


        Parameters
        ----------
        dnaspec : str
            A string or python regular expression, which should be matched.  This argument will be used to match dna attribute of the object
        exactmatch : bool
            Defaults to False.  When set True, this option requires ``dnaspec`` match the whole configuration line, instead of a portion of the configuration line.

        Returns
        -------
        list
            A list of matching :class:`~ciscoconfparse.IOSCfgLine` objects

        Examples
        --------

        >>> from ciscoconfparse import CiscoConfParse
        >>> config = [
        ...     '!',
        ...     'hostname MyRouterHostname',
        ...     '!',
        ...     ]
        >>> parse = CiscoConfParse(config, factory=True, syntax='ios')
        >>>
        >>> obj_list = parse.find_objects_dna(r'Hostname')
        >>> obj_list
        [<IOSHostnameLine # 1 'MyRouterHostname'>]
        >>>
        >>> # The IOSHostnameLine object has a hostname attribute
        >>> obj_list[0].hostname
        'MyRouterHostname'
        """
        if not self.factory:
            error = "find_objects_dna() must be called with 'factory=True'"
            logger.error(error)
            raise ValueError(error)

        if not exactmatch:
            # Return objects whose text attribute matches linespec
            linespec_re = re.compile(dnaspec)
        elif exactmatch:
            # Return objects whose text attribute matches linespec exactly
            linespec_re = re.compile("^{0}$".format(dnaspec))
        return list(filter(lambda obj: linespec_re.search(obj.dna), self.ConfigObjs))

    def find_objects(self, linespec, exactmatch=False, ignore_ws=False):
        """Find all :class:`~models_cisco.IOSCfgLine` objects whose text
        matches ``linespec`` and return the :class:`~models_cisco.IOSCfgLine`
        objects in a python list.
        :func:`~ciscoconfparse.CiscoConfParse.find_objects` is similar to
        :func:`~ciscoconfparse.CiscoConfParse.find_lines`; however, the former
        returns a list of :class:`~models_cisco.IOSCfgLine` objects, while the
        latter returns a list of text configuration statements.  Going
        forward, I strongly encourage people to start using
        :func:`~ciscoconfparse.CiscoConfParse.find_objects` instead of
        :func:`~ciscoconfparse.CiscoConfParse.find_lines`.

        Parameters
        ----------
        linespec : str
            A string or python regular expression, which should be matched
        exactmatch : bool
            Defaults to False.  When set True, this option requires ``linespec`` match the whole configuration line, instead of a portion of the configuration line.
        ignore_ws : bool
            boolean that controls whether whitespace is ignored.  Default is False.

        Returns
        -------
        list
            A list of matching :class:`~ciscoconfparse.IOSCfgLine` objects

        Examples
        --------
        This example illustrates the difference between
        :func:`~ciscoconfparse.CiscoConfParse.find_objects` and
        :func:`~ciscoconfparse.CiscoConfParse.find_lines`.

        >>> from ciscoconfparse import CiscoConfParse
        >>> config = [
        ...     '!',
        ...     'interface Serial1/0',
        ...     ' ip address 1.1.1.1 255.255.255.252',
        ...     '!',
        ...     'interface Serial1/1',
        ...     ' ip address 1.1.1.5 255.255.255.252',
        ...     '!',
        ...     ]
        >>> parse = CiscoConfParse(config)
        >>>
        >>> parse.find_objects(r'^interface')
        [<IOSCfgLine # 1 'interface Serial1/0'>, <IOSCfgLine # 4 'interface Serial1/1'>]
        >>>
        >>> parse.find_lines(r'^interface')
        ['interface Serial1/0', 'interface Serial1/1']
        >>>

        """
        if ignore_ws:
            linespec = self._build_space_tolerant_regex(linespec)
        return self._find_line_OBJ(linespec, exactmatch)

    def find_lines(self, linespec, exactmatch=False, ignore_ws=False):
        """This method is the equivalent of a simple configuration grep
        (Case-sensitive).

        Parameters
        ----------
        linespec : str
            Text regular expression for the line to be matched
        exactmatch : bool
            Defaults to False.  When set True, this option requires ``linespec`` match the whole configuration line, instead of a portion of the configuration line.
        ignore_ws : bool
            boolean that controls whether whitespace is ignored.  Default is False.

        Returns
        -------
        list
            A list of matching configuration lines
        """
        if ignore_ws:
            linespec = self._build_space_tolerant_regex(linespec)

        if exactmatch is False:
            # Return the lines in self.ioscfg, which match linespec
            return list(filter(re.compile(linespec).search, self.ioscfg))
        else:
            # Return the lines in self.ioscfg, which match (exactly) linespec
            return list(filter(re.compile("^%s$" % linespec).search, self.ioscfg))

    def find_children(self, linespec, exactmatch=False, ignore_ws=False):
        """Returns the parents matching the linespec, and their immediate
        children.  This method is different than :meth:`find_all_children`,
        because :meth:`find_all_children` finds children of children.
        :meth:`find_children` only finds immediate children.

        Parameters
        ----------
        linespec : str
            Text regular expression for the line to be matched
        exactmatch : bool
            boolean that controls whether partial matches are valid
        ignore_ws : bool
            boolean that controls whether whitespace is ignored

        Returns
        -------
        list
            A list of matching configuration lines

        Examples
        --------

        >>> from ciscoconfparse import CiscoConfParse
        >>> config = ['username ddclient password 7 107D3D232342041E3A',
        ...           'archive',
        ...           ' log config',
        ...           '  logging enable',
        ...           '  hidekeys',
        ...           ' path ftp://ns.foo.com//tftpboot/Foo-archive',
        ...           '!',
        ...     ]
        >>> p = CiscoConfParse(config)
        >>> p.find_children('^archive')
        ['archive', ' log config', ' path ftp://ns.foo.com//tftpboot/Foo-archive']
        >>>
        """
        if ignore_ws:
            linespec = self._build_space_tolerant_regex(linespec)

        if exactmatch is False:
            parentobjs = self._find_line_OBJ(linespec)
        else:
            parentobjs = self._find_line_OBJ("^%s$" % linespec)

        allobjs = set([])
        for parent in parentobjs:
            if parent.has_children is True:
                allobjs.update(set(parent.children))
            allobjs.add(parent)

        return list(map(attrgetter("text"), sorted(allobjs)))

    def find_all_children(self, linespec, exactmatch=False, ignore_ws=False):
        """Returns the parents matching the linespec, and all their children.
        This method is different than :meth:`find_children`, because
        :meth:`find_all_children` finds children of children.
        :meth:`find_children` only finds immediate children.

        Parameters
        ----------
        linespec : str
            Text regular expression for the line to be matched
        exactmatch : bool
            boolean that controls whether partial matches are valid
        ignore_ws : bool
            boolean that controls whether whitespace is ignored

        Returns
        -------
        list
            A list of matching configuration lines

        Examples
        --------
        Suppose you are interested in finding all `archive` statements in
        the following configuration...

        .. code::

           username ddclient password 7 107D3D232342041E3A
           archive
            log config
             logging enable
             hidekeys
            path ftp://ns.foo.com//tftpboot/Foo-archive
           !

        Using the config above, we expect to find the following config lines...

        .. code::

           archive
            log config
             logging enable
             hidekeys
            path ftp://ns.foo.com//tftpboot/Foo-archive

        We would accomplish this by querying `find_all_children('^archive')`...

        >>> from ciscoconfparse import CiscoConfParse
        >>> config = ['username ddclient password 7 107D3D232342041E3A',
        ...           'archive',
        ...           ' log config',
        ...           '  logging enable',
        ...           '  hidekeys',
        ...           ' path ftp://ns.foo.com//tftpboot/Foo-archive',
        ...           '!',
        ...     ]
        >>> p = CiscoConfParse(config)
        >>> p.find_all_children('^archive')
        ['archive', ' log config', '  logging enable', '  hidekeys', ' path ftp://ns.foo.com//tftpboot/Foo-archive']
        >>>
        """

        if ignore_ws:
            linespec = self._build_space_tolerant_regex(linespec)

        if exactmatch is False:
            parentobjs = self._find_line_OBJ(linespec)
        else:
            parentobjs = self._find_line_OBJ("^%s$" % linespec)

        allobjs = set([])
        for parent in parentobjs:
            allobjs.add(parent)
            allobjs.update(set(parent.all_children))
        return list(map(attrgetter("text"), sorted(allobjs)))

    def find_blocks(self, linespec, exactmatch=False, ignore_ws=False):
        """Find all siblings matching the linespec, then find all parents of
        those siblings. Return a list of config lines sorted by line number,
        lowest first.  Note: any children of the siblings should NOT be
        returned.

        Parameters
        ----------
        linespec : str
            Text regular expression for the line to be matched
        exactmatch : bool
            boolean that controls whether partial matches are valid
        ignore_ws : bool
            boolean that controls whether whitespace is ignored

        Returns
        -------
        list
            A list of matching configuration lines


        Examples
        --------
        This example finds `bandwidth percent` statements in following config,
        the siblings of those `bandwidth percent` statements, as well
        as the parent configuration statements required to access them.

        .. code::

           !
           policy-map EXTERNAL_CBWFQ
            class IP_PREC_HIGH
             priority percent 10
             police cir percent 10
               conform-action transmit
               exceed-action drop
            class IP_PREC_MEDIUM
             bandwidth percent 50
             queue-limit 100
            class class-default
             bandwidth percent 40
             queue-limit 100
           policy-map SHAPE_HEIR
            class ALL
             shape average 630000
             service-policy EXTERNAL_CBWFQ
           !

        The following config lines should be returned:

        .. code::

           policy-map EXTERNAL_CBWFQ
            class IP_PREC_MEDIUM
             bandwidth percent 50
             queue-limit 100
            class class-default
             bandwidth percent 40
             queue-limit 100

        We do this by quering `find_blocks('bandwidth percent')`...

        .. code-block:: python
           :emphasize-lines: 22,25

           >>> from ciscoconfparse import CiscoConfParse
           >>> config = ['!',
           ...           'policy-map EXTERNAL_CBWFQ',
           ...           ' class IP_PREC_HIGH',
           ...           '  priority percent 10',
           ...           '  police cir percent 10',
           ...           '    conform-action transmit',
           ...           '    exceed-action drop',
           ...           ' class IP_PREC_MEDIUM',
           ...           '  bandwidth percent 50',
           ...           '  queue-limit 100',
           ...           ' class class-default',
           ...           '  bandwidth percent 40',
           ...           '  queue-limit 100',
           ...           'policy-map SHAPE_HEIR',
           ...           ' class ALL',
           ...           '  shape average 630000',
           ...           '  service-policy EXTERNAL_CBWFQ',
           ...           '!',
           ...     ]
           >>> p = CiscoConfParse(config)
           >>> p.find_blocks('bandwidth percent')
           ['policy-map EXTERNAL_CBWFQ', ' class IP_PREC_MEDIUM', '  bandwidth percent 50', '  queue-limit 100', ' class class-default', '  bandwidth percent 40', '  queue-limit 100']
           >>>
           >>> p.find_blocks(' class class-default')
           ['policy-map EXTERNAL_CBWFQ', ' class IP_PREC_HIGH', ' class IP_PREC_MEDIUM', ' class class-default']
           >>>

        """
        tmp = set([])

        if ignore_ws:
            linespec = self._build_space_tolerant_regex(linespec)

        # Find line objects maching the spec
        if exactmatch is False:
            objs = self._find_line_OBJ(linespec)
        else:
            objs = self._find_line_OBJ("^%s$" % linespec)

        for obj in objs:
            tmp.add(obj)
            # Find the siblings of this line
            sib_objs = self._find_sibling_OBJ(obj)
            for sib_obj in sib_objs:
                tmp.add(sib_obj)

        # Find the parents for everything
        pobjs = set([])
        for lineobject in tmp:
            for pobj in lineobject.all_parents:
                pobjs.add(pobj)
        tmp.update(pobjs)

        return list(map(attrgetter("text"), sorted(tmp)))

    def find_objects_w_child(
        self, parentspec, childspec, ignore_ws=False, recurse=False
    ):
        """
        Return a list of parent :class:`~models_cisco.IOSCfgLine` objects,
        which matched the ``parentspec`` and whose children match ``childspec``.
        Only the parent :class:`~models_cisco.IOSCfgLine` objects will be
        returned.

        Parameters
        ----------
        parentspec : str
            Text regular expression for the :class:`~models_cisco.IOSCfgLine` object to be matched; this must match the parent's line
        childspec : str
            Text regular expression for the line to be matched; this must match the child's line
        ignore_ws : bool
            boolean that controls whether whitespace is ignored
        recurse : bool
            Set True if you want to search all children (children, grand children, great grand children, etc...)

        Returns
        -------
        list
            A list of matching parent :class:`~models_cisco.IOSCfgLine` objects

        Examples
        --------
        This example uses :func:`~ciscoconfparse.find_objects_w_child()` to
        find all ports that are members of access vlan 300 in following
        config...

        .. code::

           !
           interface FastEthernet0/1
            switchport access vlan 532
            spanning-tree vlan 532 cost 3
           !
           interface FastEthernet0/2
            switchport access vlan 300
            spanning-tree portfast
           !
           interface FastEthernet0/3
            duplex full
            speed 100
            switchport access vlan 300
            spanning-tree portfast
           !

        The following interfaces should be returned:

        .. code::

           interface FastEthernet0/2
           interface FastEthernet0/3

        We do this by quering `find_objects_w_child()`; we set our
        parent as `^interface` and set the child as `switchport access
        vlan 300`.

        .. code-block:: python
           :emphasize-lines: 20

           >>> from ciscoconfparse import CiscoConfParse
           >>> config = ['!',
           ...           'interface FastEthernet0/1',
           ...           ' switchport access vlan 532',
           ...           ' spanning-tree vlan 532 cost 3',
           ...           '!',
           ...           'interface FastEthernet0/2',
           ...           ' switchport access vlan 300',
           ...           ' spanning-tree portfast',
           ...           '!',
           ...           'interface FastEthernet0/3',
           ...           ' duplex full',
           ...           ' speed 100',
           ...           ' switchport access vlan 300',
           ...           ' spanning-tree portfast',
           ...           '!',
           ...     ]
           >>> p = CiscoConfParse(config)
           >>> p.find_objects_w_child('^interface',
           ...     'switchport access vlan 300')
           ...
           [<IOSCfgLine # 5 'interface FastEthernet0/2'>, <IOSCfgLine # 9 'interface FastEthernet0/3'>]
           >>>
        """

        if ignore_ws:
            parentspec = self._build_space_tolerant_regex(parentspec)
            childspec = self._build_space_tolerant_regex(childspec)

        return list(
            filter(
                lambda x: x.re_search_children(childspec, recurse=recurse),
                self.find_objects(parentspec),
            )
        )

    def find_objects_w_all_children(
        self, parentspec, childspec, ignore_ws=False, recurse=False
    ):
        """Return a list of parent :class:`~models_cisco.IOSCfgLine` objects,
        which matched the ``parentspec`` and whose children match all elements
        in ``childspec``.  Only the parent :class:`~models_cisco.IOSCfgLine`
        objects will be returned.

        Parameters
        ----------
        parentspec : str
            Text regular expression for the :class:`~models_cisco.IOSCfgLine` object to be matched; this must match the parent's line
        childspec : str
            A list of text regular expressions to be matched among the children
        ignore_ws : bool
            boolean that controls whether whitespace is ignored
        recurse : bool
            Set True if you want to search all children (children, grand children, great grand children, etc...)

        Returns
        -------
        list
            A list of matching parent :class:`~models_cisco.IOSCfgLine` objects

        Examples
        --------
        This example uses :func:`~ciscoconfparse.find_objects_w_child()` to
        find all ports that are members of access vlan 300 in following
        config...

        .. code::

           !
           interface FastEthernet0/1
            switchport access vlan 532
            spanning-tree vlan 532 cost 3
           !
           interface FastEthernet0/2
            switchport access vlan 300
            spanning-tree portfast
           !
           interface FastEthernet0/2
            duplex full
            speed 100
            switchport access vlan 300
            spanning-tree portfast
           !

        The following interfaces should be returned:

        .. code::

           interface FastEthernet0/2
           interface FastEthernet0/3

        We do this by quering `find_objects_w_all_children()`; we set our
        parent as `^interface` and set the childspec as
        ['switchport access vlan 300', 'spanning-tree portfast'].

        .. code-block:: python
           :emphasize-lines: 19

           >>> from ciscoconfparse import CiscoConfParse
           >>> config = ['!',
           ...           'interface FastEthernet0/1',
           ...           ' switchport access vlan 532',
           ...           ' spanning-tree vlan 532 cost 3',
           ...           '!',
           ...           'interface FastEthernet0/2',
           ...           ' switchport access vlan 300',
           ...           ' spanning-tree portfast',
           ...           '!',
           ...           'interface FastEthernet0/3',
           ...           ' duplex full',
           ...           ' speed 100',
           ...           ' switchport access vlan 300',
           ...           ' spanning-tree portfast',
           ...           '!',
           ...     ]
           >>> p = CiscoConfParse(config)
           >>> p.find_objects_w_all_children('^interface',
           ...     ['switchport access vlan 300', 'spanning-tree portfast'])
           ...
           [<IOSCfgLine # 5 'interface FastEthernet0/2'>, <IOSCfgLine # 9 'interface FastEthernet0/3'>]
           >>>
        """

        assert bool(getattr(childspec, "append"))  # Childspec must be a list
        retval = list()
        if ignore_ws:
            parentspec = self._build_space_tolerant_regex(parentspec)
            childspec = map(self._build_space_tolerant_regex, childspec)

        for parentobj in self.find_objects(parentspec):
            results = set([])
            for child_cfg in childspec:
                results.add(
                    bool(parentobj.re_search_children(child_cfg, recurse=recurse))
                )
            if False in results:
                continue
            else:
                retval.append(parentobj)

        return retval

    def find_objects_w_missing_children(self, parentspec, childspec, ignore_ws=False):
        """Return a list of parent :class:`~models_cisco.IOSCfgLine` objects,
        which matched the ``parentspec`` and whose children do not match
        all elements in ``childspec``.  Only the parent
        :class:`~models_cisco.IOSCfgLine` objects will be returned.

        Parameters
        ----------
        parentspec : str
            Text regular expression for the :class:`~models_cisco.IOSCfgLine` object to be matched; this must match the parent's line
        childspec : str
            A list of text regular expressions to be matched among the children
        ignore_ws : bool
            boolean that controls whether whitespace is ignored

        Returns
        -------
        list
            A list of matching parent :class:`~models_cisco.IOSCfgLine` objects"""
        assert bool(getattr(childspec, "append"))  # Childspec must be a list
        retval = list()
        if ignore_ws:
            parentspec = self._build_space_tolerant_regex(parentspec)
            childspec = map(self._build_space_tolerant_regex, childspec)

        for parentobj in self.find_objects(parentspec):
            results = set([])
            for child_cfg in childspec:
                results.add(bool(parentobj.re_search_children(child_cfg)))
            if False in results:
                retval.append(parentobj)
            else:
                continue

        return retval

    def find_parents_w_child(self, parentspec, childspec, ignore_ws=False):
        """Parse through all children matching childspec, and return a list of
        parents that matched the parentspec.  Only the parent lines will be
        returned.

        Parameters
        ----------
        parentspec : str
            Text regular expression for the line to be matched; this must match the parent's line
        childspec : str
            Text regular expression for the line to be matched; this must match the child's line
        ignore_ws : bool
            boolean that controls whether whitespace is ignored

        Returns
        -------
        list
            A list of matching parent configuration lines

        Examples
        --------
        This example finds all ports that are members of access vlan 300
        in following config...

        .. code::

           !
           interface FastEthernet0/1
            switchport access vlan 532
            spanning-tree vlan 532 cost 3
           !
           interface FastEthernet0/2
            switchport access vlan 300
            spanning-tree portfast
           !
           interface FastEthernet0/2
            duplex full
            speed 100
            switchport access vlan 300
            spanning-tree portfast
           !

        The following interfaces should be returned:

        .. code::

           interface FastEthernet0/2
           interface FastEthernet0/3

        We do this by quering `find_parents_w_child()`; we set our
        parent as `^interface` and set the child as
        `switchport access vlan 300`.

        .. code-block:: python
           :emphasize-lines: 18

           >>> from ciscoconfparse import CiscoConfParse
           >>> config = ['!',
           ...           'interface FastEthernet0/1',
           ...           ' switchport access vlan 532',
           ...           ' spanning-tree vlan 532 cost 3',
           ...           '!',
           ...           'interface FastEthernet0/2',
           ...           ' switchport access vlan 300',
           ...           ' spanning-tree portfast',
           ...           '!',
           ...           'interface FastEthernet0/3',
           ...           ' duplex full',
           ...           ' speed 100',
           ...           ' switchport access vlan 300',
           ...           ' spanning-tree portfast',
           ...           '!',
           ...     ]
           >>> p = CiscoConfParse(config)
           >>> p.find_parents_w_child('^interface', 'switchport access vlan 300')
           ['interface FastEthernet0/2', 'interface FastEthernet0/3']
           >>>

        """
        tmp = self.find_objects_w_child(parentspec, childspec, ignore_ws=ignore_ws)
        return list(map(attrgetter("text"), tmp))

    def find_objects_wo_child(self, parentspec, childspec, ignore_ws=False):
        r"""Return a list of parent :class:`~models_cisco.IOSCfgLine` objects, which matched the ``parentspec`` and whose children did not match ``childspec``.  Only the parent :class:`~models_cisco.IOSCfgLine` objects will be returned.  For simplicity, this method only finds oldest_ancestors without immediate children that match.

        Parameters
        ----------
        parentspec : str
            Text regular expression for the :class:`~models_cisco.IOSCfgLine` object to be matched; this must match the parent's line
        childspec : str
            Text regular expression for the line to be matched; this must match the child's line
        ignore_ws : bool
            boolean that controls whether whitespace is ignored

        Returns
        -------
        list
            A list of matching parent configuration lines

        Examples
        --------
        This example finds all ports that are autonegotiating in the following config...

        .. code::

           !
           interface FastEthernet0/1
            switchport access vlan 532
            spanning-tree vlan 532 cost 3
           !
           interface FastEthernet0/2
            switchport access vlan 300
            spanning-tree portfast
           !
           interface FastEthernet0/2
            duplex full
            speed 100
            switchport access vlan 300
            spanning-tree portfast
           !

        The following interfaces should be returned:

        .. code::

           interface FastEthernet0/1
           interface FastEthernet0/2

        We do this by quering `find_objects_wo_child()`; we set our
        parent as `^interface` and set the child as `speed\s\d+` (a
        regular-expression which matches the word 'speed' followed by
        an integer).

        .. code-block:: python
           :emphasize-lines: 19

           >>> from ciscoconfparse import CiscoConfParse
           >>> config = ['!',
           ...           'interface FastEthernet0/1',
           ...           ' switchport access vlan 532',
           ...           ' spanning-tree vlan 532 cost 3',
           ...           '!',
           ...           'interface FastEthernet0/2',
           ...           ' switchport access vlan 300',
           ...           ' spanning-tree portfast',
           ...           '!',
           ...           'interface FastEthernet0/3',
           ...           ' duplex full',
           ...           ' speed 100',
           ...           ' switchport access vlan 300',
           ...           ' spanning-tree portfast',
           ...           '!',
           ...     ]
           >>> p = CiscoConfParse(config)
           >>> p.find_objects_wo_child(r'^interface', r'speed\s\d+')
           [<IOSCfgLine # 1 'interface FastEthernet0/1'>, <IOSCfgLine # 5 'interface FastEthernet0/2'>]
           >>>
        """

        if ignore_ws:
            parentspec = self._build_space_tolerant_regex(parentspec)
            childspec = self._build_space_tolerant_regex(childspec)

        return [
            obj
            for obj in self.find_objects(parentspec)
            if not obj.re_search_children(childspec)
        ]

    def find_parents_wo_child(self, parentspec, childspec, ignore_ws=False):
        r"""Parse through all parents matching parentspec, and return a list of parents that did NOT have children match the childspec.  For simplicity, this method only finds oldest_ancestors without immediate children that match.

        Parameters
        ----------
        parentspec : str
            Text regular expression for the line to be matched; this must match the parent's line
        childspec : str
            Text regular expression for the line to be matched; this must match the child's line
        ignore_ws : bool
            boolean that controls whether whitespace is ignored

        Returns
        -------
        list
            A list of matching parent configuration lines

        Examples
        --------
        This example finds all ports that are autonegotiating in the
        following config...

        .. code::

           !
           interface FastEthernet0/1
            switchport access vlan 532
            spanning-tree vlan 532 cost 3
           !
           interface FastEthernet0/2
            switchport access vlan 300
            spanning-tree portfast
           !
           interface FastEthernet0/2
            duplex full
            speed 100
            switchport access vlan 300
            spanning-tree portfast
           !

        The following interfaces should be returned:

        .. code::

           interface FastEthernet0/1
           interface FastEthernet0/2

        We do this by quering `find_parents_wo_child()`; we set our
        parent as `^interface` and set the child as `speed\s\d+` (a
        regular-expression which matches the word 'speed' followed by
        an integer).

        .. code-block:: python
           :emphasize-lines: 19

           >>> from ciscoconfparse import CiscoConfParse
           >>> config = ['!',
           ...           'interface FastEthernet0/1',
           ...           ' switchport access vlan 532',
           ...           ' spanning-tree vlan 532 cost 3',
           ...           '!',
           ...           'interface FastEthernet0/2',
           ...           ' switchport access vlan 300',
           ...           ' spanning-tree portfast',
           ...           '!',
           ...           'interface FastEthernet0/3',
           ...           ' duplex full',
           ...           ' speed 100',
           ...           ' switchport access vlan 300',
           ...           ' spanning-tree portfast',
           ...           '!',
           ...     ]
           >>> p = CiscoConfParse(config)
           >>> p.find_parents_wo_child('^interface', 'speed\s\d+')
           ['interface FastEthernet0/1', 'interface FastEthernet0/2']
           >>>

        """
        tmp = self.find_objects_wo_child(parentspec, childspec, ignore_ws=ignore_ws)
        return list(map(attrgetter("text"), tmp))

    def find_children_w_parents(self, parentspec, childspec, ignore_ws=False):
        r"""Parse through the children of all parents matching parentspec,
        and return a list of children that matched the childspec.

        Parameters
        ----------
        parentspec : str
            Text regular expression for the line to be matched; this must match the parent's line
        childspec : str
            Text regular expression for the line to be matched; this must match the child's line
        ignore_ws : bool
            boolean that controls whether whitespace is ignored

        Returns
        -------
        list
            A list of matching child configuration lines

        Examples
        --------
        This example finds the port-security lines on FastEthernet0/1 in
        following config...

        .. code::

           !
           interface FastEthernet0/1
            switchport access vlan 532
            switchport port-security
            switchport port-security violation protect
            switchport port-security aging time 5
            switchport port-security aging type inactivity
            spanning-tree portfast
            spanning-tree bpduguard enable
           !
           interface FastEthernet0/2
            switchport access vlan 300
            spanning-tree portfast
            spanning-tree bpduguard enable
           !
           interface FastEthernet0/2
            duplex full
            speed 100
            switchport access vlan 300
            spanning-tree portfast
            spanning-tree bpduguard enable
           !

        The following lines should be returned:

        .. code::

            switchport port-security
            switchport port-security violation protect
            switchport port-security aging time 5
            switchport port-security aging type inactivity

        We do this by quering `find_children_w_parents()`; we set our
        parent as `^interface` and set the child as
        `switchport port-security`.

        .. code-block:: python
           :emphasize-lines: 26

           >>> from ciscoconfparse import CiscoConfParse
           >>> config = ['!',
           ...           'interface FastEthernet0/1',
           ...           ' switchport access vlan 532',
           ...           ' switchport port-security',
           ...           ' switchport port-security violation protect',
           ...           ' switchport port-security aging time 5',
           ...           ' switchport port-security aging type inactivity',
           ...           ' spanning-tree portfast',
           ...           ' spanning-tree bpduguard enable',
           ...           '!',
           ...           'interface FastEthernet0/2',
           ...           ' switchport access vlan 300',
           ...           ' spanning-tree portfast',
           ...           ' spanning-tree bpduguard enable',
           ...           '!',
           ...           'interface FastEthernet0/3',
           ...           ' duplex full',
           ...           ' speed 100',
           ...           ' switchport access vlan 300',
           ...           ' spanning-tree portfast',
           ...           ' spanning-tree bpduguard enable',
           ...           '!',
           ...     ]
           >>> p = CiscoConfParse(config)
           >>> p.find_children_w_parents('^interface\sFastEthernet0/1',
           ... 'port-security')
           [' switchport port-security', ' switchport port-security violation protect', ' switchport port-security aging time 5', ' switchport port-security aging type inactivity']
           >>>

        """
        if ignore_ws:
            parentspec = self._build_space_tolerant_regex(parentspec)
            childspec = self._build_space_tolerant_regex(childspec)

        retval = set([])
        childobjs = self._find_line_OBJ(childspec)
        for child in childobjs:
            parents = child.all_parents
            for parent in parents:
                if re.search(parentspec, parent.text):
                    retval.add(child)

        return list(map(attrgetter("text"), sorted(retval)))

    def find_objects_w_parents(self, parentspec, childspec, ignore_ws=False):
        r"""Parse through the children of all parents matching parentspec,
        and return a list of child objects, which matched the childspec.

        Parameters
        ----------
        parentspec : str
            Text regular expression for the line to be matched; this must match the parent's line
        childspec : str
            Text regular expression for the line to be matched; this must match the child's line
        ignore_ws : bool
            boolean that controls whether whitespace is ignored

        Returns
        -------
        list
            A list of matching child objects

        Examples
        --------
        This example finds the object for "ge-0/0/0" under "interfaces" in the
        following config...

        .. code::

            interfaces
                ge-0/0/0
                    unit 0
                        family ethernet-switching
                            port-mode access
                            vlan
                                members VLAN_FOO
                ge-0/0/1
                    unit 0
                        family ethernet-switching
                            port-mode trunk
                            vlan
                                members all
                            native-vlan-id 1
                vlan
                    unit 0
                        family inet
                            address 172.16.15.5/22


        The following object should be returned:

        .. code::

            <IOSCfgLine # 7 '    ge-0/0/1' (parent is # 0)>

        We do this by quering `find_objects_w_parents()`; we set our
        parent as `^\s*interface` and set the child as
        `^\s+ge-0/0/1`.

        .. code-block:: python
           :emphasize-lines: 22,23

           >>> from ciscoconfparse import CiscoConfParse
           >>> config = ['interfaces',
           ...           '    ge-0/0/0',
           ...           '        unit 0',
           ...           '            family ethernet-switching',
           ...           '                port-mode access',
           ...           '                vlan',
           ...           '                    members VLAN_FOO',
           ...           '    ge-0/0/1',
           ...           '        unit 0',
           ...           '            family ethernet-switching',
           ...           '                port-mode trunk',
           ...           '                vlan',
           ...           '                    members all',
           ...           '                native-vlan-id 1',
           ...           '    vlan',
           ...           '        unit 0',
           ...           '            family inet',
           ...           '                address 172.16.15.5/22',
           ...     ]
           >>> p = CiscoConfParse(config)
           >>> p.find_objects_w_parents('^\s*interfaces',
           ... r'\s+ge-0/0/1')
           [<IOSCfgLine # 7 '    ge-0/0/1' (parent is # 0)>]
           >>>

        """
        if ignore_ws:
            parentspec = self._build_space_tolerant_regex(parentspec)
            childspec = self._build_space_tolerant_regex(childspec)

        retval = set([])
        childobjs = self._find_line_OBJ(childspec)
        for child in childobjs:
            parents = child.all_parents
            for parent in parents:
                if re.search(parentspec, parent.text):
                    retval.add(child)

        return sorted(retval)

    def find_lineage(self, linespec, exactmatch=False):
        """Iterate through to the oldest ancestor of this object, and return
        a list of all ancestors / children in the direct line.  Cousins or
        aunts / uncles are *not* returned.  Note, all children
        of this object are returned.

        Parameters
        ----------
        linespec : str
            Text regular expression for the line to be matched
        exactmatch : bool
            Defaults to False; when True, this option requires ``linespec`` the whole line (not merely a portion of the line)

        Returns
        -------
        list
            A list of matching objects
        """
        tmp = self.find_objects(linespec, exactmatch=exactmatch)
        if len(tmp) > 1:
            error = "linespec must be unique"
            logger.error(error)
            raise ValueError(error)

        return [obj.text for obj in tmp[0].lineage]

    def has_line_with(self, linespec):
        return self.ConfigObjs.has_line_with(linespec)

    def insert_before(
        self, exist_val, new_val="", exactmatch=False, ignore_ws=False, atomic=False, **kwargs
    ):
        """Find all objects whose text matches exist_val, and insert 'new_val' before those line objects"""

        ######################################################################
        # Named parameter migration warnings...
        #   - `linespec` is now called exist_val
        #   - `insertstr` is now called new_val
        ######################################################################
        if kwargs.get("linespec", ""):
            exist_val = kwargs.get("linespec")
            logger.info("The parameter named `linespec` is deprecated.  Please use `exist_val` instead")
        if kwargs.get("insertstr", ""):
            new_val = kwargs.get("insertstr")
            logger.info("The parameter named `insertstr` is deprecated.  Please use `new_val` instead")

        error_exist_val = "FATAL: exist_val:'%s' must be a string" % exist_val
        error_new_val = "FATAL: new_val:'%s' must be a string" % new_val
        assert isinstance(exist_val, str), error_exist_val
        assert isinstance(new_val, str), error_new_val

        objs = self.find_objects(exist_val, exactmatch, ignore_ws)
        self.ConfigObjs.insert_before(exist_val, new_val, atomic=atomic)
        self.commit()
        return list(map(attrgetter("text"), sorted(objs)))

###########################################################################start
    def insert_after(
        self,  exist_val, new_val="", exactmatch=False, ignore_ws=False, atomic=False, **kwargs
    ):
        """Find all :class:`~models_cisco.IOSCfgLine` objects whose text
        matches ``exist_val``, and insert ``new_val`` after those line
        objects"""

        ######################################################################
        # Named parameter migration warnings...
        #   - `linespec` is now called exist_val
        #   - `insertstr` is now called new_val
        ######################################################################
        if kwargs.get("linespec", ""):
            exist_val = kwargs.get("linespec")
            logger.info("The parameter named `linespec` is deprecated.  Please use `exist_val` instead")
        if kwargs.get("insertstr", ""):
            new_val = kwargs.get("insertstr")
            logger.info("The parameter named `insertstr` is deprecated.  Please use `new_val` instead")

        error_exist_val = "FATAL: exist_val:'%s' must be a string" % exist_val
        error_new_val = "FATAL: new_val:'%s' must be a string" % new_val
        assert isinstance(exist_val, str), error_exist_val
        assert isinstance(new_val, str), error_new_val

        objs = self.find_objects(exist_val, exactmatch, ignore_ws)
        self.ConfigObjs.insert_after(exist_val, new_val, atomic=atomic)
        return list(map(attrgetter("text"), sorted(objs)))
###########################################################################stop

    def insert_after_child(
        self,
        parentspec,
        childspec,
        insertstr="",
        exactmatch=False,
        excludespec=None,
        ignore_ws=False,
        atomic=False,
    ):
        """Find all :class:`~models_cisco.IOSCfgLine` objects whose text
        matches ``linespec`` and have a child matching ``childspec``, and
        insert an :class:`~models_cisco.IOSCfgLine` object for ``insertstr``
        after those child objects."""
        retval = list()
        modified = False
        for pobj in self._find_line_OBJ(parentspec, exactmatch=exactmatch):
            if excludespec and re.search(excludespec, pobj.text):
                # Exclude replacements on pobj lines which match excludespec
                continue
            for cobj in pobj.children:
                if excludespec and re.search(excludespec, cobj.text):
                    # Exclude replacements on pobj lines which match excludespec
                    continue
                elif re.search(childspec, cobj.text):
                    modified = True
                    retval.append(
                        self.ConfigObjs.insert_after(cobj, insertstr, atomic=atomic)
                    )
                else:
                    pass
        return retval

    def delete_lines(self, linespec, exactmatch=False, ignore_ws=False):
        """Find all :class:`~models_cisco.IOSCfgLine` objects whose text
        matches linespec, and delete the object"""
        objs = self.find_objects(linespec, exactmatch, ignore_ws)
        for obj in reversed(objs):
            # NOTE - 'del self.ConfigObjs...' was replaced in version 1.5.30
            #    with a simpler approach
            # del self.ConfigObjs[obj.linenum]
            obj.delete()

    def prepend_line(self, linespec):
        """Unconditionally insert an :class:`~models_cisco.IOSCfgLine` object
        for ``linespec`` (a text line) at the top of the configuration"""
        self.ConfigObjs.insert(0, linespec)
        return self.ConfigObjs[0]

    def append_line(self, linespec):
        """Unconditionally insert ``linespec`` (a text line) at the end of the
        configuration

        Parameters
        ----------
        linespec : str
            Text IOS configuration line

        Returns
        -------
        The parsed :class:`~models_cisco.IOSCfgLine` object instance

        """
        self.ConfigObjs.append(linespec)
        return self.ConfigObjs[-1]

    def replace_lines(
        self, linespec, replacestr, excludespec=None, exactmatch=False, atomic=False
    ):
        """This method is a text search and replace (Case-sensitive).  You can
        optionally exclude lines from replacement by including a string (or
        compiled regular expression) in `excludespec`.

        Parameters
        ----------
        linespec : str
            Text regular expression for the line to be matched
        replacestr : str
            Text used to replace strings matching linespec
        excludespec : str
            Text regular expression used to reject lines, which would otherwise be replaced.  Default value of ``excludespec`` is None, which means nothing is excluded
        exactmatch : bool
            boolean that controls whether partial matches are valid
        atomic : bool
            boolean that controls whether the config is reparsed after replacement (default False)

        Returns
        -------
        list
            A list of changed configuration lines

        Examples
        --------
        This example finds statements with `EXTERNAL_CBWFQ` in following
        config, and replaces all matching lines (in-place) with `EXTERNAL_QOS`.
        For the purposes of this example, let's assume that we do *not* want
        to make changes to any descriptions on the policy.

        .. code::

           !
           policy-map EXTERNAL_CBWFQ
            description implement an EXTERNAL_CBWFQ policy
            class IP_PREC_HIGH
             priority percent 10
             police cir percent 10
               conform-action transmit
               exceed-action drop
            class IP_PREC_MEDIUM
             bandwidth percent 50
             queue-limit 100
            class class-default
             bandwidth percent 40
             queue-limit 100
           policy-map SHAPE_HEIR
            class ALL
             shape average 630000
             service-policy EXTERNAL_CBWFQ
           !

        We do this by calling `replace_lines(linespec='EXTERNAL_CBWFQ',
        replacestr='EXTERNAL_QOS', excludespec='description')`...

        .. code-block:: python
           :emphasize-lines: 23

           >>> from ciscoconfparse import CiscoConfParse
           >>> config = ['!',
           ...           'policy-map EXTERNAL_CBWFQ',
           ...           ' description implement an EXTERNAL_CBWFQ policy',
           ...           ' class IP_PREC_HIGH',
           ...           '  priority percent 10',
           ...           '  police cir percent 10',
           ...           '    conform-action transmit',
           ...           '    exceed-action drop',
           ...           ' class IP_PREC_MEDIUM',
           ...           '  bandwidth percent 50',
           ...           '  queue-limit 100',
           ...           ' class class-default',
           ...           '  bandwidth percent 40',
           ...           '  queue-limit 100',
           ...           'policy-map SHAPE_HEIR',
           ...           ' class ALL',
           ...           '  shape average 630000',
           ...           '  service-policy EXTERNAL_CBWFQ',
           ...           '!',
           ...     ]
           >>> p = CiscoConfParse(config)
           >>> p.replace_lines('EXTERNAL_CBWFQ', 'EXTERNAL_QOS', 'description')
           ['policy-map EXTERNAL_QOS', '  service-policy EXTERNAL_QOS']
           >>>
           >>> # Now when we call `p.find_blocks('policy-map EXTERNAL_QOS')`, we get the
           >>> # changed configuration, which has the replacements except on the
           >>> # policy-map's description.
           >>> p.find_blocks('EXTERNAL_QOS')
           ['policy-map EXTERNAL_QOS', ' description implement an EXTERNAL_CBWFQ policy', ' class IP_PREC_HIGH', ' class IP_PREC_MEDIUM', ' class class-default', 'policy-map SHAPE_HEIR', ' class ALL', '  shape average 630000', '  service-policy EXTERNAL_QOS']
           >>>

        """
        retval = list()
        ## Since we are replacing text, we *must* operate on ConfigObjs
        if excludespec:
            excludespec_re = re.compile(excludespec)

        for obj in self._find_line_OBJ(linespec, exactmatch=exactmatch):
            if excludespec and excludespec_re.search(obj.text):
                # Exclude replacements on lines which match excludespec
                continue
            retval.append(obj.re_sub(linespec, replacestr))

        if self.factory and atomic:
            # self.ConfigObjs._reassign_linenums()
            self.ConfigObjs._bootstrap_from_text()

        return retval

    def replace_children(
        self,
        parentspec,
        childspec,
        replacestr,
        excludespec=None,
        exactmatch=False,
        atomic=False,
    ):
        r"""Replace lines matching `childspec` within the `parentspec`'s
        immediate children.

        Parameters
        ----------
        parentspec : str
            Text IOS configuration line
        childspec : str
            Text IOS configuration line, or regular expression
        replacestr : str
            Text IOS configuration, which should replace text matching ``childspec``.
        excludespec : str
            A regular expression, which indicates ``childspec`` lines which *must* be skipped.  If ``excludespec`` is None, no lines will be excluded.
        exactmatch : bool
            Defaults to False.  When set True, this option requires ``linespec`` match the whole configuration line, instead of a portion of the configuration line.

        Returns
        -------
        list
            A list of changed :class:`~models_cisco.IOSCfgLine` instances.

        Examples
        --------
        `replace_children()` just searches through a parent's child lines and
        replaces anything matching `childspec` with `replacestr`.  This method
        is one of my favorites for quick and dirty standardization efforts if
        you *know* the commands are already there (just set inconsistently).

        One very common use case is rewriting all vlan access numbers in a
        configuration.  The following example sets
        `storm-control broadcast level 0.5` on all GigabitEthernet ports.

        .. code-block:: python
           :emphasize-lines: 13

           >>> from ciscoconfparse import CiscoConfParse
           >>> config = ['!',
           ...           'interface GigabitEthernet1/1',
           ...           ' description {I have a broken storm-control config}',
           ...           ' switchport',
           ...           ' switchport mode access',
           ...           ' switchport access vlan 50',
           ...           ' switchport nonegotiate',
           ...           ' storm-control broadcast level 0.2',
           ...           '!'
           ...     ]
           >>> p = CiscoConfParse(config)
           >>> p.replace_children(r'^interface\sGigabit', r'broadcast\slevel\s\S+', 'broadcast level 0.5')
           [' storm-control broadcast level 0.5']
           >>>

        One thing to remember about the last example, you *cannot* use a
        regular expression in `replacestr`; just use a normal python string.
        """
        retval = list()
        ## Since we are replacing text, we *must* operate on ConfigObjs
        childspec_re = re.compile(childspec)
        if excludespec:
            excludespec_re = re.compile(excludespec)
        for pobj in self._find_line_OBJ(parentspec, exactmatch=exactmatch):
            if excludespec and excludespec_re.search(pobj.text):
                # Exclude replacements on pobj lines which match excludespec
                continue
            for cobj in pobj.children:
                if excludespec and excludespec_re.search(cobj.text):
                    # Exclude replacements on pobj lines which match excludespec
                    continue
                elif childspec_re.search(cobj.text):
                    retval.append(cobj.re_sub(childspec, replacestr))
                else:
                    pass

        if self.factory and atomic:
            # self.ConfigObjs._reassign_linenums()
            self.ConfigObjs._bootstrap_from_text()
        return retval

    def replace_all_children(
        self,
        parentspec,
        childspec,
        replacestr,
        excludespec=None,
        exactmatch=False,
        atomic=False,
    ):
        """Replace lines matching `childspec` within all children (recursive) of lines whilch match `parentspec`"""
        retval = list()
        ## Since we are replacing text, we *must* operate on ConfigObjs
        childspec_re = re.compile(childspec)
        if excludespec:
            excludespec_re = re.compile(excludespec)
        for pobj in self._find_line_OBJ(parentspec, exactmatch=exactmatch):
            if excludespec and excludespec_re.search(pobj.text):
                # Exclude replacements on pobj lines which match excludespec
                continue
            for cobj in self._find_all_child_OBJ(pobj):
                if excludespec and excludespec_re.search(cobj.text):
                    # Exclude replacements on pobj lines which match excludespec
                    continue
                elif childspec_re.search(cobj.text):
                    retval.append(cobj.re_sub(childspec, replacestr))
                else:
                    pass

        if self.factory and atomic:
            # self.ConfigObjs._reassign_linenums()
            self.ConfigObjs._bootstrap_from_text()

        return retval

    def re_search_children(self, regex, recurse=False):
        """Use ``regex`` to search for root parents in the config with text matching regex.  If `recurse` is False, only root parent objects are returned.  A list of matching objects is returned.

        This method is very similar to :func:`~ciscoconfparse.CiscoConfParse.find_objects` (when `recurse` is True); however it was written in response to the use-case described in `Github Issue #156 <https://github.com/mpenning/ciscoconfparse/issues/156>`_.

        Parameters
        ----------
        regex : str
            A string or python regular expression, which should be matched.
        recurse : bool
            Set True if you want to search all objects, and not just the root parents

        Returns
        -------
        list
            A list of matching :class:`~models_cisco.IOSCfgLine` objects which matched.  If there is no match, an empty :py:func:`list` is returned.

        """
        ## I implemented this method in response to Github issue #156
        if recurse is False:
            # Only return the matching oldest ancestor objects...
            return [obj for obj in self.find_objects(regex) if (obj.parent is obj)]
        else:
            # Return any matching object
            return [obj for obj in self.find_objects(regex)]

    def re_match_iter_typed(
        self, regex, group=1, result_type=str, default="", untyped_default=False
    ):
        r"""Use ``regex`` to search the root parents in the config
        and return the contents of the regular expression group, at the
        integer ``group`` index, cast as ``result_type``; if there is no
        match, ``default`` is returned.

        Notes
        -----
        Only the first regex match is returned.

        Parameters
        ----------
        regex : str
            A string or python compiled regular expression, which should be matched.  This regular expression should contain parenthesis, which bound a match group.
        group : int
            An integer which specifies the desired regex group to be returned.  ``group`` defaults to 1.
        result_type : type
            A type (typically one of: ``str``, ``int``, ``float``, or :class:`~ccp_util.IPv4Obj`).         All returned values are cast as ``result_type``, which defaults to ``str``.
        default : any
            The default value to be returned, if there is no match.  The default is an empty string.
        untyped_default : bool
            Set True if you don't want the default value to be typed

        Returns
        -------
        ``result_type``
            The text matched by the regular expression group; if there is no match, ``default`` is returned.  All values are cast as ``result_type``.  The default result_type is `str`.


        Examples
        --------
        This example illustrates how you can use
        :func:`~ciscoconfparse.re_match_iter_typed` to get the
        first interface name listed in the config.

        >>> import re
        >>> from ciscoconfparse import CiscoConfParse
        >>> config = [
        ...     '!',
        ...     'interface Serial1/0',
        ...     ' ip address 1.1.1.1 255.255.255.252',
        ...     '!',
        ...     'interface Serial2/0',
        ...     ' ip address 1.1.1.5 255.255.255.252',
        ...     '!',
        ...     ]
        >>> parse = CiscoConfParse(config)
        >>> parse.re_match_iter_typed(r'interface\s(\S+)')
        'Serial1/0'
        >>>

        The following example retrieves the hostname from the configuration

        >>> from ciscoconfparse import CiscoConfParse
        >>> config = [
        ...     '!',
        ...     'hostname DEN-EDGE-01',
        ...     '!',
        ...     'interface Serial1/0',
        ...     ' ip address 1.1.1.1 255.255.255.252',
        ...     '!',
        ...     'interface Serial2/0',
        ...     ' ip address 1.1.1.5 255.255.255.252',
        ...     '!',
        ...     ]
        >>> parse = CiscoConfParse(config)
        >>> parse.re_match_iter_typed(r'^hostname\s+(\S+)')
        'DEN-EDGE-01'
        >>>

        """
        ## iterate through root objects, and return the matching value
        ##  (cast as result_type) from the first object.text that matches regex

        # if (default is True):
        ## Not using self.re_match_iter_typed(default=True), because I want
        ##   to be sure I build the correct API for match=False
        ##
        ## Ref IOSIntfLine.has_dtp for an example of how to code around
        ##   this while I build the API
        #    raise NotImplementedError

        for cobj in self.ConfigObjs:

            # Only process parent objects at the root of the tree...
            if cobj.parent is not cobj:
                continue

            mm = re.search(regex, cobj.text)
            if (mm is not None):
                return result_type(mm.group(group))
        ## Ref Github issue #121
        if untyped_default:
            return default
        else:
            return result_type(default)

    def req_cfgspec_all_diff(self, cfgspec, ignore_ws=False):
        """
        req_cfgspec_all_diff takes a list of required configuration lines,
        parses through the configuration, and ensures that none of cfgspec's
        lines are missing from the configuration.  req_cfgspec_all_diff
        returns a list of missing lines from the config.

        One example use of this method is when you need to enforce routing
        protocol standards, or standards against interface configurations.

        Examples
        --------

        >>> from ciscoconfparse import CiscoConfParse
        >>> config = [
        ...     'logging trap debugging',
        ...     'logging 172.28.26.15',
        ...     ]
        >>> p = CiscoConfParse(config)
        >>> required_lines = [
        ...     "logging 172.28.26.15",
        ...     "logging 172.16.1.5",
        ...     ]
        >>> diffs = p.req_cfgspec_all_diff(required_lines)
        >>> diffs
        ['logging 172.16.1.5']
        >>>
        """

        rgx = dict()
        if ignore_ws:
            for line in cfgspec:
                rgx[line] = self._build_space_tolerant_regex(line)

        skip_cfgspec = dict()
        retval = list()
        matches = self._find_line_OBJ("[a-zA-Z]")
        ## Make a list of unnecessary cfgspec lines
        for lineobj in matches:
            for reqline in cfgspec:
                if ignore_ws:
                    if re.search(r"^" + rgx[reqline] + "$", lineobj.text.strip()):
                        skip_cfgspec[reqline] = True
                else:
                    if lineobj.text.strip() == reqline.strip():
                        skip_cfgspec[reqline] = True
        ## Add items to be configured
        ## TODO: Find a way to add the parent of the missing lines
        for line in cfgspec:
            if not skip_cfgspec.get(line, False):
                retval.append(line)

        return retval

    def req_cfgspec_excl_diff(self, linespec, uncfgspec, cfgspec):
        r"""
        req_cfgspec_excl_diff accepts a linespec, an unconfig spec, and
        a list of required configuration elements.  Return a list of
        configuration diffs to make the configuration comply.  **All** other
        config lines matching the linespec that are *not* listed in the
        cfgspec will be removed with the uncfgspec regex.

        Uses for this method include the need to enforce syslog, acl, or
        aaa standards.

        Examples
        --------

        >>> from ciscoconfparse import CiscoConfParse
        >>> config = [
        ...     'logging trap debugging',
        ...     'logging 172.28.26.15',
        ...     ]
        >>> p = CiscoConfParse(config)
        >>> required_lines = [
        ...     "logging 172.16.1.5",
        ...     "logging 1.10.20.30",
        ...     "logging 192.168.1.1",
        ...     ]
        >>> linespec = "logging\s+\d+\.\d+\.\d+\.\d+"
        >>> unconfspec = linespec
        >>> diffs = p.req_cfgspec_excl_diff(linespec, unconfspec,
        ...     required_lines)
        >>> diffs
        ['no logging 172.28.26.15', 'logging 172.16.1.5', 'logging 1.10.20.30', 'logging 192.168.1.1']
        >>>
        """
        violate_objs = list()
        uncfg_objs = list()
        skip_cfgspec = dict()
        retval = list()
        matches = self._find_line_OBJ(linespec)
        ## Make a list of lineobject violations
        for lineobj in matches:
            # Look for config lines to unconfigure
            accept_lineobj = False
            for reqline in cfgspec:
                if lineobj.text.strip() == reqline.strip():
                    accept_lineobj = True
                    skip_cfgspec[reqline] = True
            if accept_lineobj is False:
                # If a violation is found...
                violate_objs.append(lineobj)
                result = re.search(uncfgspec, lineobj.text)
                # add uncfgtext to the violator's lineobject
                lineobj.add_uncfgtext(result.group(0))
        ## Make the list of unconfig objects, recurse through parents
        for vobj in violate_objs:
            parent_objs = vobj.all_parents
            for parent_obj in parent_objs:
                uncfg_objs.append(parent_obj)
            uncfg_objs.append(vobj)
        retval = self._objects_to_uncfg(uncfg_objs, violate_objs)
        ## Add missing lines...
        ## TODO: Find a way to add the parent of the missing lines
        for line in cfgspec:
            if not skip_cfgspec.get(line, False):
                retval.append(line)

        return retval

    def _sequence_nonparent_lines(self, a_nonparent_objs, b_nonparent_objs):
        """Assume a_nonparent_objs is the existing config sequence, and
        b_nonparent_objs is the *desired* config sequence

        This method walks b_nonparent_objs, and orders a_nonparent_objs
        the same way (as much as possible)

        This method returns:

        - The reordered list of a_nonparent_objs
        - The reordered list of a_nonparent_lines
        - The reordered list of a_nonparent_linenums
        """
        a_parse = CiscoConfParse([])  # A *new* parse for reordered a lines
        a_lines = list()
        a_linenums = list()

        ## Mark all a objects as not done
        for aobj in a_nonparent_objs:
            aobj.done = False

        for bobj in b_nonparent_objs:
            for aobj in a_nonparent_objs:
                if aobj.text == bobj.text:
                    aobj.done = True
                    a_parse.append_line(aobj.text)

        # Add any missing a_parent_objs + their children...
        for aobj in a_nonparent_objs:
            if aobj.done is False:
                aobj.done = True
                a_parse.append_line(aobj.text)

        a_parse.commit()

        a_nonparents_reordered = a_parse.ConfigObjs
        for aobj in a_nonparents_reordered:
            a_lines.append(aobj.text)
            a_linenums.append(aobj.linenum)

        return a_parse, a_lines, a_linenums

    def _sequence_parent_lines(self, a_parent_objs, b_parent_objs):
        """Assume a_parent_objs is the existing config sequence, and
        b_parent_objs is the *desired* config sequence

        This method walks b_parent_objs, and orders a_parent_objs
        the same way (as much as possible)

        This method returns:

        - The reordered list of a_parent_objs
        - The reordered list of a_parent_lines
        - The reordered list of a_parent_linenums
        """
        a_parse = CiscoConfParse([])  # A *new* parse for reordered a lines
        a_lines = list()
        a_linenums = list()

        ## Mark all a objects as not done
        for aobj in a_parent_objs:
            aobj.done = False
            for child in aobj.all_children:
                child.done = False

        ## Walk the b objects by parent, then child and reorder a objects
        for bobj in b_parent_objs:

            for aobj in a_parent_objs:
                if aobj.text == bobj.text:
                    aobj.done = True
                    a_parse.append_line(aobj.text)

                    # Append *matching* children to this aobj in the same order
                    for bchild in bobj.all_children:
                        for achild in aobj.all_children:
                            if achild.done:
                                continue
                            elif achild.geneology_text == bchild.geneology_text:
                                achild.done = True
                                a_parse.append_line(achild.text)

                    # Append *missing* children to this aobj...
                    for achild in aobj.all_children:
                        if achild.done is False:
                            achild.done = True
                            a_parse.append_line(achild.text)

        # Add any missing a_parent_objs + their children...
        for aobj in a_parent_objs:
            if aobj.done is False:
                aobj.done = True
                a_parse.append_line(aobj.text)
                for achild in aobj.all_children:
                    achild.done = True
                    a_parse.append_line(achild.text)

        a_parse.commit()

        a_parents_reordered = a_parse.ConfigObjs
        for aobj in a_parents_reordered:
            a_lines.append(aobj.text)
            a_linenums.append(aobj.linenum)

        return a_parse, a_lines, a_linenums

    def sync_diff(
        self,
        cfgspec,
        linespec,
        uncfgspec=None,
        ignore_order=True,
        remove_lines=True,
        debug=0,
    ):
        r"""
        ``sync_diff()`` accepts a list of required configuration elements,
        a linespec, and an unconfig spec.  This method return a list of
        configuration diffs to make the configuration comply with cfgspec.

        Parameters
        ----------
        cfgspec : list
            A list of required configuration lines
        linespec : str
            A regular expression, which filters lines to be diff'd
        uncfgspec : str
            A regular expression, which is used to unconfigure lines.  When ciscoconfparse removes a line, it takes the entire portion of the line that matches ``uncfgspec``, and prepends "no" to it.
        ignore_order : bool
            Indicates whether the configuration should be reordered to minimize the number of diffs.  Default: True (usually it's a good idea to leave ``ignore_order`` True, except for ACL comparisions)
        remove_lines : bool
            Indicates whether the lines which are *not* in ``cfgspec`` should be removed.  Default: True.  When ``remove_lines`` is True, all other config lines matching the linespec that are *not* listed in the cfgspec will be removed with the uncfgspec regex.
        debug : int
            Miscellaneous debugging; Default: 0

        Returns
        -------
        list
            A list of string configuration diffs


        Uses for this method include the need to enforce syslog, acl, or
        aaa standards.

        Examples
        --------

        >>> from ciscoconfparse import CiscoConfParse
        >>> config = [
        ...     'logging trap debugging',
        ...     'logging 172.28.26.15',
        ...     ]
        >>> p = CiscoConfParse(config)
        >>> required_lines = [
        ...     "logging 172.16.1.5",
        ...     "logging 1.10.20.30",
        ...     "logging 192.168.1.1",
        ...     ]
        >>> linespec = "logging\s+\d+\.\d+\.\d+\.\d+"
        >>> unconfspec = linespec
        >>> diffs = p.sync_diff(required_lines,
        ...     linespec, unconfspec) # doctest: +SKIP
        >>> diffs                     # doctest: +SKIP
        ['no logging 172.28.26.15', 'logging 172.16.1.5', 'logging 1.10.20.30', 'logging 192.168.1.1']
        >>>
        """

        tmp = self._find_line_OBJ(linespec)
        if uncfgspec is None:
            uncfgspec = linespec
        a_lines = map(lambda x: x.text, tmp)
        a = CiscoConfParse(a_lines)

        b = CiscoConfParse(cfgspec, factory=False)
        b_lines = b.ioscfg

        a_hierarchy = list()
        b_hierarchy = list()

        ## Build heirarchical, equal-length lists of parents / non-parents
        a_parents, a_nonparents = a.ConfigObjs.config_hierarchy()
        b_parents, b_nonparents = b.ConfigObjs.config_hierarchy()

        obj = DiffObject(0, a_nonparents, a_parents)
        a_hierarchy.append(obj)

        obj = DiffObject(0, b_nonparents, b_parents)
        b_hierarchy.append(obj)

        retval = list()
        ## Assign config_this and unconfig_this attributes by "diff level"
        for adiff_level, bdiff_level in zip(a_hierarchy, b_hierarchy):
            for attr in ["parents", "nonparents"]:
                if attr == "parents":
                    if ignore_order:
                        a_parents = getattr(adiff_level, attr)
                        b_parents = getattr(bdiff_level, attr)

                        # Rewrite a, since we reordered everything
                        a, a_lines, a_linenums = self._sequence_parent_lines(
                            a_parents, b_parents
                        )
                    else:
                        a_lines = list()
                        a_linenums = list()
                        for obj in adiff_level.parents:
                            a_lines.append(obj.text)
                            a_linenums.append(obj.linenum)
                            a_lines.extend(
                                map(lambda x: getattr(x, "text"), obj.all_children)
                            )
                            a_linenums.extend(
                                map(lambda x: getattr(x, "linenum"), obj.all_children)
                            )
                    b_lines = list()
                    b_linenums = list()
                    for obj in bdiff_level.parents:
                        b_lines.append(obj.text)
                        b_linenums.append(obj.linenum)
                        b_lines.extend(
                            map(lambda x: getattr(x, "text"), obj.all_children)
                        )
                        b_linenums.extend(
                            map(lambda x: getattr(x, "linenum"), obj.all_children)
                        )
                else:
                    if ignore_order:
                        a_nonparents = getattr(adiff_level, attr)
                        b_nonparents = getattr(bdiff_level, attr)

                        # Rewrite a, since we reordered everything
                        a, a_lines, a_linenums = self._sequence_nonparent_lines(
                            a_nonparents, b_nonparents
                        )
                    else:
                        a_lines = map(
                            lambda x: getattr(x, "text"), getattr(adiff_level, attr)
                        )
                        # Build a map from a_lines index to a.ConfigObjs index
                        a_linenums = map(
                            lambda x: getattr(x, "linenum"), getattr(adiff_level, attr)
                        )
                    b_lines = map(
                        lambda x: getattr(x, "text"), getattr(bdiff_level, attr)
                    )
                    # Build a map from b_lines index to b.ConfigObjs index
                    b_linenums = map(
                        lambda x: getattr(x, "linenum"), getattr(bdiff_level, attr)
                    )

                ###
                ### Mark diffs here
                ###

                # Get a SequenceMatcher instance to calculate diffs at this level
                matcher = SequenceMatcher(isjunk=None, a=a_lines, b=b_lines)

                # Use the SequenceMatcher instance to label objects appropriately:
                #  - tag is the diff evaluation: equal, replace, insert, or delete
                #  - i1 and i2 are the begin and end points for arg a
                #  - j1 and j2 are the begin and end points for arg b
                for tag, i1, i2, j1, j2 in matcher.get_opcodes():
                    # print ("%7s a[%d:%d] (%s) b[%d:%d] (%s)" % (tag, i1, i2, a_lines[i1:i2], j1, j2, b_lines[j1:j2]))
                    if (debug > 0) or (self.debug > 0):
                        logger.debug("TAG='{0}'".format(tag))

                    # if tag=='equal', check whether the parent objs are the same
                    #     if parent objects are the same, then do nothing
                    #     if parent objects are different, then delete a & config b
                    # if tag=='replace'
                    #     delete a & config b
                    # if tag=='insert', then configure b
                    aobjs = list()  # List of a IOSCfgLine objects at this level
                    bobjs = list()  # List of b IOSCfgLine objects at this level
                    for num in range(i1, i2):
                        aobj = a.ConfigObjs[a_linenums[num]]
                        aobjs.append(aobj)
                    for num in range(j1, j2):
                        bobj = b.ConfigObjs[b_linenums[num]]
                        bobjs.append(bobj)

                    max_len = max(len(aobjs), len(bobjs))
                    for idx in range(0, max_len):
                        try:
                            aobj = aobjs[idx]
                            # set aparent_text to all parents' text (joined)
                            aparent_text = " ".join(
                                map(lambda x: x.text, aobj.all_parents)
                            )
                        except IndexError:
                            # aobj doesn't exist, if we get an index error
                            #    fake some data...
                            aobj = None
                            aparent_text = "__ANOTHING__"
                        if (debug > 0) or (self.debug > 0):
                            logger.debug("    aobj:'{0}'".format(aobj))
                            logger.debug("    aobj parents:'{0}'".format(aparent_text))

                        try:
                            bobj = bobjs[idx]
                            # set bparent_text to all parents' text (joined)
                            bparent_text = " ".join(
                                map(lambda x: x.text, bobj.all_parents)
                            )
                        except IndexError:
                            # bobj doesn't exist, if we get an index error
                            #    fake some data...
                            bobj = None
                            bparent_text = "__BNOTHING__"

                        if (debug > 0) or (self.debug > 0):
                            logger.debug("    bobj:'{0}'".format(bobj))
                            logger.debug("    bobj parents:'{0}'".format(bparent_text))

                        if tag == "equal":
                            # If the diff claims that these lines are equal, they
                            #   aren't truly equal unless parents match
                            if aparent_text != bparent_text:
                                if (debug > 0) or (self.debug > 0):
                                    logger.debug(
                                        "    tagged 'equal', aparent_text!=bparent_text"
                                    )
                                # a & b parents are *not* the same
                                #  therefore a & b are not equal
                                if aobj:
                                    # Only configure parent if it's not already
                                    #    slated for removal
                                    if not getattr(aobj.parent, "unconfig_this", False):
                                        aobj.parent.config_this = True
                                    aobj.unconfig_this = True
                                    if debug > 0:
                                        logger.debug("    unconfigure aobj")
                                if bobj:
                                    bobj.config_this = True
                                    bobj.parent.config_this = True
                                    if debug > 0:
                                        logger.debug("    configure bobj")
                            elif aparent_text == bparent_text:
                                # Both a & b parents match, so these lines are equal
                                aobj.unconfig_this = False
                                bobj.config_this = False
                                if debug > 0:
                                    logger.debug(
                                        "    tagged 'equal', aparent_text==bparent_text"
                                    )
                                    logger.debug("    do nothing with aobj / bobj")
                        elif tag == "replace":
                            # tag: replace, I'm not going to check parents for now
                            if debug > 0:
                                logger.debug("    tagged 'replace'")
                            if aobj:
                                # Only configure parent if it's not already
                                #    slated for removal
                                if not getattr(aobj.parent, "unconfig_this", False):
                                    aobj.parent.config_this = True
                                aobj.unconfig_this = True
                                if debug > 0:
                                    logger.debug("    unconfigure aobj")
                            if bobj:
                                bobj.config_this = True
                                bobj.parent.config_this = True
                                if debug > 0:
                                    logger.debug("    configure bobj")
                        elif tag == "insert":
                            if debug > 0:
                                logger.debug("    tagged 'insert'")
                            # I don't think tag: insert ever applies to a objects...
                            if aobj:
                                # Only configure parent if it's not already
                                #    slated for removal
                                if not getattr(aobj.parent, "unconfig_this", False):
                                    aobj.parent.config_this = True
                                aobj.unconfig_this = True
                                if debug > 0:
                                    logger.debug("    unconfigure aobj")
                            # tag: insert certainly applies to b objects...
                            if bobj:
                                bobj.config_this = True
                                bobj.parent.config_this = True
                                if debug > 0:
                                    logger.debug("    configure bobj")
                        elif tag == "delete":
                            # NOTE: I'm not deleting b objects, for now
                            if debug > 0:
                                logger.debug("    tagged 'delete'")
                            if aobj:
                                # Only configure parent if it's not already
                                #    slated for removal
                                for pobj in aobj.all_parents:
                                    if not getattr(pobj, "unconfig_this", False):
                                        pobj.config_this = True
                                aobj.unconfig_this = True
                                if debug > 0:
                                    logger.debug("    unconfigure aobj")
                        else:
                            error = "Unknown action: {0}".format(tag)
                            logger.error(error)
                            raise ValueError(error)

                ###
                ### Write a object diffs here
                ###

                ## Unconfigure A objects, at *each level*, as required
                for obj in a.ConfigObjs:
                    if remove_lines and getattr(obj, "unconfig_this", False):
                        ## FIXME: This should only be applied to IOS and ASA configs
                        if uncfgspec:
                            mm = re.search(uncfgspec, obj.text)
                            if (mm is not None):
                                obj.add_uncfgtext(mm.group(0))
                                retval.append(obj.uncfgtext)
                            else:
                                retval.append(
                                    " " * obj.indent + "no " + obj.text.lstrip()
                                )
                        else:
                            retval.append(" " * obj.indent + "no " + obj.text.lstrip())
                    elif remove_lines and getattr(obj, "config_this", False):
                        retval.append(obj.text)

                    # Clean up the attributes we used temporarily in this method
                    for attr in ["config_this", "unconfig_this"]:
                        try:
                            delattr(obj.text, attr)
                        except:
                            pass

        ###
        ### Write b object diffs here
        ###
        for obj in b.ConfigObjs:
            if getattr(obj, "config_this", False):
                retval.append(obj.text)

            # Clean up the attributes we used temporarily in this method
            try:
                delattr(obj.text, "config_this")
            except:
                pass

        ## Strip out 'double negatives' (i.e. 'no no ')
        for idx in range(0, len(retval)):
            retval[idx] = re.sub(
                r"(\s+)no\s+no\s+(\S+.+?)$", r"\g<1>\g<2>", retval[idx]
            )

        if debug > 0:
            logger.debug("Completed diff:")
            for line in retval:
                logger.debug("'{0}'".format(line))
        return retval

    def save_as(self, filepath):
        """Save a text copy of the configuration at ``filepath``; this
        method uses the OperatingSystem's native line separators (such as
        ``\\r\\n`` in Windows)."""
        try:
            with open(filepath, "w") as newconf:
                for line in self.ioscfg:
                    newconf.write(line + "\n")
            return True
        except Exception as e:
            logger.error(str(e))
            raise e

    ### The methods below are marked SEMI-PRIVATE because they return an object
    ###  or iterable of objects instead of the configuration text itself.
    def _build_space_tolerant_regex(self, linespec):
        r"""SEMI-PRIVATE: Accept a string, and return a string with all
        spaces replaced with '\s+'"""

        # Unicode below...
        backslash = "\x5c"
        # escaped_space = "\\s+" (not a raw string)
        if sys.version_info >= (
            3,
            0,
            0,
        ):
            escaped_space = (backslash + backslash + "s+").translate("utf-8")
        else:
            escaped_space = backslash + backslash + "s+"

        LINESPEC_LIST_TYPE = bool(getattr(linespec, "append", False))

        if not LINESPEC_LIST_TYPE:
            assert bool(getattr(linespec, "upper", False))  # Ensure it's a str
            linespec = re.sub(r"\s+", escaped_space, linespec)
        else:
            for idx in range(0, len(linespec)):
                ## Ensure this element is a string
                assert bool(getattr(linespec[idx], "upper", False))
                linespec[idx] = re.sub(r"\s+", escaped_space, linespec[idx])

        return linespec

    def _find_line_OBJ(self, linespec, exactmatch=False):
        """SEMI-PRIVATE: Find objects whose text matches the linespec"""
        ## NOTE TO SELF: do not remove _find_line_OBJ(); used by Cisco employees
        if not exactmatch:
            # Return objects whose text attribute matches linespec
            linespec_re = re.compile(linespec)
        elif exactmatch:
            # Return objects whose text attribute matches linespec exactly
            linespec_re = re.compile("^%s$" % linespec)
        return list(filter(lambda obj: linespec_re.search(obj.text), self.ConfigObjs))

    def _find_sibling_OBJ(self, lineobject):
        """SEMI-PRIVATE: Takes a singe object and returns a list of sibling
        objects"""
        siblings = lineobject.parent.children
        return siblings

    def _find_all_child_OBJ(self, lineobject):
        """SEMI-PRIVATE: Takes a single object and returns a list of
        decendants in all 'children' / 'grandchildren' / etc... after it.
        It should NOT return the children of siblings"""
        # sort the list, and get unique objects
        retval = set(lineobject.children)
        for candidate in lineobject.children:
            if candidate.has_children:
                for child in candidate.children:
                    retval.add(child)
        retval = sorted(retval)
        return retval

    def _unique_OBJ(self, objectlist):
        """SEMI-PRIVATE: Returns a list of unique objects (i.e. with no
        duplicates).
        The returned value is sorted by configuration line number
        (lowest first)"""
        retval = set([])
        for obj in objectlist:
            retval.add(obj)
        return sorted(retval)

    def _objects_to_uncfg(self, objectlist, unconflist):
        # Used by req_cfgspec_excl_diff()
        retval = list()
        unconfdict = dict()
        for unconf in unconflist:
            unconfdict[unconf] = "DEFINED"
        for obj in self._unique_OBJ(objectlist):
            if unconfdict.get(obj, None) == "DEFINED":
                retval.append(obj.uncfgtext)
            else:
                retval.append(obj.text)
        return retval


#########################################################################3


class IOSConfigList(MutableSequence):
    """A custom list to hold :class:`~models_cisco.IOSCfgLine` objects.  Most people will never need to use this class directly."""

    def __init__(
        self,
        data=None,
        comment_delimiter="!",
        debug=0,
        factory=False,
        ignore_blank_lines=True,
        syntax="ios",
        CiscoConfParse=None,
    ):
        """Initialize the class.

        Parameters
        ----------
        data : list
            A list of parsed :class:`~models_cisco.IOSCfgLine` objects
        comment_delimiter : str
            A comment delimiter.  This should only be changed when parsing non-Cisco IOS configurations, which do not use a !  as the comment delimiter.  ``comment`` defaults to '!'
        debug : int
            ``debug`` defaults to 0, and should be kept that way unless you're working on a very tricky config parsing problem.  Debug output is not particularly friendly
        ignore_blank_lines : bool
            ``ignore_blank_lines`` defaults to True; when this is set True, ciscoconfparse ignores blank configuration lines.  You might want to set ``ignore_blank_lines`` to False if you intentionally use blank lines in your configuration (ref: Github Issue #2).

        Returns
        -------
        An instance of an :class:`~ciscoconfparse.IOSConfigList` object.

        """
        # data = kwargs.get('data', None)
        # comment_delimiter = kwargs.get('comment_delimiter', '!')
        # debug = kwargs.get('debug', False)
        # factory = kwargs.get('factory', False)
        # ignore_blank_lines = kwargs.get('ignore_blank_lines', True)
        # syntax = kwargs.get('syntax', 'ios')
        # CiscoConfParse = kwargs.get('CiscoConfParse', None)
        super(IOSConfigList, self).__init__()

        self._list = list()
        self.CiscoConfParse = CiscoConfParse
        self.comment_delimiter = comment_delimiter
        self.factory = factory
        self.ignore_blank_lines = ignore_blank_lines
        self.syntax = syntax
        self.dna = "IOSConfigList"
        self.debug = debug

        ## Support either a list or a generator instance
        if getattr(data, "__iter__", False):
            self._list = self._bootstrap_obj_init(data)
        else:
            self._list = list()

    def __len__(self):
        return len(self._list)

    def __getitem__(self, ii):
        return self._list[ii]

    def __delitem__(self, ii):
        del self._list[ii]
        self._bootstrap_from_text()

    def __setitem__(self, ii, val):
        return self._list[ii]

    def __str__(self):
        return self.__repr__()

    def __enter__(self):
        # Add support for with statements...
        # FIXME: *with* statements dont work
        for obj in self._list:
            yield obj

    def __exit__(self, *args, **kwargs):
        # FIXME: *with* statements dont work
        self._list[0].confobj.CiscoConfParse.atomic()

    def __repr__(self):
        return """<IOSConfigList, comment='%s', conf=%s>""" % (
            self.comment_delimiter,
            self._list,
        )

    def _bootstrap_from_text(self):
        ## reparse all objects from their text attributes... this is *very* slow
        ## Ultimate goal: get rid of all reparsing from text...
        self._list = self._bootstrap_obj_init(list(map(attrgetter("text"), self._list)))
        if self.debug > 0:
            logger.debug("self._list = {0}".format(self._list))

    def has_line_with(self, linespec):
        return bool(filter(methodcaller("re_search", linespec), self._list))

    @junos_unsupported
    def insert_before(self, exist_val, new_val, atomic=False):
        """
        Insert new_val before all occurances of exist_val.

        Parameters
        ----------
        exist_val : str
            An existing text value.  This may match multiple configuration entries.
        new_val : str
            A new value to be inserted in the configuration.
        atomic : bool
            A boolean that controls whether the config is reparsed after the insertion (default False)

        Returns
        -------
        list
            An ios-style configuration list (indented by stop_width for each configuration level).

        Examples
        --------

        >>> parse = CiscoConfParse(["a", "b", "c", "b"])
        >>> # Insert 'g' before any occurance of 'b'
        >>> retval = parse.insert_before("b", "g")
        >>> parse.commit()
        >>> parse.ioscfg
        ... ["a", "g", "b", "c", "g", "b"]
        >>>
        """

        calling_fn_index = 1
        calling_filename = inspect.stack()[calling_fn_index].filename
        calling_function = inspect.stack()[calling_fn_index].function
        calling_lineno = inspect.stack()[calling_fn_index].lineno
        error =  "FATAL CALL: in %s line %s %s(exist_val='%s', new_val='%s')" % (calling_filename, calling_lineno, calling_function, exist_val, new_val)
        # exist_val MUST be a string
        if isinstance(exist_val, str) is True:
            pass

        elif isinstance(exist_val, IOSCfgLine) is True:
            exist_val = exist_val.text

        else:
            raise ValueError(error)

        # new_val MUST be a string
        if isinstance(new_val, str) is True:
            pass

        elif isinstance(new_val, IOSCfgLine) is True:
            new_val = new_val.text

        else:
            raise ValueError(error)

        if self.factory:
            new_obj = ConfigLineFactory(
                text=new_val,
                comment_delimiter=self.comment_delimiter,
                syntax=self.syntax,
            )
        elif self.syntax == "ios":
            new_obj = IOSCfgLine(text=new_val, comment_delimiter=self.comment_delimiter)

        # Find all config lines which need to be modified... store in all_idx
        all_idx = [idx for idx, val in enumerate(self._list) if val.text==exist_val]
        for idx in sorted(all_idx, reverse=True):
            self._list.insert(idx, new_obj)

        if atomic:
            # Reparse the whole config as a text list
            self._bootstrap_from_text()
        else:
            ## Just renumber lines...
            self._reassign_linenums()

####################################################################new mod
    @junos_unsupported
    def insert_after(self, exist_val, new_val, atomic=False):
        """
        Insert new_val after all occurances of exist_val.

        Parameters
        ----------
        exist_val : str
            An existing text value.  This may match multiple configuration entries.
        new_val : str
            A new value to be inserted in the configuration.
        atomic : bool
            A boolean that controls whether the config is reparsed after the insertion (default False)

        Returns
        -------
        list
            An ios-style configuration list (indented by stop_width for each configuration level).

        Examples
        --------

        >>> parse = CiscoConfParse(["a", "b", "c", "b"])
        >>> # Insert 'g' after any occurance of 'b'
        >>> retval = parse.insert_after("b", "g")
        >>> parse.commit()
        >>> parse.ioscfg
        ... ["a", "b", "g", "c", "b", "g"]
        >>>
        """

        calling_fn_index = 1
        calling_filename = inspect.stack()[calling_fn_index].filename
        calling_function = inspect.stack()[calling_fn_index].function
        calling_lineno = inspect.stack()[calling_fn_index].lineno
        error =  "FATAL CALL: in %s line %s %s(exist_val='%s', new_val='%s')" % (calling_filename, calling_lineno, calling_function, exist_val, new_val)
        # exist_val MUST be a string
        if isinstance(exist_val, str) is True:
            pass

        elif isinstance(exist_val, IOSCfgLine) is True:
            exist_val = exist_val.text

        else:
            raise ValueError(error)

        # new_val MUST be a string
        if isinstance(new_val, str) is True:
            pass

        elif isinstance(new_val, IOSCfgLine) is True:
            new_val = new_val.text

        else:
            raise ValueError(error)

        if self.factory:
            new_obj = ConfigLineFactory(
                text=new_val,
                comment_delimiter=self.comment_delimiter,
                syntax=self.syntax,
            )
        elif self.syntax == "ios":
            new_obj = IOSCfgLine(text=new_val, comment_delimiter=self.comment_delimiter)

        # Find all config lines which need to be modified... store in all_idx
        all_idx = [idx for idx, val in enumerate(self._list) if val.text==exist_val]
        for idx in sorted(all_idx, reverse=True):
            self._list.insert(idx+1, new_obj)

        if atomic:
            # Reparse the whole config as a text list
            self._bootstrap_from_text()
        else:
            ## Just renumber lines...
            self._reassign_linenums()
####################################################################new mod

#    @junos_unsupported
#    def insert_after(self, robj, val, atomic=False):
#        ## Insert something after robj
#        if getattr(robj, "capitalize", False):
#            raise ValueError
#
#        ## If val is a string...
#        if getattr(val, "capitalize", False):
#            if self.factory:
#                obj = ConfigLineFactory(
#                    text=val,
#                    comment_delimiter=self.comment_delimiter,
#                    syntax=self.syntax,
#                )
#            elif self.syntax == "ios":
#                obj = IOSCfgLine(text=val, comment_delimiter=self.comment_delimiter)
#
#        ## FIXME: This shouldn't be required
#        ## Removed 2015-01-24 during rewrite...
#        # self._reassign_linenums()
#
#        ii = self._list.index(robj)
#        if (ii is not None):
#            ## Do insertion here
#            self._list.insert(ii + 1, obj)
#
#        if atomic:
#            # Reparse the whole config as a text list
#            self._bootstrap_from_text()
#        else:
#            ## Just renumber lines...
#            self._reassign_linenums()

    @junos_unsupported
    def insert(self, ii, val):
        if getattr(val, "capitalize", False):
            if self.factory:
                obj = ConfigLineFactory(
                    text=val,
                    comment_delimiter=self.comment_delimiter,
                    syntax=self.syntax,
                )
            elif self.syntax == "ios":
                obj = IOSCfgLine(text=val, comment_delimiter=self.comment_delimiter)
            else:
                error = 'insert() cannot insert "{0}"'.format(val)
                logger.error(error)
                raise ValueError(error)
        else:
            error = 'insert() cannot insert "{0}"'.format(val)
            logger.error(error)
            raise ValueError(error)

        ## Insert something at index ii
        self._list.insert(ii, obj)

        ## Just renumber lines...
        self._reassign_linenums()

    @junos_unsupported
    def append(self, val):
        list_idx = len(self._list)
        self.insert(list_idx, val)

    def config_hierarchy(self):
        """Walk this configuration and return the following tuple
        at each parent 'level': (list_of_parent_sibling_objs, list_of_nonparent_sibling_objs)

        """
        parent_siblings = list()
        nonparent_siblings = list()

        for obj in self.CiscoConfParse.find_objects(r"^\S+"):
            if obj.is_comment:
                continue
            elif len(obj.children) == 0:
                nonparent_siblings.append(obj)
            else:
                parent_siblings.append(obj)

        return parent_siblings, nonparent_siblings

    def _banner_mark_regex(self, REGEX):
        # Build a list of all leading banner lines
        banner_objs = list(filter(lambda obj: REGEX.search(obj.text), self._list))

        BANNER_STR_RE = r"^(?:(?P<btype>(?:set\s+)*banner\s\w+\s+)(?P<bchar>\S))"
        for parent in banner_objs:
            parent.oldest_ancestor = True

            ## Parse out the banner type and delimiting banner character
            mm = re.search(BANNER_STR_RE, parent.text)
            if (mm is not None):
                mm_results = mm.groupdict()
                (banner_lead, bannerdelimit) = (
                    mm_results["btype"].rstrip(),
                    mm_results["bchar"],
                )
            else:
                (banner_lead, bannerdelimit) = ("", None)

            if self.debug > 0:
                logger.debug("banner_lead = '{0}'".format(banner_lead))
                logger.debug("bannerdelimit = '{0}'".format(bannerdelimit))
                logger.debug(
                    "{0} starts at line {1}".format(banner_lead, parent.linenum)
                )

            idx = parent.linenum
            while not (bannerdelimit is None):
                ## Check whether the banner line has both begin and end delimter
                if idx == parent.linenum:
                    parts = parent.text.split(bannerdelimit)
                    if len(parts) > 2:
                        ## banner has both begin and end delimiter on one line
                        if self.debug > 0:
                            logger.debug(
                                "{0} ends at line"
                                " {1}".format(banner_lead, parent.linenum)
                            )
                        break

                ## Use code below to identify children of the banner line
                idx += 1
                try:
                    obj = self._list[idx]
                    if obj.text is None:
                        if self.debug > 0:
                            logger.warning(
                                "found empty text while parsing '{0}' in the banner".format(
                                    obj
                                )
                            )
                        pass
                    elif bannerdelimit in obj.text.strip():
                        if self.debug > 0:
                            logger.debug(
                                "{0} ends at line"
                                " {1}".format(banner_lead, obj.linenum)
                            )
                        parent.children.append(obj)
                        parent.child_indent = 0
                        obj.parent = parent
                        break
                    # Commenting the following lines out; fix Github issue #115
                    # elif obj.is_comment and (obj.indent == 0):
                    #    break
                    parent.children.append(obj)
                    parent.child_indent = 0
                    obj.parent = parent
                except IndexError:
                    break

    def _macro_mark_children(self, macro_parent_idx_list):
        # Mark macro children appropriately...
        for idx in macro_parent_idx_list:
            pobj = self._list[idx]
            pobj.child_indent = 0

            # Walk the next configuration lines looking for the macro's children
            finished = False
            while not finished:
                idx += 1
                cobj = self._list[idx]
                cobj.parent = pobj
                pobj.children.append(cobj)
                # If we hit the end of the macro, break out of the loop
                if cobj.text.rstrip() == "@":
                    finished = True

    def _bootstrap_obj_init(self, text_list):
        """Accept a text list and format into proper IOSCfgLine() objects"""
        # Append text lines as IOSCfgLine objects...
        BANNER_STR = set(
            [
                "login",
                "motd",
                "incoming",
                "exec",
                "telnet",
                "lcd",
            ]
        )
        BANNER_ALL = [r"^(set\s+)*banner\s+{0}".format(ii) for ii in BANNER_STR]
        BANNER_ALL.append("aaa authentication fail-message")  # Github issue #76
        BANNER_RE = re.compile("|".join(BANNER_ALL))

        retval = list()
        idx = 0

        max_indent = 0
        macro_parent_idx_list = list()
        parents = dict()
        for line in text_list:
            # Reject empty lines if ignore_blank_lines...
            if self.ignore_blank_lines and line.strip() == "":
                continue
            #
            if not self.factory:
                obj = IOSCfgLine(line, self.comment_delimiter)
            elif self.syntax == "ios":
                obj = ConfigLineFactory(line, self.comment_delimiter, syntax="ios")
            else:
                error = ("Cannot classify config list item '%s' " 
                    "into a proper configuration object line" % line)
                if self.debug > 0:
                    logger.error(error)
                raise ValueError(error)

            obj.confobj = self
            obj.linenum = idx
            indent = len(line) - len(line.lstrip())
            obj.indent = indent

            is_config_line = obj.is_config_line

            # list out macro parent line numbers...
            if obj.text[0:11] == "macro name ":
                macro_parent_idx_list.append(obj.linenum)

            ## Parent cache:
            ## Maintain indent vs max_indent in a family and
            ##     cache the parent until indent<max_indent
            if (indent < max_indent) and is_config_line:
                parent = None
                # walk parents and intelligently prune stale parents
                stale_parent_idxs = filter(
                    lambda ii: ii >= indent, sorted(parents.keys(), reverse=True)
                )
                for parent_idx in stale_parent_idxs:
                    del parents[parent_idx]
            else:
                ## As long as the child indent hasn't gone backwards,
                ##    we can use a cached parent
                parent = parents.get(indent, None)

            ## If indented, walk backwards and find the parent...
            ## 1.  Assign parent to the child
            ## 2.  Assign child to the parent
            ## 3.  Assign parent's child_indent
            ## 4.  Maintain oldest_ancestor
            if (indent > 0) and not (parent is None):
                ## Add the line as a child (parent was cached)
                self._add_child_to_parent(retval, idx, indent, parent, obj)
            elif (indent > 0) and (parent is None):
                ## Walk backwards to find parent, and add the line as a child
                candidate_parent_index = idx - 1
                while candidate_parent_index >= 0:
                    candidate_parent = retval[candidate_parent_index]
                    if (
                        candidate_parent.indent < indent
                    ) and candidate_parent.is_config_line:
                        # We found the parent
                        parent = candidate_parent
                        parents[indent] = parent  # Cache the parent
                        if indent == 0:
                            parent.oldest_ancestor = True
                        break
                    else:
                        candidate_parent_index -= 1

                ## Add the line as a child...
                self._add_child_to_parent(retval, idx, indent, parent, obj)

            ## Handle max_indent
            if (indent == 0) and is_config_line:
                # only do this if it's a config line...
                max_indent = 0
            elif indent > max_indent:
                max_indent = indent

            retval.append(obj)
            idx += 1

        self._list = retval
        self._banner_mark_regex(BANNER_RE)
        # We need to use a different method for macros than banners because
        #   macros don't specify a delimiter on their parent line, but
        #   banners call out a delimiter.
        self._macro_mark_children(macro_parent_idx_list)  # Process macros
        return retval

    def _add_child_to_parent(self, _list, idx, indent, parentobj, childobj):
        ## parentobj could be None when trying to add a child that should not
        ##    have a parent
        if parentobj is None:
            if self.debug > 0:
                logger.debug("parentobj is None")
            return

        if self.debug > 0:
            # logger.debug("Adding child '{0}' to parent"
            #    " '{1}'".format(childobj, parentobj))
            # logger.debug("BEFORE parent.children - {0}"
            #    .format(parentobj.children))
            pass
        if childobj.is_comment and (_list[idx - 1].indent > indent):
            ## I *really* hate making this exception, but legacy
            ##   ciscoconfparse never marked a comment as a child
            ##   when the line immediately above it was indented more
            ##   than the comment line
            pass
        elif childobj.parent is childobj:
            # Child has not been assigned yet
            parentobj.children.append(childobj)
            childobj.parent = parentobj
            childobj.parent.child_indent = indent
        else:
            pass

        if self.debug > 0:
            # logger.debug("     AFTER parent.children - {0}"
            #    .format(parentobj.children))
            pass

    def iter_with_comments(self, begin_index=0):
        for idx, obj in enumerate(self._list):
            if idx >= begin_index:
                yield obj

    def iter_no_comments(self, begin_index=0):
        for idx, obj in enumerate(self._list):
            if (idx >= begin_index) and (not obj.is_comment):
                yield obj

    def _reassign_linenums(self):
        # Call this after any insertion or deletion
        for idx, obj in enumerate(self._list):
            obj.linenum = idx

    @property
    def all_parents(self):
        return [obj for obj in self._list if obj.has_children]

    @property
    def last_index(self):
        return self.__len__() - 1


#########################################################################3


class NXOSConfigList(MutableSequence):
    """A custom list to hold :class:`~models_nxos.NXOSCfgLine` objects.  Most people will never need to use this class directly."""

    def __init__(
        self,
        data=None,
        comment_delimiter="!",
        debug=0,
        factory=False,
        ignore_blank_lines=True,
        syntax="nxos",
        CiscoConfParse=None,
    ):
        """Initialize the class.

        Parameters
        ----------
        data : list
            A list of parsed :class:`~models_cisco.IOSCfgLine` objects
        comment_delimiter : str
            A comment delimiter.  This should only be changed when parsing non-Cisco IOS configurations, which do not use a !  as the comment delimiter.  ``comment`` defaults to '!'
        debug : int
            ``debug`` defaults to 0, and should be kept that way unless you're working on a very tricky config parsing problem.  Debug output is not particularly friendly
        ignore_blank_lines : bool
            ``ignore_blank_lines`` defaults to True; when this is set True, ciscoconfparse ignores blank configuration lines.  You might want to set ``ignore_blank_lines`` to False if you intentionally use blank lines in your configuration (ref: Github Issue #2).

        Returns
        -------
        An instance of an :class:`~ciscoconfparse.NXOSConfigList` object.

        """
        # data = kwargs.get('data', None)
        # comment_delimiter = kwargs.get('comment_delimiter', '!')
        # debug = kwargs.get('debug', False)
        # factory = kwargs.get('factory', False)
        # ignore_blank_lines = kwargs.get('ignore_blank_lines', True)
        # syntax = kwargs.get('syntax', 'nxos')
        # CiscoConfParse = kwargs.get('CiscoConfParse', None)
        super(NXOSConfigList, self).__init__()

        self._list = list()
        self.CiscoConfParse = CiscoConfParse
        self.comment_delimiter = comment_delimiter
        self.factory = factory
        self.ignore_blank_lines = ignore_blank_lines
        self.syntax = syntax
        self.dna = "NXOSConfigList"
        self.debug = debug

        ## Support either a list or a generator instance
        if getattr(data, "__iter__", False):
            self._list = self._bootstrap_obj_init(data)
        else:
            self._list = list()

    def __len__(self):
        return len(self._list)

    def __getitem__(self, ii):
        return self._list[ii]

    def __delitem__(self, ii):
        del self._list[ii]
        self._bootstrap_from_text()

    def __setitem__(self, ii, val):
        return self._list[ii]

    def __str__(self):
        return self.__repr__()

    def __enter__(self):
        # Add support for with statements...
        # FIXME: *with* statements dont work
        for obj in self._list:
            yield obj

    def __exit__(self, *args, **kwargs):
        # FIXME: *with* statements dont work
        self._list[0].confobj.CiscoConfParse.atomic()

    def __repr__(self):
        return """<NXOSConfigList, comment='%s', conf=%s>""" % (
            self.comment_delimiter,
            self._list,
        )

    def _bootstrap_from_text(self):
        ## reparse all objects from their text attributes... this is *very* slow
        ## Ultimate goal: get rid of all reparsing from text...
        self._list = self._bootstrap_obj_init(list(map(attrgetter("text"), self._list)))
        if self.debug > 0:
            logger.debug("self._list = {0}".format(self._list))

    def has_line_with(self, linespec):
        return bool(filter(methodcaller("re_search", linespec), self._list))

    def insert_before(self, robj, val, atomic=False):
        ## Insert something before robj
        if getattr(robj, "capitalize", False):
            # robj must not be a string...
            raise ValueError

        if getattr(val, "capitalize", False):
            if self.factory:
                obj = ConfigLineFactory(
                    text=val,
                    comment_delimiter=self.comment_delimiter,
                    syntax=self.syntax,
                )
            elif self.syntax == "nxos":
                obj = NXOSCfgLine(text=val, comment_delimiter=self.comment_delimiter)

        ii = self._list.index(robj)
        if (ii is not None):
            ## Do insertion here
            self._list.insert(ii, obj)

        if atomic:
            # Reparse the whole config as a text list
            self._bootstrap_from_text()
        else:
            ## Just renumber lines...
            self._reassign_linenums()

    def insert_after(self, robj, val, atomic=False):
        ## Insert something after robj
        if getattr(robj, "capitalize", False):
            raise ValueError

        ## If val is a string...
        if getattr(val, "capitalize", False):
            if self.factory:
                obj = ConfigLineFactory(
                    text=val,
                    comment_delimiter=self.comment_delimiter,
                    syntax=self.syntax,
                )
            elif self.syntax == "nxos":
                obj = NXOSCfgLine(text=val, comment_delimiter=self.comment_delimiter)

        ## FIXME: This shouldn't be required
        ## Removed 2015-01-24 during rewrite...
        # self._reassign_linenums()

        ii = self._list.index(robj)
        if (ii is not None):
            ## Do insertion here
            self._list.insert(ii + 1, obj)

        if atomic:
            # Reparse the whole config as a text list
            self._bootstrap_from_text()
        else:
            ## Just renumber lines...
            self._reassign_linenums()

    def insert(self, ii, val):
        if getattr(val, "capitalize", False):
            if self.factory:
                obj = ConfigLineFactory(
                    text=val,
                    comment_delimiter=self.comment_delimiter,
                    syntax=self.syntax,
                )
            elif self.syntax == "nxos":
                obj = NXOSCfgLine(text=val, comment_delimiter=self.comment_delimiter)
            else:
                error = 'insert() cannot insert "{0}"'.format(val)
                logger.error(error)
                raise ValueError(error)
        else:
            error = 'insert() cannot insert "{0}"'.format(val)
            logger.error(error)
            raise ValueError(error)

        ## Insert something at index ii
        self._list.insert(ii, obj)

        ## Just renumber lines...
        self._reassign_linenums()

    def append(self, val):
        list_idx = len(self._list)
        self.insert(list_idx, val)

    def config_hierarchy(self):
        """Walk this configuration and return the following tuple
        at each parent 'level':
            (list_of_parent_sibling_objs, list_of_nonparent_sibling_objs)
        """
        parent_siblings = list()
        nonparent_siblings = list()

        for obj in self.CiscoConfParse.find_objects(r"^\S+"):
            if obj.is_comment:
                continue
            elif len(obj.children) == 0:
                nonparent_siblings.append(obj)
            else:
                parent_siblings.append(obj)

        return parent_siblings, nonparent_siblings

    def _banner_mark_regex(self, REGEX):
        # Build a list of all leading banner lines
        banner_objs = list(filter(lambda obj: REGEX.search(obj.text), self._list))

        BANNER_STR_RE = r"^(?:(?P<btype>(?:set\s+)*banner\s\w+\s+)(?P<bchar>\S))"
        for parent in banner_objs:
            parent.oldest_ancestor = True

            ## Parse out the banner type and delimiting banner character
            mm = re.search(BANNER_STR_RE, parent.text)
            if (mm is not None):
                mm_results = mm.groupdict()
                (banner_lead, bannerdelimit) = (
                    mm_results["btype"].rstrip(),
                    mm_results["bchar"],
                )
            else:
                (banner_lead, bannerdelimit) = ("", None)

            if self.debug > 0:
                logger.debug("banner_lead = '{0}'".format(banner_lead))
                logger.debug("bannerdelimit = '{0}'".format(bannerdelimit))
                logger.debug(
                    "{0} starts at line {1}".format(banner_lead, parent.linenum)
                )

            idx = parent.linenum
            while not (bannerdelimit is None):
                ## Check whether the banner line has both begin and end delimter
                if idx == parent.linenum:
                    parts = parent.text.split(bannerdelimit)
                    if len(parts) > 2:
                        ## banner has both begin and end delimiter on one line
                        if self.debug > 0:
                            logger.debug(
                                "{0} ends at line"
                                " {1}".format(banner_lead, parent.linenum)
                            )
                        break

                idx += 1
                try:
                    obj = self._list[idx]
                    if obj.text is None:
                        if self.debug > 0:
                            logger.warning(
                                "found empty text while parsing '{0}' in the banner".format(
                                    obj
                                )
                            )
                        pass
                    elif bannerdelimit in obj.text.strip():
                        if self.debug > 0:
                            logger.debug(
                                "{0} ends at line"
                                " {1}".format(banner_lead, obj.linenum)
                            )
                        parent.children.append(obj)
                        parent.child_indent = 0
                        obj.parent = parent
                        break

                    ## Fix Github issue #75 I don't think this case is reqd now
                    # elif obj.is_comment and (obj.indent == 0):
                    #    break

                    parent.children.append(obj)
                    parent.child_indent = 0
                    obj.parent = parent
                except IndexError:
                    break

    def _bootstrap_obj_init(self, text_list):
        """Accept a text list and format into proper objects"""
        # Append text lines as NXOSCfgLine objects...
        BANNER_STR = set(
            [
                "login",
                "motd",
                "incoming",
                "exec",
                "telnet",
                "lcd",
            ]
        )
        BANNER_RE = re.compile(
            "|".join([r"^(set\s+)*banner\s+{0}".format(ii) for ii in BANNER_STR])
        )
        retval = list()
        idx = 0

        max_indent = 0
        parents = dict()
        for line in text_list:
            # Reject empty lines if ignore_blank_lines...
            if self.ignore_blank_lines and line.strip() == "":
                continue
            #
            if not self.factory:
                obj = NXOSCfgLine(line, self.comment_delimiter)
            elif self.syntax == "nxos":
                obj = ConfigLineFactory(line, self.comment_delimiter, syntax="nxos")
            else:
                raise ValueError

            obj.confobj = self
            obj.linenum = idx
            indent = len(line) - len(line.lstrip())
            obj.indent = indent

            is_config_line = obj.is_config_line

            ## Parent cache:
            ## Maintain indent vs max_indent in a family and
            ##     cache the parent until indent<max_indent
            if (indent < max_indent) and is_config_line:
                parent = None
                # walk parents and intelligently prune stale parents
                stale_parent_idxs = filter(
                    lambda ii: ii >= indent, sorted(parents.keys(), reverse=True)
                )
                for parent_idx in stale_parent_idxs:
                    del parents[parent_idx]
            else:
                ## As long as the child indent hasn't gone backwards,
                ##    we can use a cached parent
                parent = parents.get(indent, None)

            ## If indented, walk backwards and find the parent...
            ## 1.  Assign parent to the child
            ## 2.  Assign child to the parent
            ## 3.  Assign parent's child_indent
            ## 4.  Maintain oldest_ancestor
            if (indent > 0) and not (parent is None):
                ## Add the line as a child (parent was cached)
                self._add_child_to_parent(retval, idx, indent, parent, obj)
            elif (indent > 0) and (parent is None):
                ## Walk backwards to find parent, and add the line as a child
                candidate_parent_index = idx - 1
                while candidate_parent_index >= 0:
                    candidate_parent = retval[candidate_parent_index]
                    if (
                        candidate_parent.indent < indent
                    ) and candidate_parent.is_config_line:
                        # We found the parent
                        parent = candidate_parent
                        parents[indent] = parent  # Cache the parent
                        if indent == 0:
                            parent.oldest_ancestor = True
                        break
                    else:
                        candidate_parent_index -= 1

                ## Add the line as a child...
                self._add_child_to_parent(retval, idx, indent, parent, obj)

            ## Handle max_indent
            if (indent == 0) and is_config_line:
                # only do this if it's a config line...
                max_indent = 0
            elif indent > max_indent:
                max_indent = indent

            retval.append(obj)
            idx += 1

        self._list = retval
        self._banner_mark_regex(BANNER_RE)  # Process IOS banners
        return retval

    def _add_child_to_parent(self, _list, idx, indent, parentobj, childobj):
        ## parentobj could be None when trying to add a child that should not
        ##    have a parent
        if parentobj is None:
            if self.debug > 0:
                logger.debug("parentobj is None")
            return

        if self.debug > 0:
            # logger.debug("Adding child '{0}' to parent"
            #    " '{1}'".format(childobj, parentobj))
            # logger.debug("BEFORE parent.children - {0}"
            #    .format(parentobj.children))
            pass
        if childobj.is_comment and (_list[idx - 1].indent > indent):
            ## I *really* hate making this exception, but legacy
            ##   ciscoconfparse never marked a comment as a child
            ##   when the line immediately above it was indented more
            ##   than the comment line
            pass
        elif childobj.parent is childobj:
            # Child has not been assigned yet
            parentobj.children.append(childobj)
            childobj.parent = parentobj
            childobj.parent.child_indent = indent
        else:
            pass

        if self.debug > 0:
            # logger.debug("     AFTER parent.children - {0}"
            #    .format(parentobj.children))
            pass

    def iter_with_comments(self, begin_index=0):
        for idx, obj in enumerate(self._list):
            if idx >= begin_index:
                yield obj

    def iter_no_comments(self, begin_index=0):
        for idx, obj in enumerate(self._list):
            if (idx >= begin_index) and (not obj.is_comment):
                yield obj

    def _reassign_linenums(self):
        # Call this after any insertion or deletion
        for idx, obj in enumerate(self._list):
            obj.linenum = idx

    @property
    def all_parents(self):
        return [obj for obj in self._list if obj.has_children]

    @property
    def last_index(self):
        return self.__len__() - 1


class ASAConfigList(MutableSequence):
    """A custom list to hold :class:`~models_asa.ASACfgLine` objects.  Most
    people will never need to use this class directly.


    """

    def __init__(
        self,
        data=None,
        comment_delimiter="!",
        debug=0,
        factory=False,
        ignore_blank_lines=True,
        syntax="asa",
        CiscoConfParse=None,
    ):
        """Initialize the class.

        Parameters
        ----------
        data : list
            A list of parsed :class:`~models_cisco.IOSCfgLine` objects
        comment_delimiter : str
            A comment delimiter.  This should only be changed when parsing non-Cisco IOS configurations, which do not use a !  as the comment delimiter.  ``comment`` defaults to '!'
        debug : int
            ``debug`` defaults to 0, and should be kept that way unless you're working on a very tricky config parsing problem.  Debug output is not particularly friendly
        ignore_blank_lines : bool
            ``ignore_blank_lines`` defaults to True; when this is set True, ciscoconfparse ignores blank configuration lines.  You might want to set ``ignore_blank_lines`` to False if you intentionally use blank lines in your configuration (ref: Github Issue #2).

        Returns
        -------
        An instance of an :class:`~ciscoconfparse.ASAConfigList` object.

        """
        super(ASAConfigList, self).__init__()

        self._list = list()
        self.CiscoConfParse = CiscoConfParse
        self.comment_delimiter = comment_delimiter
        self.factory = factory
        self.ignore_blank_lines = ignore_blank_lines
        self.syntax = syntax
        self.dna = "ASAConfigList"
        self.debug = debug

        ## Support either a list or a generator instance
        if getattr(data, "__iter__", False):
            self._bootstrap_obj_init(data)
        else:
            self._list = list()

        ###
        ### Internal structures
        self._RE_NAMES = re.compile(r"^\s*name\s+(\d+\.\d+\.\d+\.\d+)\s+(\S+)")
        self._RE_OBJNET = re.compile(r"^\s*object-group\s+network\s+(\S+)")
        self._RE_OBJSVC = re.compile(r"^\s*object-group\s+service\s+(\S+)")
        self._RE_OBJACL = re.compile(r"^\s*access-list\s+(\S+)")
        self._network_cache = dict()

    def __len__(self):
        return len(self._list)

    def __getitem__(self, ii):
        return self._list[ii]

    def __delitem__(self, ii):
        del self._list[ii]
        self._bootstrap_from_text()

    def __setitem__(self, ii, val):
        return self._list[ii]

    def __str__(self):
        return self.__repr__()

    def __enter__(self):
        # Add support for with statements...
        # FIXME: *with* statements dont work
        for obj in self._list:
            yield obj

    def __exit__(self, *args, **kwargs):
        # FIXME: *with* statements dont work
        self._list[0].confobj.CiscoConfParse.atomic()

    def __repr__(self):
        return """<ASAConfigList, comment='%s', conf=%s>""" % (
            self.comment_delimiter,
            self._list,
        )

    def _bootstrap_from_text(self):
        ## reparse all objects from their text attributes... this is *very* slow
        ## Ultimate goal: get rid of all reparsing from text...
        self._list = self._bootstrap_obj_init(list(map(attrgetter("text"), self._list)))

    def has_line_with(self, linespec):
        return bool(filter(methodcaller("re_search", linespec), self._list))

    def insert_before(self, robj, val, atomic=False):
        ## Insert something before robj
        if getattr(robj, "capitalize", False):
            raise ValueError

        if getattr(val, "capitalize", False):
            if self.factory:
                obj = ConfigLineFactory(
                    text=val,
                    comment_delimiter=self.comment_delimiter,
                    syntax=self.syntax,
                )
            elif self.syntax == "asa":
                obj = ASACfgLine(text=val, comment_delimiter=self.comment_delimiter)

        ii = self._list.index(robj)
        if (ii is not None):
            ## Do insertion here
            self._list.insert(ii, obj)

        if atomic:
            # Reparse the whole config as a text list
            self._bootstrap_from_text()
        else:
            ## Just renumber lines...
            self._reassign_linenums()

    def insert_after(self, robj, val, atomic=False):
        ## Insert something after robj
        if getattr(robj, "capitalize", False):
            raise ValueError

        if getattr(val, "capitalize", False):
            if self.factory:
                obj = ConfigLineFactory(
                    text=val,
                    comment_delimiter=self.comment_delimiter,
                    syntax=self.syntax,
                )
            elif self.syntax == "asa":
                obj = ASACfgLine(text=val, comment_delimiter=self.comment_delimiter)

        ## FIXME: This shouldn't be required
        self._reassign_linenums()

        ii = self._list.index(robj)
        if (ii is not None):
            ## Do insertion here
            self._list.insert(ii + 1, obj)

        if atomic:
            # Reparse the whole config as a text list
            self._bootstrap_from_text()
        else:
            ## Just renumber lines...
            self._reassign_linenums()

    def insert(self, ii, val):
        ## Insert something at index ii
        if getattr(val, "capitalize", False):
            if self.factory:
                obj = ConfigLineFactory(
                    text=val,
                    comment_delimiter=self.comment_delimiter,
                    syntax=self.syntax,
                )
            elif self.syntax == "asa":
                obj = ASACfgLine(text=val, comment_delimiter=self.comment_delimiter)

        self._list.insert(ii, obj)

        ## Just renumber lines...
        self._reassign_linenums()

    def append(self, val, atomic=False):
        list_idx = len(self._list)
        self.insert(list_idx, val)

    def config_hierarchy(self):
        """Walk this configuration and return the following tuple
        at each parent 'level':
            (list_of_parent_siblings, list_of_nonparent_siblings)"""
        parent_siblings = list()
        nonparent_siblings = list()

        for obj in self.CiscoConfParse.find_objects(r"^\S+"):
            if obj.is_comment:
                continue
            elif len(obj.children) == 0:
                nonparent_siblings.append(obj)
            else:
                parent_siblings.append(obj)

        return parent_siblings, nonparent_siblings

    def _bootstrap_obj_init(self, text_list):
        """Accept a text list and format into proper objects"""
        # Append text lines as IOSCfgLine objects...
        retval = list()
        idx = 0

        max_indent = 0
        parents = dict()
        for line in text_list:
            # Reject empty lines if ignore_blank_lines...
            if self.ignore_blank_lines and line.strip() == "":
                continue

            if self.syntax == "asa" and self.factory:
                obj = ConfigLineFactory(line, self.comment_delimiter, syntax="asa")
            elif self.syntax == "asa" and not self.factory:
                obj = ASACfgLine(text=line, comment_delimiter=self.comment_delimiter)
            else:
                raise ValueError

            obj.confobj = self
            obj.linenum = idx
            indent = len(line) - len(line.lstrip())
            obj.indent = indent

            is_config_line = obj.is_config_line

            ## Parent cache:
            ## Maintain indent vs max_indent in a family and
            ##     cache the parent until indent<max_indent
            if (indent < max_indent) and is_config_line:
                parent = None
                # walk parents and intelligently prune stale parents
                stale_parent_idxs = filter(
                    lambda ii: ii >= indent, sorted(parents.keys(), reverse=True)
                )
                for parent_idx in stale_parent_idxs:
                    del parents[parent_idx]
            else:
                ## As long as the child indent hasn't gone backwards,
                ##    we can use a cached parent
                parent = parents.get(indent, None)

            ## If indented, walk backwards and find the parent...
            ## 1.  Assign parent to the child
            ## 2.  Assign child to the parent
            ## 3.  Assign parent's child_indent
            ## 4.  Maintain oldest_ancestor
            if (indent > 0) and not (parent is None):
                ## Add the line as a child (parent was cached)
                self._add_child_to_parent(retval, idx, indent, parent, obj)
            elif (indent > 0) and (parent is None):
                ## Walk backwards to find parent, and add the line as a child
                candidate_parent_index = idx - 1
                while candidate_parent_index >= 0:
                    candidate_parent = retval[candidate_parent_index]
                    if (
                        candidate_parent.indent < indent
                    ) and candidate_parent.is_config_line:
                        # We found the parent
                        parent = candidate_parent
                        parents[indent] = parent  # Cache the parent
                        if indent == 0:
                            parent.oldest_ancestor = True
                        break
                    else:
                        candidate_parent_index -= 1

                ## Add the line as a child...
                self._add_child_to_parent(retval, idx, indent, parent, obj)

            ## Handle max_indent
            if (indent == 0) and is_config_line:
                # only do this if it's a config line...
                max_indent = 0
            elif indent > max_indent:
                max_indent = indent

            retval.append(obj)
            idx += 1

        self._list = retval
        ## Insert ASA-specific banner processing here, if required
        return retval

    def _add_child_to_parent(self, _list, idx, indent, parentobj, childobj):
        ## parentobj could be None when trying to add a child that should not
        ##    have a parent
        if parentobj is None:
            if self.debug > 0:
                logger.debug("parentobj is None")
            return

        if self.debug > 0:
            logger.debug(
                "Adding child '{0}' to parent" " '{1}'".format(childobj, parentobj)
            )
            logger.debug("     BEFORE parent.children - {0}".format(parentobj.children))
        if childobj.is_comment and (_list[idx - 1].indent > indent):
            ## I *really* hate making this exception, but legacy
            ##   ciscoconfparse never marked a comment as a child
            ##   when the line immediately above it was indented more
            ##   than the comment line
            pass
        elif childobj.parent is childobj:
            # Child has not been assigned yet
            parentobj.children.append(childobj)
            childobj.parent = parentobj
            childobj.parent.child_indent = indent
        else:
            pass

        if self.debug > 0:
            logger.debug("     AFTER parent.children - {0}".format(parentobj.children))

    def iter_with_comments(self, begin_index=0):
        for idx, obj in enumerate(self._list):
            if idx >= begin_index:
                yield obj

    def iter_no_comments(self, begin_index=0):
        for idx, obj in enumerate(self._list):
            if (idx >= begin_index) and (not obj.is_comment):
                yield obj

    def _reassign_linenums(self):
        # Call this after any insertion or deletion
        for idx, obj in enumerate(self._list):
            obj.linenum = idx

    @property
    def all_parents(self):
        return [obj for obj in self._list if obj.has_children]

    @property
    def last_index(self):
        return self.__len__() - 1

    ###
    ### ASA-specific stuff here...
    ###
    @property
    def names(self):
        """Return a dictionary of name to address mappings"""
        retval = dict()
        name_rgx = self._RE_NAMES
        for obj in self.CiscoConfParse.find_objects(name_rgx):
            addr = obj.re_match_typed(name_rgx, group=1, result_type=str)
            name = obj.re_match_typed(name_rgx, group=2, result_type=str)
            retval[name] = addr
        return retval

    @property
    def object_group_network(self):
        """Return a dictionary of name to object-group network mappings"""
        retval = dict()
        obj_rgx = self._RE_OBJNET
        for obj in self.CiscoConfParse.find_objects(obj_rgx):
            name = obj.re_match_typed(obj_rgx, group=1, result_type=str)
            retval[name] = obj
        return retval

    @property
    def access_list(self):
        """Return a dictionary of ACL name to ACE (list) mappings"""
        retval = dict()
        for obj in self.CiscoConfParse.find_objects(self._RE_OBJACL):
            name = obj.re_match_typed(self._RE_OBJACL, group=1, result_type=str)
            tmp = retval.get(name, [])
            tmp.append(obj)
            retval[name] = tmp
        return retval


class DiffObject(object):
    """This object should be used at every level of hierarchy"""

    def __init__(self, level, nonparents, parents):
        self.level = level
        self.nonparents = nonparents
        self.parents = parents

    def __repr__(self):
        return "<DiffObject level: {0}>".format(self.level)


class CiscoPassword(object):
    def __init__(self, ep=""):
        self.ep = ep

    def decrypt(self, ep=""):
        """Cisco Type 7 password decryption.  Converted from perl code that was
        written by jbash [~at~] cisco.com; enhancements suggested by
        rucjain [~at~] cisco.com"""

        xlat = (
            0x64,
            0x73,
            0x66,
            0x64,
            0x3B,
            0x6B,
            0x66,
            0x6F,
            0x41,
            0x2C,
            0x2E,
            0x69,
            0x79,
            0x65,
            0x77,
            0x72,
            0x6B,
            0x6C,
            0x64,
            0x4A,
            0x4B,
            0x44,
            0x48,
            0x53,
            0x55,
            0x42,
            0x73,
            0x67,
            0x76,
            0x63,
            0x61,
            0x36,
            0x39,
            0x38,
            0x33,
            0x34,
            0x6E,
            0x63,
            0x78,
            0x76,
            0x39,
            0x38,
            0x37,
            0x33,
            0x32,
            0x35,
            0x34,
            0x6B,
            0x3B,
            0x66,
            0x67,
            0x38,
            0x37,
        )

        dp = ""
        regex = re.compile("^(..)(.+)")
        ep = ep or self.ep
        if not (len(ep) & 1):
            result = regex.search(ep)
            try:
                s, e = int(result.group(1)), result.group(2)
            except ValueError:
                # typically get a ValueError for int( result.group(1))) because
                # the method was called with an unencrypted password.  For now
                # SILENTLY bypass the error
                s, e = (0, "")
            for ii in range(0, len(e), 2):
                # int( blah, 16) assumes blah is base16... cool
                magic = int(re.search(".{%s}(..)" % ii, e).group(1), 16)
                # Wrap around after 53 chars...
                newchar = "%c" % (magic ^ int(xlat[int(s % 53)]))
                dp = dp + str(newchar)
                s = s + 1
        # if s > 53:
        #    logger.warning("password decryption failed.")
        return dp


def ConfigLineFactory(text="", comment_delimiter="!", syntax="ios"):
    # Complicted & Buggy
    # classes = [j for (i,j) in globals().iteritems() if isinstance(j, TypeType) and issubclass(j, BaseCfgLine)]

    ## Manual and simple
    if syntax == "ios":
        classes = [
            IOSIntfLine,
            IOSRouteLine,
            IOSAccessLine,
            IOSAaaLoginAuthenticationLine,
            IOSAaaEnableAuthenticationLine,
            IOSAaaCommandsAuthorizationLine,
            IOSAaaCommandsAccountingLine,
            IOSAaaExecAccountingLine,
            IOSAaaGroupServerLine,
            IOSHostnameLine,
            IOSIntfGlobal,
            IOSCfgLine,
        ]  # This is simple
    elif syntax == "nxos":
        classes = [
            NXOSIntfLine,
            NXOSRouteLine,
            NXOSAccessLine,
            NXOSAaaLoginAuthenticationLine,
            NXOSAaaEnableAuthenticationLine,
            NXOSAaaCommandsAuthorizationLine,
            NXOSAaaCommandsAccountingLine,
            NXOSAaaExecAccountingLine,
            NXOSAaaGroupServerLine,
            NXOSvPCLine,
            NXOSHostnameLine,
            NXOSIntfGlobal,
            NXOSCfgLine,
        ]  # This is simple
    elif syntax == "asa":
        classes = [
            ASAName,
            ASAObjNetwork,
            ASAObjService,
            ASAObjGroupNetwork,
            ASAObjGroupService,
            ASAIntfLine,
            ASAIntfGlobal,
            ASAHostnameLine,
            ASAAclLine,
            ASACfgLine,
        ]
    elif syntax == "junos":
        classes = [IOSCfgLine]
    else:
        error = "'{0}' is an unknown syntax".format(syntax)
        logger.error(error)
        raise ValueError("'{0}' is an unknown syntax".format(syntax))

    for cls in classes:
        if cls.is_object_for(text):
            inst = cls(
                text=text, comment_delimiter=comment_delimiter
            )  # instance of the proper subclass
            return inst
    error = "Could not find an object for '%s'" % line
    logger.error(error)
    raise ValueError(error)


### TODO: Add unit tests below
if __name__ == "__main__":
    import optparse

    pp = optparse.OptionParser()
    pp.add_option(
        "-c", dest="config", help="Config file to be parsed", metavar="FILENAME"
    )
    pp.add_option("-m", dest="method", help="Command for parsing", metavar="METHOD")
    pp.add_option("--a1", dest="arg1", help="Command's first argument", metavar="ARG")
    pp.add_option("--a2", dest="arg2", help="Command's second argument", metavar="ARG")
    pp.add_option("--a3", dest="arg3", help="Command's third argument", metavar="ARG")
    (opts, args) = pp.parse_args()

    if opts.method == "find_lines":
        diff = CiscoConfParse(opts.config).find_lines(opts.arg1)
    elif opts.method == "find_children":
        diff = CiscoConfParse(opts.config).find_children(opts.arg1)
    elif opts.method == "find_all_children":
        diff = CiscoConfParse(opts.config).find_all_children(opts.arg1)
    elif opts.method == "find_blocks":
        diff = CiscoConfParse(opts.config).find_blocks(opts.arg1)
    elif opts.method == "find_parents_w_child":
        diff = CiscoConfParse(opts.config).find_parents_w_child(opts.arg1, opts.arg2)
    elif opts.method == "find_parents_wo_child":
        diff = CiscoConfParse(opts.config).find_parents_wo_child(opts.arg1, opts.arg2)
    elif opts.method == "req_cfgspec_excl_diff":
        diff = CiscoConfParse(opts.config).req_cfgspec_excl_diff(
            opts.arg1, opts.arg2, opts.arg3.split(",")
        )
    elif opts.method == "req_cfgspec_all_diff":
        diff = CiscoConfParse(opts.config).req_cfgspec_all_diff(opts.arg1.split(","))
    elif opts.method == "decrypt":
        pp = CiscoPassword()
        print(pp.decrypt(opts.arg1))
        exit(1)
    elif opts.method == "help":
        print("Valid methods and their arguments:")
        print("   find_lines:             arg1=linespec")
        print("   find_children:          arg1=linespec")
        print("   find_all_children:      arg1=linespec")
        print("   find_blocks:            arg1=linespec")
        print("   find_parents_w_child:   arg1=parentspec  arg2=childspec")
        print("   find_parents_wo_child:  arg1=parentspec  arg2=childspec")
        print(
            "   req_cfgspec_excl_diff:  arg1=linespec    arg2=uncfgspec"
            + "   arg3=cfgspec"
        )
        print("   req_cfgspec_all_diff:   arg1=cfgspec")
        print("   decrypt:                arg1=encrypted_passwd")
        exit(1)
    else:
        import doctest

        doctest.testmod()
        exit(0)

    if len(diff) > 0:
        for line in diff:
            print(line)
    else:
        error = "ciscoconfparse was called with unknown parameters"
        logger.error(error)
        raise RuntimeError(error)
