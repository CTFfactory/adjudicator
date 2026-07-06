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
    """Build a minimal SMB2 Negotiate Protocol Request packet."""
    smb2_header = b'\xfeSMB'           # Protocol ID
    smb2_header += struct.pack('<H', 64)  # Structure Size
    smb2_header += struct.pack('<H', 0)   # Credit Charge
    smb2_header += struct.pack('<L', 0)   # Status
    smb2_header += struct.pack('<H', 0)   # Command: Negotiate (0x0000)
    smb2_header += struct.pack('<H', 0)   # Credit Request
    smb2_header += struct.pack('<L', 0)   # Flags
    smb2_header += struct.pack('<L', 0)   # Next Command
    smb2_header += struct.pack('<Q', 1)   # Message ID
    smb2_header += struct.pack('<L', 0)   # Reserved
    smb2_header += struct.pack('<L', 0)   # Tree ID
    smb2_header += struct.pack('<Q', 0)   # Session ID
    smb2_header += b'\x00' * 16          # Signature

    negotiate_body = struct.pack('<H', 36)  # Structure Size
    negotiate_body += struct.pack('<H', 2)  # Dialect Count
    negotiate_body += struct.pack('<H', 1)  # Security Mode
    negotiate_body += struct.pack('<H', 0)  # Reserved
    negotiate_body += struct.pack('<L', 0)  # Capabilities
    negotiate_body += b'\x00' * 16         # Client GUID
    negotiate_body += struct.pack('<L', 0)  # Negotiate Context Offset
    negotiate_body += struct.pack('<H', 0)  # Negotiate Context Count
    negotiate_body += struct.pack('<H', 0)  # Reserved2
    negotiate_body += struct.pack('<H', 0x0202)  # SMB 2.0.2
    negotiate_body += struct.pack('<H', 0x0210)  # SMB 2.1

    smb2_packet = smb2_header + negotiate_body
    netbios_header = b'\x00'
    netbios_header += struct.pack('>I', len(smb2_packet))[1:]

    return netbios_header + smb2_packet


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
        elif len(self.recv) > 4:
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
        args = [self.prog, "//" + self.ipaddr + "/IPC$", "-U", username + "%" + password, "-p", str(self.service.get_port()), "-c", "exit"]
        reactor.spawnProcess(self, self.prog, args)


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
        self.service.fail_login()
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
