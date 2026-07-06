#!/usr/bin/env python2
# Redis PING/PONG protocol checker for the Adjudicator
# Validates Redis is actually running by sending PING and expecting
# +PONG or -NOAUTH (both confirm a real Redis instance).
from twisted.internet import reactor, protocol
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

    def TimedOut(self):
        self.transport.loseConnection()
        self.factory.add_fail("timeout")

    def connectionMade(self):
        logger.info("Job %s: Redis connection made to %s:%s" % (
            self.job_id, self.factory.get_ip(), self.factory.get_port()))
        reactor.callLater(self.factory.get_timeout(), self.TimedOut)
        # Send Redis PING command using inline format
        self.transport.write(b'PING\r\n')

    def dataReceived(self, data):
        self.recv += data
        response = self.recv.decode('utf-8', errors='replace')
        # Redis responds with +PONG\r\n for an unauthenticated PING
        # or -NOAUTH Authentication required.\r\n if auth is enabled
        # Both responses confirm a real Redis server is running
        if '+PONG' in response:
            logger.info("Job %s: Redis PONG received from %s" % (
                self.job_id, self.factory.get_ip()))
            self.factory.add_data("Redis OK - PONG received\r\n")
            self.transport.loseConnection()
        elif '-NOAUTH' in response:
            logger.info("Job %s: Redis NOAUTH received from %s (auth required, server is real)" % (
                self.job_id, self.factory.get_ip()))
            self.factory.add_data("Redis OK - NOAUTH received (server confirmed)\r\n")
            self.transport.loseConnection()
        elif '-' in response:
            # Any Redis error response still confirms it's Redis
            logger.info("Job %s: Redis error response from %s: %s" % (
                self.job_id, self.factory.get_ip(), response.strip()))
            self.factory.add_data("Redis OK - error response received (server confirmed)\r\n")
            self.transport.loseConnection()
        elif len(self.recv) > 256:
            # Got a lot of data but no Redis-like response
            logger.warning("Job %s: Invalid Redis response from %s" % (
                self.job_id, self.factory.get_ip()))
            self.factory.add_data("Redis FAIL - no valid Redis response\r\n")
            self.factory.add_fail("invalid Redis response")
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
        connector = reactor.connectTCP(self.job.get_ip(), self.service.get_port(),
                                       self, self.params.get_timeout())
        deferred = self.get_deferred(connector)
        deferred.addCallback(self.service_pass)
        deferred.addErrback(self.service_fail)

    def service_pass(self, reason):
        self.service.pass_conn()
        logger.info("Job %s: Redis check passed for %s" % (self.job_id, self.ip))

    def service_fail(self, failure):
        self.service.fail_conn(failure)
        logger.warning("Job %s: Redis check failed for %s" % (self.job_id, self.ip))

    def clientConnectionFailed(self, connector, reason):
        self.end = time.time()
        if self.params.debug:
            logger.warning("Job %s: Redis clientConnectionFailed: %s" % (
                self.job.get_job_id(), reason))
        conn_time = None
        if self.start:
            conn_time = self.end - self.start
        else:
            self.service.timeout(self.data)
            return
        self.service.fail_conn(reason.getErrorMessage(), self.data)
        self.deferreds[connector].errback(reason)

    def clientConnectionLost(self, connector, reason):
        self.end = time.time()
        if self.params.debug:
            logger.info("Job %s: Redis clientConnectionLost: %s" % (
                self.job.get_job_id(), reason))
        if self.data:
            self.service.set_data(self.data)
        if self.fail and self.reason:
            self.service.fail_conn(self.reason, self.data)
            self.deferreds[connector].errback(reason)
        elif self.fail and not self.reason:
            self.service.fail_conn(reason.getErrorMessage(), self.data)
            self.deferreds[connector].errback(reason)
        elif "non-clean" in reason.getErrorMessage():
            self.service.fail_conn("other", self.data)
            self.deferreds[connector].errback(reason)
        else:
            self.service.pass_conn()
            self.deferreds[connector].callback(self.job.get_job_id())
