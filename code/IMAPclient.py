import imaplib
import socket
from twisted.internet.defer import Deferred
from twisted.internet.threads import deferToThread
from logger import logger

def run_imap_check(ip, port, username, password, use_ssl, timeout):
    socket.setdefaulttimeout(timeout)
    client = None
    try:
        if use_ssl:
            client = imaplib.IMAP4_SSL(ip, port)
        else:
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
        use_ssl = auth.get("use_ssl", False) if auth else False

        if not username or not password:
            d = deferToThread(self.run_imap_conn_only, use_ssl)
        else:
            d = deferToThread(run_imap_check, self.ip, self.port, username, password, use_ssl, self.timeout)
        
        d.addCallback(self.success)
        d.addErrback(self.fail)

    def run_imap_conn_only(self, use_ssl):
        socket.setdefaulttimeout(self.timeout)
        client = None
        try:
            if use_ssl:
                client = imaplib.IMAP4_SSL(self.ip, self.port)
            else:
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
        err_msg = failure.getErrorMessage().lower()
        logger.warning("Job %s: IMAP check failed for %s:%s: %s" % (self.job.get_job_id(), self.ip, self.port, err_msg))
        self.data = failure.getErrorMessage()
        if "login failed" in err_msg or "auth" in err_msg or "credential" in err_msg or "login" in err_msg or "no " in err_msg or "bad " in err_msg:
            self.job_status = "yellow"
            self.d.callback(self)
        else:
            self.job_status = "fail"
            self.d.errback(failure)
