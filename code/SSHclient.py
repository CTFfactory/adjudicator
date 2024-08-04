#!/usr/bin/env python2
from twisted.internet import reactor
from twisted.internet.defer import Deferred
from Jobs import Jobs
from BaseClient import BaseProtocol
import sys
import re

class SSHProtocol(BaseProtocol):

    def __init__(self, job):
        super().__init__(job)
        self.success_re = re.compile("(SSH OK .*)")
        self.refused_re = re.compile("(.*Connection refused)")
        self.prog = "/usr/lib/nagios/plugins/check_ssh"

    def outConnectionLost(self):
        self.success_m = self.success_re.search(self.data)
        self.failure_m = self.refused_re.search(self.data)
        if self.success_m:
            self.success = self.success_m.group()
        if self.failure_m:
            self.failure = self.failure_m.group()
        if self.success and not self.fail:
            self.d.callback(self)
        else:
            self.d.errback()
