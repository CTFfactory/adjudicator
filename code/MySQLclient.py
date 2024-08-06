#!/usr/bin/env python2
from twisted.internet import reactor
from twisted.internet.defer import Deferred
from Jobs import Jobs
from BaseClient import BaseProtocol
import sys
import re

class MySQLProtocol(BaseProtocol):

    def __init__(self, job):
        super().__init__(job)
        self.success_re = re.compile("(Access denied for user.*)")
        self.refused_re = re.compile("(Can't connect to MySQL server on.*)")
        self.prog = "/usr/lib/nagios/plugins/check_mysql"
