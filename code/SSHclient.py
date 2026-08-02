#!/usr/bin/env python2
from twisted.internet import reactor
from twisted.internet.defer import Deferred
from twisted.internet.threads import deferToThread
from BaseClient import BaseProtocol
from logger import logger
from io import StringIO
import sys
import re

try:
    import paramiko
    HAS_PARAMIKO = True
except ImportError:
    HAS_PARAMIKO = False

def run_ssh_auth_check(ip, port, username, password, private_key, timeout):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        if private_key:
            pkey = None
            # Handle unicode key string for Python 2
            key_io = StringIO(unicode(private_key))
            for cls in (paramiko.RSAKey, paramiko.Ed25519Key, paramiko.ECDSAKey, paramiko.DSSKey):
                try:
                    key_io.seek(0)
                    pkey = cls.from_private_key(key_io)
                    break
                except Exception:
                    continue
            if not pkey:
                raise Exception("Invalid or unsupported SSH private key format")
            client.connect(ip, port=port, username=username, pkey=pkey, timeout=timeout)
        else:
            client.connect(ip, port=port, username=username, password=password, timeout=timeout)
        client.close()
        return "SSH login successful"
    except Exception as e:
        try:
            client.close()
        except Exception:
            pass
        raise Exception("SSH check failed: %s" % e)

class SSHProtocol(BaseProtocol):

    def __init__(self, job, service=None):
        super(SSHProtocol, self).__init__(job, service)
        self.success_re = re.compile("(SSH OK .*)")
        self.refused_re = re.compile("(.*Connection refused)")
        self.prog = "/usr/lib/nagios/plugins/check_ssh"

    def connect(self):
        auth = self.service.get_auth() if self.service else None
        username = auth.get("username", "") if auth else ""
        password = auth.get("password", "") if auth else ""
        private_key = auth.get("private_key", "") if auth else ""

        if username and (password or private_key) and HAS_PARAMIKO:
            d = deferToThread(run_ssh_auth_check, self.ipaddr, self.service.get_port(), username, password, private_key, 10)
            d.addCallback(self.ssh_success)
            d.addErrback(self.ssh_fail)
        else:
            args = [self.prog, "-H", self.ipaddr]
            if self.service:
                args += ["-p", str(self.service.get_port())]
            reactor.spawnProcess(self, self.prog, args)

    def ssh_success(self, result):
        logger.info("Job %s: SSH check passed: %s" % (self.job.get_job_id(), result))
        self.job_status = "pass"
        self.d.callback(self)

    def ssh_fail(self, failure):
        err_msg = failure.getErrorMessage().lower()
        logger.warning("Job %s: SSH check failed: %s" % (self.job.get_job_id(), err_msg))
        if "authentication failed" in err_msg or "bad authentication" in err_msg or "permission denied" in err_msg or "auth" in err_msg:
            self.job_status = "yellow"
            self.d.callback(self)
        else:
            self.job_status = "fail"
            self.d.errback(failure)
