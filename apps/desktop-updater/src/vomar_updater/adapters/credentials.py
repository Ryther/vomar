"""Native OS credential storage, with no file/plaintext fallback."""
class Credentials:
    def __init__(self,backend=None):
        import keyring
        self.backend=backend or keyring.get_keyring()
        if type(self.backend).__module__=='keyring.backends.chainer':
            allowed=('keyring.backends.SecretService','keyring.backends.macOS','keyring.backends.Windows')
            choices=[b for b in self.backend.backends if type(b).__module__ in allowed and b.priority>0]
            if choices:self.backend=choices[0]
    def _check(self):
        module=type(self.backend).__module__
        if module not in ('keyring.backends.SecretService','keyring.backends.macOS','keyring.backends.Windows') or self.backend.priority<=0:
            raise ValueError('OS credential store unavailable or locked. Unlock Keychain, Credential Manager or Secret Service; no plaintext fallback is used.')
    def set(self,service,account,password):
        self._check();self.backend.set_password('org.openvimar.'+service,account,password)
    def get(self,service,account):
        self._check();return self.backend.get_password('org.openvimar.'+service,account)
    def delete(self,service,account):
        self._check();self.backend.delete_password('org.openvimar.'+service,account)
