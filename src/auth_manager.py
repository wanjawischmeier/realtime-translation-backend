import secrets
import time
from io_config.logger import LOGGER
from io_config.config import HOST_PASSWORD,ADMIN_PASSWORD

# In a production environment, we should consider using a database
stored_keys = {}

class AuthManager:

    def generate_unique_key(self):
        return secrets.token_hex(16)

    def store_key(self, key, expire_hours, power):
        stored_keys[key] = {
            "key":key,
            "expire":time.time() + 1000*60*60*expire_hours,
            "power":power
        }

    def login(self, password, role=None):
        if (password == HOST_PASSWORD or password == ADMIN_PASSWORD) and (role is None or (role != "admin" or password == ADMIN_PASSWORD)):
            unique_key = self.generate_unique_key()
            expire_hours = 3
            power = "admin" if ADMIN_PASSWORD == password else "host"
            self.store_key(unique_key,expire_hours,power)
            LOGGER.info(f"Successful authentication user")
            return {"key":unique_key,"expire_hours":expire_hours,"power":power}
        else:
            LOGGER.warning(f"Failed authentication attempt")
            return None

    def get_entry(self, key):
        stored = stored_keys.get(key)
        if stored and stored["expire"] > time.time():
            return {"key":stored["key"],"power":stored["power"]}
        else:
            return None

    def validate_key(self, key, power="host"):
        """Validate the provided key against the stored key."""
        stored = self.get_entry(key)
        if stored and stored is not None:
            
            if power is not "admin" or stored["power"] is power:
                return True
                LOGGER.info(f"Key validation successful for user and enough power")
            else:
                LOGGER.warning(f"Key validation successful for user but missing power")
                return False
            
        else:
            LOGGER.warning(f"Key validation failed for user")
            return False

auth_manager = AuthManager()
