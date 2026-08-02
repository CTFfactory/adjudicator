#!/usr/bin/env python2
# SMB protocol negotiation checker for the Adjudicator
from twisted.internet import reactor, protocol
from twisted.internet.defer import Deferred
from GenSocket import GenCoreFactory
from BaseClient import BaseProtocol
import struct
import time
import sys
from logger import logger

def build_smb2_negotiate():
    """Build a pure SMB2/SMB3 negotiate request packet to support modern Windows and Samba."""
    # 1. Build SMB2 Header (64 bytes)
    header = struct.pack(
        '<4sHHIHHIIQQQ16s',
        b'\xfeSMB',       # ProtocolId
        64,              # StructureSize
        0,               # CreditCharge
        0,               # Status
        0,               # Command (Negotiate)
        31,              # CreditRequest
        0,               # Flags
        0,               # NextCommand
        0,               # MessageId
        0,               # Reserved/AsyncId
        0,               # SessionId
        b'\x00' * 16     # Signature
    )

    # 2. Build SMB2 Negotiate Request (36 bytes + dialects)
    dialects = [0x0202, 0x0210, 0x0300, 0x0302]  # SMB 2.0.2, 2.1, 3.0, 3.0.2
    req = struct.pack(
        '<HHHHI16sIHH',
        36,              # StructureSize
        len(dialects),   # DialectCount
        1,               # SecurityMode (Signing enabled)
        0,               # Reserved
        0,               # Capabilities
        b'\x00' * 16,    # ClientGuid
        0,               # NegotiateContextOffset
        0,               # NegotiateContextCount
        0                # Reserved2
    )
    req += struct.pack(f'<{len(dialects)}H', *dialects)

    pkt = header + req
    # NetBIOS Session Header: 1-byte type (0x00), followed by 3-byte length
    netbios = b'\x00' + struct.pack('>I', len(pkt))[1:]
    return netbios + pkt



class SMBClient(protocol.Protocol):

    def __init__(self, factory):
        self.factory = factory
        self.job_id = self.factory.get_job_id()
        self.recv = b''

    def TimedOut(self):
        self.transport.loseConnection()
        self.factory.add_fail("timeout")

    def connectionMade(self):
        logger.info("Job %s: SMB connection made to %s:%s" % (
            self.job_id, self.factory.get_ip(), self.factory.get_port()))
        reactor.callLater(self.factory.get_timeout(), self.TimedOut)
        negotiate_pkt = build_smb2_negotiate()
        self.transport.write(negotiate_pkt)

    def dataReceived(self, data):
        self.recv += data
        if b'\xfeSMB' in self.recv or b'\xffSMB' in self.recv:
            logger.info("Job %s: Valid SMB response received from %s" % (
                self.job_id, self.factory.get_ip()))
            self.factory.add_data("SMB OK - valid protocol response\r\n")
            self.transport.loseConnection()
        elif len(self.recv) >= 8:
            logger.warning("Job %s: Invalid SMB response from %s" % (
                self.job_id, self.factory.get_ip()))
            self.factory.add_data("SMB FAIL - no valid SMB magic bytes in response\r\n")
            self.factory.add_fail("invalid SMB response")
            self.transport.loseConnection()


class SMBSubprocessProtocol(BaseProtocol):
    def __init__(self, job, service=None):
        super(SMBSubprocessProtocol, self).__init__(job, service)
        self.prog = "/usr/bin/smbclient"

    def connect(self):
        auth = self.service.get_auth()
        username = auth.get("username", "")
        password = auth.get("password", "")
        domain = auth.get("domain", "")
        args = [self.prog, "//" + self.ipaddr + "/IPC$", "-U", username + "%" + password, "-p", str(self.service.get_port()), "-c", "exit"]
        if domain:
            args += ["-W", domain]
        reactor.spawnProcess(self, self.prog, args)

    def processEnded(self, reason):
        exit_code = 0
        if hasattr(reason.value, 'exitCode') and reason.value.exitCode is not None:
            exit_code = reason.value.exitCode

        self.exit_code = exit_code
        err_msg = self.data.lower()
        if "logon_failure" in err_msg or "access_denied" in err_msg or "access denied" in err_msg or "login failed" in err_msg:
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


class SMBCheckFactory(GenCoreFactory):

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
        return SMBClient(self)

    def check_service(self):
        auth = self.service.get_auth() if self.service else None
        username = auth.get("username", "") if auth else ""
        password = auth.get("password", "") if auth else ""

        if username and password:
            proto = SMBSubprocessProtocol(self.job, self.service)
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
        logger.info("Job %s: SMB check passed for %s" % (self.job_id, self.ip))

    def service_fail(self, failure):
        self.service.fail_conn(failure.getErrorMessage())
        logger.warning("Job %s: SMB check failed for %s" % (self.job_id, self.ip))

    def subprocess_pass(self, proto):
        self.service.pass_conn()
        logger.info("Job %s: SMB authentication check passed for %s" % (self.job_id, self.ip))

    def subprocess_fail(self, failure):
        self.service.fail_login()
        logger.warning("Job %s: SMB authentication check failed for %s" % (self.job_id, self.ip))

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
