#!/usr/bin/env python2
# RDP X.224 Connection Request checker for the Adjudicator
# Validates RDP protocol negotiation by sending a TPKT/X.224 Connection
# Request and checking for a valid TPKT/X.224 Connection Confirm response.
from twisted.internet import reactor, protocol
from twisted.internet.defer import Deferred
from GenSocket import GenCoreFactory
import struct
import time
import sys
from logger import logger


def build_x224_connection_request():
    """Build an X.224 Connection Request PDU wrapped in TPKT header.

    This is the initial RDP negotiation packet that any RDP server
    must respond to with a Connection Confirm (CC) PDU.
    """
    # RDP Negotiation Request (TYPE_RDP_NEG_REQ)
    rdp_neg_req = b'\x01'              # type: TYPE_RDP_NEG_REQ
    rdp_neg_req += b'\x00'             # flags
    rdp_neg_req += struct.pack('<H', 8)  # length: 8 bytes
    rdp_neg_req += struct.pack('<L', 0x00000001)  # requestedProtocols: PROTOCOL_SSL

    # X.224 Connection Request (CR) TPDU
    # RFC 905, section 13.3
    x224_cr = b'\xe0'                  # CR TPDU code (1110 0000)
    x224_cr += struct.pack('>H', 0)    # DST-REF
    x224_cr += struct.pack('>H', 0)    # SRC-REF
    x224_cr += b'\x00'                 # Class option

    # Cookie/token (optional, but helps compatibility)
    cookie = b'Cookie: mstshash=scorebot\r\n'

    x224_payload = x224_cr + cookie + rdp_neg_req

    # X.224 length indicator (length of everything after the LI byte itself)
    x224_pdu = struct.pack('B', len(x224_payload)) + x224_payload

    # TPKT Header (RFC 1006)
    tpkt_length = 4 + len(x224_pdu)  # 4 = TPKT header size
    tpkt_header = struct.pack('B', 3)   # version: 3
    tpkt_header += struct.pack('B', 0)  # reserved: 0
    tpkt_header += struct.pack('>H', tpkt_length)  # length (big-endian)

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
        # Send X.224 Connection Request
        cr_pdu = build_x224_connection_request()
        self.transport.write(cr_pdu)

    def dataReceived(self, data):
        self.recv += data
        # Need at least 4 bytes for TPKT header
        if len(self.recv) < 4:
            return
        # Validate TPKT header
        # Byte 0: version (must be 3)
        # Byte 1: reserved (0)
        # Bytes 2-3: length (big-endian)
        version = struct.unpack('B', self.recv[0:1])[0]
        if version != 3:
            logger.warning("Job %s: Invalid TPKT version %d from %s" % (
                self.job_id, version, self.factory.get_ip()))
            self.factory.add_data("RDP FAIL - invalid TPKT version: %d\r\n" % version)
            self.factory.add_fail("invalid RDP response")
            self.transport.loseConnection()
            return

        tpkt_length = struct.unpack('>H', self.recv[2:4])[0]

        # Wait for full TPKT packet
        if len(self.recv) < tpkt_length:
            return

        # Check for X.224 Connection Confirm (CC) TPDU
        # The CC TPDU code is 0xd0 (1101 0000)
        if len(self.recv) > 5:
            # Byte 4 is the X.224 length indicator
            # Byte 5 is the X.224 TPDU code
            x224_code = struct.unpack('B', self.recv[5:6])[0]
            if (x224_code & 0xf0) == 0xd0:
                logger.info("Job %s: Valid RDP X.224 CC response from %s" % (
                    self.job_id, self.factory.get_ip()))
                self.factory.add_data("RDP OK - valid X.224 Connection Confirm received\r\n")
                self.transport.loseConnection()
                return

        # If we got a full TPKT but no valid CC, it's not a real RDP server
        logger.warning("Job %s: Invalid RDP response from %s (no X.224 CC)" % (
            self.job_id, self.factory.get_ip()))
        self.factory.add_data("RDP FAIL - no valid X.224 Connection Confirm\r\n")
        self.factory.add_fail("invalid RDP response")
        self.transport.loseConnection()


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
        connector = reactor.connectTCP(self.job.get_ip(), self.service.get_port(),
                                       self, self.params.get_timeout())
        deferred = self.get_deferred(connector)
        deferred.addCallback(self.service_pass)
        deferred.addErrback(self.service_fail)

    def service_pass(self, reason):
        self.service.pass_conn()
        logger.info("Job %s: RDP check passed for %s" % (self.job_id, self.ip))

    def service_fail(self, failure):
        self.service.fail_conn(failure)
        logger.warning("Job %s: RDP check failed for %s" % (self.job_id, self.ip))

    def clientConnectionFailed(self, connector, reason):
        self.end = time.time()
        if self.params.debug:
            logger.warning("Job %s: RDP clientConnectionFailed: %s" % (
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
            logger.info("Job %s: RDP clientConnectionLost: %s" % (
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
