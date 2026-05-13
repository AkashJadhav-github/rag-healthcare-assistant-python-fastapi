import base64
import hashlib
from typing import Any, Optional

from cryptography.fernet import Fernet
from sqlalchemy import String
from sqlalchemy.types import TypeDecorator

from ..config import settings


class EncryptedString(TypeDecorator):
    impl = String
    cache_ok = True

    @property
    def _fernet(self) -> Fernet:
        key = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
        return Fernet(base64.urlsafe_b64encode(key))

    def process_bind_param(self, value: Optional[str], dialect: Any) -> Optional[str]:
        if value is None:
            return None
        return self._fernet.encrypt(value.encode()).decode()

    def process_result_value(self, value: Optional[str], dialect: Any) -> Optional[str]:
        if value is None:
            return None
        return self._fernet.decrypt(value.encode()).decode()
