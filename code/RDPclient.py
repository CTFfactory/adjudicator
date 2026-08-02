#!/usr/bin/env python2
# RDP X.224 Connection Request checker for the Adjudicator
from twisted.internet import reactor, protocol
from twisted.internet.defer import Deferred
from GenSocket import GenCoreFactory
from BaseClient import BaseProtocol
import struct
import time
import sys
from logger import logger


def build_x224_connection_request():
    """Build an X.224 Connection Request PDU wrapped in TPKT header."""
    rdp_neg_req = b'\x01'
    rdp_neg_req += b'\x00'
    rdp_neg_req += struct.pack('<H', 8)
    rdp_neg_req += struct.pack('<L', 0x00000001)

    x224_cr = b'\xe0'
    x224_cr += struct.pack('>H', 0)
    x224_cr += struct.pack('>H', 0)
    x224_cr += b'\x00'

    cookie = b'Cookie: mstshash=scorebot\r\n'
    x224_payload = x224_cr + cookie + rdp_neg_req
    x224_pdu = struct.pack('B', len(x224_payload)) + x224_payload

    tpkt_length = 4 + len(x224_pdu)
    tpkt_header = struct.pack('B', 3)
    tpkt_header += struct.pack('B', 0)
    tpkt_header += struct.pack('>H', tpkt_length)

    return tpkt_header + x224_pdu


class RDPClient(protocol.Protocol):

    def __init__(self, factory):
        self.factory = factory
        self.job_id = self.factory.get_job_id()
        self.recv = b''

    def TimedOut(self):
        self.transport.loseConnection()
        self.factory.add_fail("timeout")

    def connectionMade(self):
        logger.info("Job %s: RDP connection made to %s:%s" % (
            self.job_id, self.factory.get_ip(), self.factory.get_port()))
        reactor.callLater(self.factory.get_timeout(), self.TimedOut)
        cr_pdu = build_x224_connection_request()
        self.transport.write(cr_pdu)

    def dataReceived(self, data):
        self.recv += data
        if len(self.recv) < 4:
            return
        version = struct.unpack('B', self.recv[0:1])[0]
        if version != 3:
            logger.warning("Job %s: Invalid TPKT version %d from %s" % (
                self.job_id, version, self.factory.get_ip()))
            self.factory.add_data("RDP FAIL - invalid TPKT version: %d\r\n" % version)
            self.factory.add_fail("invalid RDP response")
            self.transport.loseConnection()
            return

        tpkt_length = struct.unpack('>H', self.recv[2:4])[0]
        if len(self.recv) < tpkt_length:
            return

        if len(self.recv) > 5:
            x224_code = struct.unpack('B', self.recv[5:6])[0]
            if (x224_code & 0xf0) == 0xd0:
                logger.info("Job %s: Valid RDP X.224 CC response from %s" % (
                    self.job_id, self.factory.get_ip()))
                self.factory.add_data("RDP OK - valid X.224 Connection Confirm received\r\n")
                self.transport.loseConnection()
                return

        logger.warning("Job %s: Invalid RDP response from %s (no X.224 CC)" % (
            self.job_id, self.factory.get_ip()))
        self.factory.add_data("RDP FAIL - no valid X.224 Connection Confirm\r\n")
        self.factory.add_fail("invalid RDP response")
        self.transport.loseConnection()


class RDPSubprocessProtocol(BaseProtocol):
    def __init__(self, job, service=None):
        super(RDPSubprocessProtocol, self).__init__(job, service)
        self.prog = "/usr/bin/xfreerdp"

    def connect(self):
        auth = self.service.get_auth()
        username = auth.get("username", "")
        password = auth.get("password", "")
        args = [self.prog, "/v:" + self.ipaddr + ":" + str(self.service.get_port()), "/u:" + username, "/p:" + password, "+auth-only", "/cert-ignore"]
        reactor.spawnProcess(self, self.prog, args)

    def processEnded(self, reason):
        exit_code = 0
        if hasattr(reason.value, 'exitCode') and reason.value.exitCode is not None:
            exit_code = reason.value.exitCode

        self.exit_code = exit_code
        err_msg = self.data.lower()
        if "logon failure" in err_msg or "authentication failure" in err_msg or "errconnect_logon_failure" in err_msg:
            self.job_status = "yellow"
            self.d.callback(self)
        elif exit_code == 0:
            self.job_status = "pass"
            self.d.callback(self)
        elif exit_code == 1:
            self.job_status = "yellow"
            self.d.callback(self)
        else:
            self.job_status = "fail"
            self.d.errback(reason)


class RDPCheckFactory(GenCoreFactory):

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
        return RDPClient(self)

    def check_service(self):
        auth = self.service.get_auth() if self.service else None
        username = auth.get("username", "") if auth else ""
        password = auth.get("password", "") if auth else ""

        if username and password:
            proto = RDPSubprocessProtocol(self.job, self.service)
            proto.d.addCallback(self.subprocess_pass)
            proto.d.addErrback(self.subprocess_fail)
            proto.connect()
        else:
            connector = reactor.connectTCP(self.job.get_ip(), self.service.get_port(),
                                           self, self.params.get_timeout())
            deferred = self.get_deferred(connector)
            deferred.addCallback(self.service_pass)
            deferred.addErrback(self.service_fail)

    def service_pass(self, reason):
        self.service.pass_conn()
        logger.info("Job %s: RDP check passed for %s" % (self.job_id, self.ip))

    def service_fail(self, failure):
        self.service.fail_login()
        logger.warning("Job %s: RDP check failed for %s" % (self.job_id, self.ip))

    def subprocess_pass(self, proto):
        self.service.pass_conn()
        logger.info("Job %s: RDP authentication check passed for %s" % (self.job_id, self.ip))

    def subprocess_fail(self, failure):
        self.service.fail_login()
        logger.warning("Job %s: RDP authentication check failed for %s" % (self.job_id, self.ip))

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
