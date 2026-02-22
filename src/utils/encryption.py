import os
from cryptography.fernet import Fernet
from dotenv import load_dotenv
import base64
import hashlib

load_dotenv()

class PhoneEncryptor:
    def __init__(self):
        # Получаем ключ из .env
        key_string = os.getenv("ENCRYPTION_KEY")
        if not key_string:
            raise ValueError("ENCRYPTION_KEY не найден в .env файле!")
        
        # Создаём 32-байтный ключ для Fernet
        # Fernet требует ключ в base64 (ровно 32 байта)
        key = base64.urlsafe_b64encode(
            hashlib.sha256(key_string.encode()).digest()
        )
        self.cipher = Fernet(key)
    
    def encrypt(self, phone: str) -> str:
        """Шифрует номер телефона"""
        if not phone:
            return None
        return self.cipher.encrypt(phone.encode()).decode()
    
    def decrypt(self, encrypted_phone: str) -> str:
        """Расшифровывает номер телефона"""
        if not encrypted_phone:
            return None
        return self.cipher.decrypt(encrypted_phone.encode()).decode()
    
    def mask_phone(self, phone: str) -> str:
        """Маскирует номер для показа (например: +7***1234)"""
        if not phone:
            return ""
        if len(phone) >= 10:
            return phone[:2] + "*" * (len(phone) - 6) + phone[-4:]
        return phone

# Создаём глобальный экземпляр
phone_encryptor = PhoneEncryptor()
