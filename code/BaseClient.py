#!/usr/bin/env python2
from twisted.internet import reactor, protocol
from twisted.internet.defer import Deferred
from Jobs import Jobs
import re

class BaseProtocol(protocol.ProcessProtocol):

    def __init__(self, job):
        self.job = job
        self.ipaddr = self.job.get_ip()
        self.data = ""
        self.success_re = None
        self.refused_re = None
        self.d = Deferred()
        self.prog = ""

    def connect(self):
        reactor.spawnProcess(self, self.prog, [self.prog, self.ipaddr])

    def getDeferred(self):
        return self.d

    def outConnectionLost(self):
        self.success_m = self.success_re.search(self.data)
        self.failure_m = self.refused_re.search(self.data)
        if self.success_m:
            self.success = self.success_m.group()
            self.d.callback(self)
        else:
            self.d.errback()

    def outReceived(self, data):
        if type(data) == type(b'a'):
            self.data += data.decode('utf-8')+"\r\n"
        else:
            self.data += data

    def get_recv(self):
        return self.recv

    def get_lost(self):
        return self.lost