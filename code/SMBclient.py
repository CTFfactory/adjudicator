#!/usr/bin/env python2
# SMB protocol negotiation checker for the Adjudicator
# Validates actual SMB protocol response (SMB1/SMB2 magic bytes),
# not just TCP connect, to prevent trivial spoofing.
from twisted.internet import reactor, protocol
from twisted.internet.defer import Deferred
from GenSocket import GenCoreFactory
import struct
import time
import sys
from logger import logger


# SMB2 Negotiate Protocol Request
# This sends a minimal SMB2 negotiate request that any SMB server will respond to.
# The response must contain either \xfeSMB (SMB2) or \xffSMB (SMB1) magic bytes.

def build_smb2_negotiate():
    """Build a minimal SMB2 Negotiate Protocol Request packet."""
    # NetBIOS Session Service header (will be prepended with length)
    # SMB2 Header
    smb2_header = b'\xfeSMB'           # Protocol ID
    smb2_header += struct.pack('<H', 64)  # Structure Size (64 bytes for SMB2 header)
    smb2_header += struct.pack('<H', 0)   # Credit Charge
    smb2_header += struct.pack('<L', 0)   # Status
    smb2_header += struct.pack('<H', 0)   # Command: Negotiate (0x0000)
    smb2_header += struct.pack('<H', 0)   # Credit Request
    smb2_header += struct.pack('<L', 0)   # Flags
    smb2_header += struct.pack('<L', 0)   # Next Command
    smb2_header += struct.pack('<Q', 1)   # Message ID
    smb2_header += struct.pack('<L', 0)   # Reserved (Process ID)
    smb2_header += struct.pack('<L', 0)   # Tree ID
    smb2_header += struct.pack('<Q', 0)   # Session ID
    smb2_header += b'\x00' * 16          # Signature

    # SMB2 Negotiate Request body
    negotiate_body = struct.pack('<H', 36)  # Structure Size
    negotiate_body += struct.pack('<H', 2)  # Dialect Count
    negotiate_body += struct.pack('<H', 1)  # Security Mode: signing enabled
    negotiate_body += struct.pack('<H', 0)  # Reserved
    negotiate_body += struct.pack('<L', 0)  # Capabilities
    negotiate_body += b'\x00' * 16         # Client GUID
    negotiate_body += struct.pack('<L', 0)  # Negotiate Context Offset
    negotiate_body += struct.pack('<H', 0)  # Negotiate Context Count
    negotiate_body += struct.pack('<H', 0)  # Reserved2
    # Dialects: SMB 2.0.2 and SMB 2.1
    negotiate_body += struct.pack('<H', 0x0202)  # SMB 2.0.2
    negotiate_body += struct.pack('<H', 0x0210)  # SMB 2.1

    smb2_packet = smb2_header + negotiate_body

    # NetBIOS Session Service header
    netbios_header = b'\x00'  # Message Type: Session Message
    netbios_header += struct.pack('>I', len(smb2_packet))[1:]  # Length (3 bytes, big-endian)

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
        # Send SMB2 Negotiate request
        negotiate_pkt = build_smb2_negotiate()
        self.transport.write(negotiate_pkt)

    def dataReceived(self, data):
        self.recv += data
        # Check for SMB magic bytes in response
        # SMB2: \xfeSMB, SMB1: \xffSMB
        if b'\xfeSMB' in self.recv or b'\xffSMB' in self.recv:
            logger.info("Job %s: Valid SMB response received from %s" % (
                self.job_id, self.factory.get_ip()))
            self.factory.add_data("SMB OK - valid protocol response\r\n")
            self.transport.loseConnection()
        elif len(self.recv) > 4:
            # Got data but no SMB magic - not a real SMB server
            logger.warning("Job %s: Invalid SMB response from %s" % (
                self.job_id, self.factory.get_ip()))
            self.factory.add_data("SMB FAIL - no valid SMB magic bytes in response\r\n")
            self.factory.add_fail("invalid SMB response")
            self.transport.loseConnection()


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
        connector = reactor.connectTCP(self.job.get_ip(), self.service.get_port(),
                                       self, self.params.get_timeout())
        deferred = self.get_deferred(connector)
        deferred.addCallback(self.service_pass)
        deferred.addErrback(self.service_fail)

    def service_pass(self, reason):
        self.service.pass_conn()
        logger.info("Job %s: SMB check passed for %s" % (self.job_id, self.ip))

    def service_fail(self, failure):
        self.service.fail_conn(failure)
        logger.warning("Job %s: SMB check failed for %s" % (self.job_id, self.ip))

    def clientConnectionFailed(self, connector, reason):
        self.end = time.time()
        if self.params.debug:
            logger.warning("Job %s: SMB clientConnectionFailed: %s" % (
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
            logger.info("Job %s: SMB clientConnectionLost: %s" % (
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
