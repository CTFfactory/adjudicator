#!/usr/bin/env python2
from twisted.internet import reactor
from twisted.internet.defer import Deferred
from BaseClient import BaseProtocol
import re

class DNSProtocol(BaseProtocol):

    def __init__(self, job, service=None):
        super().__init__(job, service)
        self.success_re = re.compile("(DNS OK: .*)")
        self.refused_re = re.compile("(.*Connection refused|.*No response)")
        self.prog = "/usr/lib/nagios/plugins/check_dns"

    def connect(self):
        # Query the nameserver (self.ipaddr) to resolve the host's own hostname
        args = [self.prog, "-s", self.ipaddr, "-H", self.job.get_hostname()]
        reactor.spawnProcess(self, self.prog, args)
