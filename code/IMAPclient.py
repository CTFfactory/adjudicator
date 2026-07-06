import imaplib
import socket
from twisted.internet.defer import Deferred
from twisted.internet.threads import deferToThread
from logger import logger

def run_imap_check(ip, port, username, password, timeout):
    socket.setdefaulttimeout(timeout)
    client = None
    try:
        client = imaplib.IMAP4(ip, port)
        client.login(username, password)
        client.logout()
        return "IMAP login successful"
    except Exception as e:
        if client:
            try:
                client.logout()
            except Exception:
                pass
        raise Exception("IMAP check failed: %s" % e)

class IMAPCheckProtocol(object):
    def __init__(self, job, service):
        self.job = job
        self.service = service
        self.ip = job.get_ip()
        self.port = service.get_port()
        self.timeout = job.get_service_timeout() or 10
        self.d = Deferred()
        self.data = ""

    def getDeferred(self):
        return self.d

    def connect(self):
        auth = self.service.get_auth()
        username = auth.get("username", "") if auth else ""
        password = auth.get("password", "") if auth else ""

        if not username or not password:
            d = deferToThread(self.run_imap_conn_only)
        else:
            d = deferToThread(run_imap_check, self.ip, self.port, username, password, self.timeout)
        
        d.addCallback(self.success)
        d.addErrback(self.fail)

    def run_imap_conn_only(self):
        socket.setdefaulttimeout(self.timeout)
        client = None
        try:
            client = imaplib.IMAP4(self.ip, self.port)
            client.logout()
            return "IMAP connection successful"
        except Exception as e:
            if client:
                try:
                    client.logout()
                except Exception:
                    pass
            raise Exception("IMAP connect failed: %s" % e)

    def success(self, result):
        logger.info("Job %s: IMAP check passed for %s:%s: %s" % (self.job.get_job_id(), self.ip, self.port, result))
        self.data = result
        self.d.callback(self)

    def fail(self, failure):
        logger.warning("Job %s: IMAP check failed for %s:%s: %s" % (self.job.get_job_id(), self.ip, self.port, failure.getErrorMessage()))
        self.data = failure.getErrorMessage()
        self.d.errback(failure)
