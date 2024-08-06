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
        self.success_re = re.compile("(SSH OK .*)")
        self.failure_re = re.compile("(.*Connection refused)")
        self.prog = "/usr/lib/nagios/plugins/check_mysql"
