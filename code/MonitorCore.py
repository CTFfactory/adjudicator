#!/usr/bin/env python3
# requires:  https://pypi.python.org/pypi/http-parser
from twisted.internet import reactor, protocol, ssl
from http_parser.pyparser import HttpParser
from WebClient import WebServiceCheckFactory, JobFactory
from GenSocket import GenCheckFactory
from DNSclient import DNSclient
from Pingclient import PingProtocol
from FTPclient import FTP_client
from SMTPclient import SMTPFactory
from twisted.python import syslog
#from twisted.python import log
import traceback
import time
import sys
import os

class MonitorCore(object):

    def __init__(self, params, jobs):
        self.params = params
        self.resubmit_interval = 30
        self.jobs = jobs
        self.ping = "/usr/bin/ping"
        self.ping_cnt = str(5)
        self.jobs_done = []

    def get_job(self):
        factory = JobFactory(self.params, self.jobs, "get")
        if self.params.get_scheme() == "https":
            ssl_obj = ssl.CertificateOptions()
            reactor.connectSSL(self.params.get_ip(), self.params.get_port(), factory, ssl_obj,\
                                            self.params.get_timeout())
        elif self.params.get_scheme() == "http":
            reactor.connectTCP(self.params.get_sb_ip(), self.params.get_sb_port(), factory, \
                    self.params.get_timeout())
        else:
            raise Exception("Unknown scheme:  %s" % self.params.get_scheme())
        # Keep looking for more work
        reactor.callLater(1, self.get_job)

    def start_job(self):
        # Get the next job started
        job = self.jobs.get_job()
        if job:
            job_id = job.get_job_id()
            # DNS
            try:
                dnsobj = DNSclient(job)
            except:
                sys.stderr.write("Job %s: Failure starting job %s:\n" % (job_id, job.get_json_str()))
                traceback.print_tb()
            # Execute the query
            query_d = dnsobj.query()
            # Handle a DNS success - move on to ping
            query_d.addCallback(self.dns_pass, job, dnsobj)
            # Handle a DNS failure - fail the host
            query_d.addErrback(self.dns_fail, job, dnsobj)
            # We post the job when the timeout says, whatever is done or not.
            reactor.callLater(job.get_timeout(), self.timeout_job, job.get_job_id())
        reactor.callLater(0.01, self.start_job)

    def timeout_job(self, job_id):
        if job_id not in self.jobs_done:
            job = self.jobs.finish_job(job_id, "timeout")
            self.post_job(job)

    def finish_jobs(self):
        done_jobs = self.jobs.find_done_jobs()
        for job_id in done_jobs:
            job = self.jobs.finish_job(job_id, "job finished")
            self.post_job(job)
        reactor.callLater(0.1, self.finish_jobs)

    def post_job(self, job):
        factory = JobFactory(self.params, self.jobs, "put", job)
        connector = reactor.connectTCP(self.params.get_sb_ip(), self.params.get_sb_port(), factory, \
                           self.params.get_timeout())
        deferred = factory.get_deferred(connector)
        deferred.addCallback(self.job_submit_pass, job)
        deferred.addErrback(self.job_submit_fail, job)

    def proc_result(self, job, result):
        job_id = job.get_job_id()
        job_json = job.get_result_json_str()
        if len(result) > 300:
            filename = "sbe/%s.out" % time.strftime("%Y-%m-%d_%H%M%S", time.localtime(time.time()))
            fileobj = open(filename, "w")
            fileobj.write(result)
            fileobj.close()
            sys.stderr.write("Job %s: submitted, SBE response in file %s\n" % (job_id, filename))
        else:
            sys.stderr.write("Job %s: submitted, SBE response: %s\n" % (job_id, result))
        sys.stderr.write("Job %s: submitted: %s\n" % (job_id, job_json))

    def job_submit_pass(self, result, job):
        job_id = job.get_job_id()
        sys.stderr.write("Job %s: successfully submitted %s \n" % (job_id, result))
        self.proc_result(job, result)
        self.jobs_done.append(job_id)
        self.jobs.submitted_job(job_id)

    def job_submit_fail(self, failure, job):
        job_id = job.get_job_id()
        sys.stderr.write("Job %s: failed due to %s \n" % (job_id, failure.getErrorMessage()))
        if job.get_job_fail():
            sys.stderr.write("giving up.\n")
        else:
            sys.stderr.write("retrying in %s.\n" % self.resubmit_interval)
            reactor.callLater(self.resubmit_interval, self.post_job, job)

    def dns_fail(self, failure, job, dnsobj):
        # Do this if the DNS check failed
        job_id = job.get_job_id()
        sys.stderr.write("Job %s:  DNS failed. %s\n" % (job_id, failure))
        job = self.jobs.finish_job(job_id, "DNS failed")
        job.set_ip("fail")
        self.post_job(job)
        dnsobj.close()
        del dnsobj

    def dns_pass(self, result, job, dnsobj):
        jobid = job.get_job_id()
        print("Job %s:  DNS passed: %s" % (jobid, result))
        reactor.callLater(0.1, self.pinghost, job)
        dnsobj.close()
        del dnsobj

    def pinghost(self, job):
        pingobj = PingProtocol(job)
        ping_d = pingobj.getDeferred()
        ping_d.addCallback(self.ping_pass, job, pingobj)
        ping_d.addErrback(self.ping_fail, job, pingobj)
        pingobj.ping()

    def ping_pass(self, result, job, pingobj):
        jobid = job.get_job_id()
        sys.stderr.write("Job %s:  Ping passed. %s\n" % (jobid, result))
        reactor.callLater(1, self.check_services, job)
        del pingobj

    def ping_fail(self, failure, job, pingobj):
        jobid = job.get_job_id()
        sys.stderr.write("Job %s:  Ping failed. %s\n" % (jobid, failure))
        job = self.jobs.finish_job(job_id, "Ping failed")
        job.set_ip("fail")
        self.post_job(job)
        del pingobj

    def ftp_fail(self, failure, service, job_id):
        if "530 Login incorrect" in failure:
            sys.stderr.write("Job %s: Login failure\n" % job_id)
            service.fail_login()
        elif "Connection refused" in failure:
            sys.stderr.write("Job %s: Connection failure\n" % job_id)
            service.fail_conn("refused")
        else:
            sys.stderr.write("Job %s: Failure %s\n" % (job_id, failure))
            service.fail_conn(failure)

    def check_services(self, job):
        # Service walk
        for service in job.get_services():
            if "tcp" in service.get_proto():
                if service.get_application() == "http":
                    factory = WebServiceCheckFactory(self.params, job, service)
                    job.set_factory(factory)
                    factory.authenticate()
                elif service.get_application() == "ftp":
                    ftpobj = FTP_client(job, service, self.params, self.ftp_fail)
                    ftpobj.run()
                elif service.get_application() == "smtp":
                    factory = SMTPFactory(self.params, job, service)
                    job.set_factory(factory)
                    factory.check_service()
                else:
                    factory = GenCheckFactory(self.params, job, service)
                    connector = reactor.connectTCP(job.get_ip(), service.get_port(), factory, self.params.get_timeout())
                    deferred = factory.get_deferred(connector)
                    deferred.addCallback(self.gen_service_connect_pass, job, service)
                    deferred.addErrback(self.gen_service_connect_fail, job, service)
            else:
                # todo - handle the error by reporting the problem with the job in the json
                # and sending that back with the job report back.
                service.fail_conn("Unknown service protocol %s/%s" % (service.get_port(), service.get_proto()))

    def gen_service_connect_pass(self, result, job, service):
        service.pass_conn()
        proto = service.get_proto()
        port = service.get_port()
        jobid = job.get_job_id()
        sys.stderr.write("Job %s:  Service %s/%s passed. %s\n" % (jobid, port, proto, result))

    def gen_service_connect_fail(self, failure, job, service):
        service.fail_conn(failure)
        proto = service.get_proto()
        port = service.get_port()
        jobid = job.get_job_id()
        sys.stderr.write("Job %s:  Service %s/%s failed:\n\t%s\n" % (jobid, port, proto, failure))

def check_dir(dir):
    try:
        os.stat(dir)
    except OSError as e:
        if e.errno == 2:
            sys.stderr.write("No such directory %s, creating" % dir)
            os.mkdir(dir)
        else:
            sys.stderr.write("Directory %s - Unknown error%s: %s" % (e.errno, e.strerror))


if __name__=="__main__":
    # Testing with an artificial job file
    from Parameters import Parameters
    from Jobs import Jobs

    for dir in ("log", "raw", "sbe"):
        check_dir(dir)
    #log.startLogging(open('log/MonitorCore.log', 'w'))
    syslog.startLogging(prefix="Scorebot")
    params = Parameters()
    jobs = Jobs()
    mon_obj = MonitorCore(params, jobs)
    reactor.callLater(5, mon_obj.get_job)
    reactor.callLater(10, mon_obj.start_job)
    reactor.callLater(1, mon_obj.finish_jobs)
    reactor.run()
