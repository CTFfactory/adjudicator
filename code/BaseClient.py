#!/usr/bin/env python2
from twisted.internet import reactor, protocol
from twisted.internet.defer import Deferred
from Jobs import Jobs
import re

class BaseProtocol(protocol.ProcessProtocol):

    def __init__(self, job, service=None):
        self.job = job
        self.service = service
        self.ipaddr = self.job.get_ip()
        self.data = ""
        self.success_re = None
        self.refused_re = None
        self.d = Deferred()
        self.prog = ""

    def connect(self):
        # Default behavior: use -H for host
        args = [self.prog, "-H", self.ipaddr]
        reactor.spawnProcess(self, self.prog, args)

    def getDeferred(self):
        return self.d

    def outConnectionLost(self):
        pass

    def processEnded(self, reason):
        exit_code = 0
        if hasattr(reason.value, 'exitCode') and reason.value.exitCode is not None:
            exit_code = reason.value.exitCode

        self.exit_code = exit_code
        if exit_code == 0:
            self.job_status = "pass"
            self.d.callback(self)
        elif exit_code == 1:
            self.job_status = "yellow"
            self.d.callback(self)
        else:
            if self.success_re and self.success_re.search(self.data):
                self.job_status = "yellow"
                self.d.callback(self)
            else:
                self.job_status = "fail"
                self.d.errback(reason)

    def outReceived(self, data):
        if type(data) == type(b'a'):
            self.data += data.decode('utf-8')+"\r\n"
        else:
            self.data += data

    def get_recv(self):
        return self.recv

    def get_lost(self):
        return self.lost