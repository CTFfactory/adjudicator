import smtplib
import socket
from twisted.internet.threads import deferToThread
from logger import logger

def run_smtp_check(ip, port, username, password, use_ssl, timeout):
    socket.setdefaulttimeout(timeout)
    client = None
    try:
        if use_ssl:
            client = smtplib.SMTP_SSL(ip, port)
        else:
            client = smtplib.SMTP(ip, port)
        client.ehlo()
        if not use_ssl and client.has_extn("starttls"):
            client.starttls()
            client.ehlo()
        client.login(username, password)
        client.quit()
        return "SMTP login successful"
    except Exception as e:
        if client:
            try:
                client.quit()
            except Exception:
                pass
        raise Exception("SMTP check failed: %s" % e)

def run_smtp_conn_only(ip, port, use_ssl, timeout):
    socket.setdefaulttimeout(timeout)
    client = None
    try:
        if use_ssl:
            client = smtplib.SMTP_SSL(ip, port)
        else:
            client = smtplib.SMTP(ip, port)
        client.ehlo()
        client.quit()
        return "SMTP connection successful"
    except Exception as e:
        if client:
            try:
                client.quit()
            except Exception:
                pass
        raise Exception("SMTP connect failed: %s" % e)

class SMTPFactory(object):

    def __init__(self, params, job, service):
        self.params = params
        self.job = job
        self.job_id = self.job.get_job_id()
        self.ip = self.job.get_ip()
        self.service = service
        self.port = self.service.get_port()
        self.timeout = self.params.get_timeout() or 10

    def check_service(self):
        auth = self.service.get_auth()
        username = auth.get("username", "") if auth else ""
        password = auth.get("password", "") if auth else ""
        use_ssl = auth.get("use_ssl", False) if auth else False

        if not username or not password:
            d = deferToThread(run_smtp_conn_only, self.ip, self.port, use_ssl, self.timeout)
        else:
            d = deferToThread(run_smtp_check, self.ip, self.port, username, password, use_ssl, self.timeout)
        
        d.addCallback(self.service_pass)
        d.addErrback(self.service_fail)

    def service_pass(self, result):
        logger.info("Job %s: SMTP check passed for %s:%s: %s" % (self.job_id, self.ip, self.port, result))
        self.service.pass_conn()

    def service_fail(self, failure):
        err_msg = failure.getErrorMessage().lower()
        logger.warning("Job %s: SMTP check failed for %s:%s: %s" % (self.job_id, self.ip, self.port, err_msg))
        if "authenticationerror" in err_msg or "auth" in err_msg or "login failed" in err_msg or "credentials" in err_msg:
            self.service.pass_degraded()
        else:
            self.service.fail_login()
