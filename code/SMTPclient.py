#!/usr/bin/env python2
# requires:  https://pypi.python.org/pypi/http-parser
from twisted.internet import reactor, protocol, ssl
from twisted.internet.defer import Deferred
from GenSocket import GenCoreFactory
import time
import sys
from logger import logger


class SMTPClient(protocol.Protocol):

    def __init__(self, factory):
        self.factory = factory
        self.job_id = self.factory.get_job_id()
        self.fqdn = "mail.scorebot.prosversusjoes.net"
        self.addr = self.factory.get_ip()
        self.port = self.factory.get_port()
        self.request = "HELO %s\n" % self.fqdn
        self.recv = ""

    def no_unicode(self, text):
        #sys.stderr.write("\nJob %s: Converting %s" % (self.job_id, text))
        if isinstance(text, str):
            return text.encode('utf-8')
        else:
            return text

    def TimedOut(self):
        self.transport.loseConnection()
        self.factory.add_fail("timeout")

    def connectionMade(self):
        if self.job_id:
            logger.info("Job %s: Made connection to %s:%s" % (self.job_id, self.factory.get_ip(), self.factory.get_port()))
        else:
            logger.info("Made connection to %s:%s" % (self.factory.get_ip(), self.factory.get_port()))

    def dataReceived(self, data):
        data_len = len(data)
        self.recv += data.decode('utf-8')
        logger.debug("Job %s: Received %s" % (self.job_id, data))
        self.factory.add_data(data)
        if "220" in data.decode('utf-8') and "SMTP" in data.decode('utf-8'):
            logger.debug("Job %s: Sending %s" % (self.job_id, self.request))
            self.transport.write(self.no_unicode(self.request))
            return
        elif "250" in data:
            self.transport.loseConnection()

class SMTPFactory(GenCoreFactory):

    def __init__(self, params, job, service):
        GenCoreFactory.__init__(self)
        self.params = params
        self.job = job
        self.job_id = self.job.get_job_id()
        self.fqdn = self.job.get_fqdn()
        self.ip = self.job.get_ip()
        self.service = service
        self.fqdn = self.job.get_fqdn()

    def buildProtocol(self, addr):
        self.addr = addr
        self.start = time.time()
        return SMTPClient(self)

    def check_service(self):
        connector = reactor.connectTCP(self.job.get_ip(), self.service.get_port(), self, self.params.get_timeout())
        deferred = self.get_deferred(connector)
        deferred.addCallback(self.service_pass)
        deferred.addErrback(self.service_fail)

    def service_pass(self, reason):
        self.service.pass_conn()
        logger.info("Job %s: Successfully checked SMTP connection for %s(%s)" % (self.job_id, self.fqdn, self.ip))

    def service_fail(self, failure):
        self.service.pass_conn(failure)
        logger.warning("Job %s: Failed check of SMTP connection for %s(%s)" % (self.job_id, self.fqdn, self.ip))

    def clientConnectionFailed(self, connector, reason):
        self.end = time.time()
        if self.params.debug:
            logger.warning("Job %s: clientConnectionFailed: %s" % (self.job.get_job_id(), reason))
            logger.debug("Received headers: %s" % self.get_server_headers())
        conn_time = None
        if self.start:
            conn_time = self.end - self.start
        else:
            self.service.timeout(self.data)
            return
        self.deferreds[connector].errback(reason)

    def clientConnectionLost(self, connector, reason):
        self.end = time.time()
        if self.params.debug:
            logger.info("Job %s: clientConnectionLost: %s" % (self.job.get_job_id(), reason))
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

if __name__=="__main__":
    from Parameters import Parameters
    from Jobs import Jobs
    import json
    from twisted.python import log
    import sys
    log.startLogging(open('log/smtptest.log', 'w'))
    jobs = Jobs()
    jobfile = open("test_smtpjob.txt")
    sys.stderr.write( "Testing %s\n" % sys.argv[0])
    params = Parameters()

    def check_smtp(job):
        print("Checking services for %s" % job.get_ip())
        for service in job.get_services():
            factory = SMTPFactory(params, job, service)
            job.set_factory(factory)
            factory.check_service()

    jobs_raw = json.load(jobfile)
    for job in jobs_raw:
        jobs.add(json.dumps(job))
        job = jobs.get_job()
        check_smtp(job)

    reactor.callLater(30, reactor.stop)
    reactor.run()
    print("Finished normally")
