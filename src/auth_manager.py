import secrets
import time
from io_config.logger import LOGGER
from io_config.config import HOST_PASSWORD

# In a production environment, we should consider using a database
stored_keys = {}

class AuthManager:

    def generate_unique_key(self):
        return secrets.token_hex(16)

    def store_key(self, key, expire_hours):
        stored_keys[key] = time.time() + 1000*60*60*expire_hours

    def authenticate(self, password):
        if password == HOST_PASSWORD:
            unique_key = self.generate_unique_key()
            expire_hours = 3
            self.store_key(unique_key,expire_hours)
            LOGGER.info(f"Successful authentication user")
            return {"key":unique_key,"expire_hours":expire_hours}
        else:
            LOGGER.warning(f"Failed authentication attempt")
            return None

    def validate_key(self, key):
        """Validate the provided key against the stored key."""
        stored = stored_keys.get(key)
        if stored and stored > time.time():
            LOGGER.info(f"Key validation successful for user")
            return True
        else:
            LOGGER.warning(f"Key validation failed for user")
            return False

auth_manager = AuthManager()
