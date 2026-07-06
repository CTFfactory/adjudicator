#!/usr/bin/env python2
# Redis PING/PONG and AUTH protocol checker for the Adjudicator
from twisted.internet import reactor, protocol, ssl
from twisted.internet.defer import Deferred
from GenSocket import GenCoreFactory
import time
import sys
from logger import logger

class RedisClient(protocol.Protocol):

    def __init__(self, factory):
        self.factory = factory
        self.job_id = self.factory.get_job_id()
        self.recv = b''
        self.state = 'INIT'

    def TimedOut(self):
        self.transport.loseConnection()
        self.factory.add_fail("timeout")

    def connectionMade(self):
        logger.info("Job %s: Redis connection made to %s:%s" % (
            self.job_id, self.factory.get_ip(), self.factory.get_port()))
        reactor.callLater(self.factory.get_timeout(), self.TimedOut)

        auth = self.factory.service.get_auth() if self.factory.service else None
        self.password = auth.get("password", "") if auth else ""

        if self.password:
            self.state = 'AUTHING'
            self.transport.write(b'AUTH %s\r\n' % self.password)
        else:
            self.state = 'PINGING'
            self.transport.write(b'PING\r\n')

    def dataReceived(self, data):
        self.recv += data
        response = self.recv.decode('utf-8', errors='replace')

        if self.state == 'AUTHING':
            if '+OK' in response:
                self.recv = b''
                self.state = 'PINGING'
                self.transport.write(b'PING\r\n')
            elif '-' in response:
                logger.warning("Job %s: Redis authentication failed for %s: %s" % (
                    self.job_id, self.factory.get_ip(), response.strip()))
                self.factory.add_data("Redis FAIL - authentication failed\r\n")
                self.factory.add_fail("authentication failed")
                self.transport.loseConnection()
        elif self.state == 'PINGING':
            if '+PONG' in response:
                logger.info("Job %s: Redis PONG received from %s" % (
                    self.job_id, self.factory.get_ip()))
                self.factory.add_data("Redis OK - PONG received\r\n")
                self.transport.loseConnection()
            elif '-NOAUTH' in response:
                logger.warning("Job %s: Redis check failed - authentication required by server but not provided by team" % self.job_id)
                self.factory.add_data("Redis FAIL - auth required\r\n")
                self.factory.add_fail("authentication required")
                self.transport.loseConnection()
            elif '-' in response:
                logger.warning("Job %s: Redis ping error response from %s: %s" % (
                    self.job_id, self.factory.get_ip(), response.strip()))
                self.factory.add_data("Redis FAIL - error response\r\n")
                self.factory.add_fail("ping error response")
                self.transport.loseConnection()
        
        if len(self.recv) > 512:
            self.factory.add_fail("response buffer overflow")
            self.transport.loseConnection()

class RedisCheckFactory(GenCoreFactory):

    def __init__(self, params, job, service):
        GenCoreFactory.__init__(self)
        self.params = params
        self.job = job
        self.job_id = self.job.get_job_id()
        self.ip = self.job.get_ip()
        self.service = service
        self.port = self.service.get_port()
        self.timeout = self.job.get_timeout()

    def buildProtocol(self, addr):
        self.addr = addr
        self.start = time.time()
        return RedisClient(self)

    def check_service(self):
        auth = self.service.get_auth() if self.service else None
        use_ssl = auth.get("use_ssl", False) if auth else False

        if use_ssl:
            ssl_obj = ssl.CertificateOptions()
            connector = reactor.connectSSL(self.job.get_ip(), self.service.get_port(),
                                           self, ssl_obj, self.params.get_timeout())
        else:
            connector = reactor.connectTCP(self.job.get_ip(), self.service.get_port(),
                                           self, self.params.get_timeout())
        
        deferred = self.get_deferred(connector)
        deferred.addCallback(self.service_pass)
        deferred.addErrback(self.service_fail)

    def service_pass(self, reason):
        self.service.pass_conn()
        logger.info("Job %s: Redis check passed for %s" % (self.job_id, self.ip))

    def service_fail(self, failure):
        self.service.fail_login()
        logger.warning("Job %s: Redis check failed for %s" % (self.job_id, self.ip))

    def clientConnectionFailed(self, connector, reason):
        self.end = time.time()
        self.service.fail_login()
        self.deferreds[connector].errback(reason)

    def clientConnectionLost(self, connector, reason):
        self.end = time.time()
        if self.data:
            self.service.set_data(self.data)
        if self.fail and self.reason:
            self.service.fail_login()
            self.deferreds[connector].errback(reason)
        elif self.fail and not self.reason:
            self.service.fail_login()
            self.deferreds[connector].errback(reason)
        elif "non-clean" in reason.getErrorMessage():
            self.service.fail_login()
            self.deferreds[connector].errback(reason)
        else:
            self.service.pass_conn()
            self.deferreds[connector].callback(self.job.get_job_id())
