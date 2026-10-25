"""One-off: install local SSH public key on the kb-manager CentOS VM using the password.

Usage: uv run --from paramiko python -I ssh_bootstrap.py <host> <password> <pubkey file>
The password is taken from argv so it is not hard-coded in this file.
"""
import sys
import paramiko

host, password, pub_path = sys.argv[1], sys.argv[2], sys.argv[3]
pub = open(pub_path, encoding="utf-8").read().strip()
cmd = (
    "mkdir -p ~/.ssh && chmod 700 ~/.ssh && "
    f"(grep -qxF '{pub}' ~/.ssh/authorized_keys 2>/dev/null || echo '{pub}' >> ~/.ssh/authorized_keys) && "
    "chmod 600 ~/.ssh/authorized_keys && echo KEY_INSTALLED"
)
client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(host, username="root", password=password, timeout=10, allow_agent=False, look_for_keys=False)
_, stdout, stderr = client.exec_command(cmd)
print(stdout.read().decode(errors="replace"), end="")
print(stderr.read().decode(errors="replace"), end="")
client.close()
