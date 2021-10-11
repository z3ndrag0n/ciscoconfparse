from __future__ import absolute_import

r""" errors.py - Parse, Query, Build, and Modify IOS-style configs

     Copyright (C) 2020-2021 Cisco Systems and David Michael Pennington
     Copyright (C) 2019      ThousandEyes and David Michael Pennington
     Copyright (C) 2018-2019 Samsung Data Services and David Michael Pennington

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


class BaseError(Exception):
    def __init__(self, msg=""):
        super(BaseError, self).__init__(msg)
        self.msg = msg


class DynamicAddressException(Exception):
    """Throw this if you try to get an address object from a dhcp interface"""

    def __init__(self, msg=""):
        super(DynamicAddressException, self).__init__(msg)
        self.msg = msg
