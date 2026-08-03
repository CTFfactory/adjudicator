#!/usr/bin/env python2
from twisted.internet import reactor, protocol
from twisted.internet.defer import Deferred
from Jobs import Jobs
import sys
import re

class PingProtocol(protocol.ProcessProtocol):

    def __init__(self, job, count=str(5)):
        self.job = job
        self.ipaddr = self.job.get_ip()
        self.data = ""
        self.received_re = re.compile("(\d) received")
        self.transmitted_re = re.compile("(\d) packets transmitted")
        self.recv = 0
        self.fail = 0
        self.trans = 0
        self.d = Deferred()
        self.ping_prog = "/usr/bin/ping"
        self.count = count

    def ping(self):
        reactor.spawnProcess(self, self.ping_prog, [self.ping_prog, "-c", self.count, self.ipaddr])

    def getDeferred(self):
        return self.d

    def outReceived(self, data):
        if type(data) == type(b'a'):
            self.data += data.decode('utf-8', errors='replace')+"\r\n"
        else:
            self.data += data

    def outConnectionLost(self):
        recv_match = self.received_re.search(self.data)
        trans_match = self.transmitted_re.search(self.data)
        self.recv = int(recv_match.group(1)) if recv_match else 0
        self.trans = int(trans_match.group(1)) if trans_match else int(self.count)
        self.lost = self.trans - self.recv
        self.job.set_ping_sent(self.trans)
        self.job.set_ping_respond(self.recv)
        self.ratio = float(self.recv) / self.trans if self.trans > 0 else 0.0
        if 0 <= self.ratio <= 100:
            self.d.callback(self)
        else:
            self.d.errback()

    def get_recv(self):
        return self.recv

    def get_lost(self):
        return self.lost

if __name__=="__main__":
    # Plain logfile writing
    #from twisted.python import log
    #log.startLogging(open('log/pingtest.log', 'w'))
    # Syslog FTW
    from twisted.python import syslog
    syslog.startLogging()
    def check_services(result, pingobj):
        try:
            print("Got %d good pings" % pingobj.get_recv())
            print("Got %d bad pings" % pingobj.get_fail())
        except:
            log.err()
    def ping_fail(failure):
        print("It failed!!")
    import sys
    ipaddr = sys.argv[1]
    count = str(5)
    sys.stderr.write( "Testing %s\n" % sys.argv[0])
    json_str1 = '{"pk": 120, "model": "scorebot.job", "fields": {"job_dns": ["10.100.101.60"], "job_host": {"host_services": [{"service_protocol": "tcp", "service_port": 80, "service_connect": "ERROR", "service_content": {}}], "host_ping_ratio": 50, "host_fqdn": "www.alpha.net"}}, "status": "job"}'
    jobs_obj = Jobs()
    jobs_obj.add(json_str1)
    job = jobs_obj.get_job()
    job.set_ip("10.100.101.60")
    pingobj = PingProtocol(job, count)
    ping_d = pingobj.getDeferred()
    ping_d.addCallback(check_services, pingobj)
    ping_d.addErrback(ping_fail)
    pingobj.ping()
    #reactor.spawnProcess(pingobj, ping, [ping, "-c", count, ipaddr])
    reactor.callLater(8, reactor.stop)
    reactor.run()

