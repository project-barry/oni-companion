"""Service identity (plan 4.1): instance id, adjective-animal name, key pair + self-signed certificate.

The certificate's SHA-256 fingerprint is the real identity; id and name are labels anyone can copy.
The certificate is made with the system `openssl` command (the stdlib cannot create one), EC P-256,
10 years, subject CN=<instanceId>. Files live in <data folder>/connect/ with mode 600:
identity.json, key.pem, cert.pem. The key and certificate are written last and renamed into place, so
cert.pem existing means the pair is complete.
"""
import hashlib
import os
import random
import re
import shutil
import ssl
import subprocess
import tempfile
import uuid

from .. import __version__
from .files import read_json, write_atomic, write_json
from .words import ADJECTIVES, ANIMALS

API_VERSION = 1
UUID4 = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
DAYS = 3650


class IdentityError(Exception):
    """The certificate could not be made (openssl missing or failing). The message is for the user."""


def random_name(rng=None):
    rng = rng or random.SystemRandom()
    return "%s-%s" % (rng.choice(ADJECTIVES), rng.choice(ANIMALS))


def fingerprint_of_pem(cert_pem_text):
    return hashlib.sha256(ssl.PEM_cert_to_DER_cert(cert_pem_text)).hexdigest()


def _openssl_conf(instance_id):
    # Our own minimal config: does not depend on a system openssl.cnf (missing on small images).
    return ("[req]\ndistinguished_name=dn\nprompt=no\nx509_extensions=ext\n"
            "[dn]\nCN=%s\n"
            "[ext]\nbasicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature\n"
            "extendedKeyUsage=serverAuth\n" % instance_id)


def make_key_and_cert(instance_id, key_path, cert_path, openssl="openssl"):
    exe = shutil.which(openssl) if os.sep not in openssl else openssl
    if not exe:
        raise IdentityError("The openssl command is missing, so this device cannot make its certificate.")
    d = os.path.dirname(key_path)
    os.makedirs(d, mode=0o700, exist_ok=True)
    old = os.umask(0o077)
    work = tempfile.mkdtemp(prefix=".mk-", dir=d)
    try:
        conf = os.path.join(work, "req.cnf")
        with open(conf, "w") as f:
            f.write(_openssl_conf(instance_id))
        k, c = os.path.join(work, "key.pem"), os.path.join(work, "cert.pem")
        try:
            subprocess.run([exe, "ecparam", "-name", "prime256v1", "-genkey", "-noout", "-out", k],
                           check=True, capture_output=True, timeout=30)
            subprocess.run([exe, "req", "-new", "-x509", "-key", k, "-sha256", "-days", str(DAYS),
                            "-config", conf, "-out", c], check=True, capture_output=True, timeout=30)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as e:
            detail = getattr(e, "stderr", b"") or b""
            raise IdentityError("openssl could not make the certificate. %s" % detail.decode("utf-8", "replace").strip()[:200])
        with open(c) as f:
            fingerprint_of_pem(f.read())      # must parse
        os.chmod(k, 0o600)
        os.chmod(c, 0o600)
        os.replace(k, key_path)
        os.replace(c, cert_path)                # last: its existence means the pair is complete
    finally:
        shutil.rmtree(work, ignore_errors=True)
        os.umask(old)


class Identity:
    """Loads or creates the identity. Not thread safe by itself; the manager holds a lock around it."""

    def __init__(self, folder, openssl="openssl", rng=None):
        self.folder = folder
        self.openssl = openssl
        self.rng = rng
        self.instance_id = None
        self.name = None
        self.fingerprint = None
        self._load()

    @property
    def key_path(self):
        return os.path.join(self.folder, "key.pem")

    @property
    def cert_path(self):
        return os.path.join(self.folder, "cert.pem")

    @property
    def meta_path(self):
        return os.path.join(self.folder, "identity.json")

    @property
    def exists(self):
        return self.fingerprint is not None

    def _load(self):
        meta = read_json(self.meta_path, {})
        try:
            iid, name = meta.get("instanceId"), meta.get("name")
            if not (isinstance(iid, str) and UUID4.match(iid) and isinstance(name, str)
                    and re.fullmatch(r"[a-z]{2,20}-[a-z]{2,20}", name)):
                return
            with open(self.cert_path) as f:
                fp = fingerprint_of_pem(f.read())
            if not os.path.isfile(self.key_path):
                return
        except (OSError, ValueError, AttributeError):
            return
        self.instance_id, self.name, self.fingerprint = iid, name, fp

    def ensure(self):
        if not self.exists:
            self._create()
        return self

    def _create(self):
        iid = str(uuid.uuid4())
        name = random_name(self.rng)
        make_key_and_cert(iid, self.key_path, self.cert_path, self.openssl)
        write_json(self.meta_path, {"instanceId": iid, "name": name})
        self._load()
        if not self.exists:
            raise IdentityError("The new certificate could not be read back.")

    def reset(self):
        """New id, name and key. The old files are removed first, so a crash in between leaves no identity,
        never a half old / half new one."""
        for p in (self.meta_path, self.cert_path, self.key_path):
            try:
                os.unlink(p)
            except OSError:
                pass
        self.instance_id = self.name = self.fingerprint = None
        self._create()

    def body(self):
        """The Identity reply (api.schema.json). Labels only."""
        self.ensure()
        return {"instanceId": self.instance_id, "name": self.name, "fingerprint": self.fingerprint,
                "fingerprintTag": self.fingerprint[:4].upper(), "apiVersion": API_VERSION,
                "coreVersion": __version__}

    def tls_context(self):
        self.ensure()
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.load_cert_chain(self.cert_path, self.key_path)
        return ctx
