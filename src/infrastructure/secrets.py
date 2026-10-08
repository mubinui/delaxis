"""Secret management integration for secure credential storage."""

import os
import time
from abc import ABC, abstractmethod
from typing import Any

import structlog
from cryptography.fernet import Fernet

from src.config.settings import get_settings

logger = structlog.get_logger(__name__)


class SecretManager(ABC):
    """Abstract base class for secret management providers."""

    @abstractmethod
    async def get_secret(self, secret_name: str) -> str | None:
        """Retrieve a secret by name."""
        pass

    @abstractmethod
    async def set_secret(self, secret_name: str, secret_value: str) -> bool:
        """Store a secret."""
        pass

    @abstractmethod
    async def delete_secret(self, secret_name: str) -> bool:
        """Delete a secret."""
        pass

    @abstractmethod
    async def list_secrets(self) -> list[str]:
        """List all secret names."""
        pass


class EnvironmentSecretManager(SecretManager):
    """Secret manager that uses environment variables."""

    async def get_secret(self, secret_name: str) -> str | None:
        """Get secret from environment variable."""
        return os.getenv(secret_name)

    async def set_secret(self, secret_name: str, secret_value: str) -> bool:
        """Set environment variable (not persistent)."""
        os.environ[secret_name] = secret_value
        return True

    async def delete_secret(self, secret_name: str) -> bool:
        """Delete environment variable."""
        if secret_name in os.environ:
            del os.environ[secret_name]
            return True
        return False

    async def list_secrets(self) -> list[str]:
        """List all environment variables (filtered for secrets)."""
        # Return only variables that look like secrets
        secret_patterns = ["_KEY", "_SECRET", "_TOKEN", "_PASSWORD", "_CREDENTIAL"]
        return [
            key
            for key in os.environ.keys()
            if any(pattern in key.upper() for pattern in secret_patterns)
        ]


class AWSSecretsManager(SecretManager):
    """Secret manager for AWS Secrets Manager."""

    def __init__(self, region_name: str = "us-east-1"):
        self.region_name = region_name
        self._client: Any = None

    def _get_client(self) -> Any:
        """Get AWS Secrets Manager client."""
        if self._client is None:
            try:
                import boto3

                self._client = boto3.client("secretsmanager", region_name=self.region_name)
            except ImportError as exc:
                raise ImportError("boto3 is required for AWS Secrets Manager integration") from exc
        return self._client

    async def get_secret(self, secret_name: str) -> str | None:
        """Get secret from AWS Secrets Manager."""
        try:
            client = self._get_client()
            response = client.get_secret_value(SecretId=secret_name)
            value = response.get("SecretString")
            return str(value) if value is not None else None
        except Exception as e:
            logger.error("aws_secrets_manager_get_failed", secret_name=secret_name, error=str(e))
            return None

    async def set_secret(self, secret_name: str, secret_value: str) -> bool:
        """Store secret in AWS Secrets Manager."""
        try:
            client = self._get_client()
            try:
                # Try to update existing secret
                client.update_secret(SecretId=secret_name, SecretString=secret_value)
            except client.exceptions.ResourceNotFoundException:
                # Create new secret if it doesn't exist
                client.create_secret(Name=secret_name, SecretString=secret_value)
            return True
        except Exception as e:
            logger.error("aws_secrets_manager_set_failed", secret_name=secret_name, error=str(e))
            return False

    async def delete_secret(self, secret_name: str) -> bool:
        """Delete secret from AWS Secrets Manager."""
        try:
            client = self._get_client()
            client.delete_secret(SecretId=secret_name, ForceDeleteWithoutRecovery=True)
            return True
        except Exception as e:
            logger.error("aws_secrets_manager_delete_failed", secret_name=secret_name, error=str(e))
            return False

    async def list_secrets(self) -> list[str]:
        """List all secrets in AWS Secrets Manager."""
        try:
            client = self._get_client()
            response = client.list_secrets()
            return [secret["Name"] for secret in response.get("SecretList", [])]
        except Exception as e:
            logger.error("aws_secrets_manager_list_failed", error=str(e))
            return []


class AzureKeyVaultManager(SecretManager):
    """Secret manager for Azure Key Vault."""

    def __init__(self, vault_url: str):
        self.vault_url = vault_url
        self._client: Any = None

    def _get_client(self) -> Any:
        """Get Azure Key Vault client."""
        if self._client is None:
            try:
                from azure.identity import DefaultAzureCredential
                from azure.keyvault.secrets import SecretClient

                credential = DefaultAzureCredential()
                self._client = SecretClient(vault_url=self.vault_url, credential=credential)
            except ImportError as exc:
                raise ImportError(
                    "azure-keyvault-secrets and azure-identity are required for Azure Key Vault integration"
                ) from exc
        return self._client

    async def get_secret(self, secret_name: str) -> str | None:
        """Get secret from Azure Key Vault."""
        try:
            client = self._get_client()
            secret = client.get_secret(secret_name)
            return str(secret.value) if secret.value is not None else None
        except Exception as e:
            logger.error("azure_keyvault_get_failed", secret_name=secret_name, error=str(e))
            return None

    async def set_secret(self, secret_name: str, secret_value: str) -> bool:
        """Store secret in Azure Key Vault."""
        try:
            client = self._get_client()
            client.set_secret(secret_name, secret_value)
            return True
        except Exception as e:
            logger.error("azure_keyvault_set_failed", secret_name=secret_name, error=str(e))
            return False

    async def delete_secret(self, secret_name: str) -> bool:
        """Delete secret from Azure Key Vault."""
        try:
            client = self._get_client()
            client.begin_delete_secret(secret_name)
            return True
        except Exception as e:
            logger.error("azure_keyvault_delete_failed", secret_name=secret_name, error=str(e))
            return False

    async def list_secrets(self) -> list[str]:
        """List all secrets in Azure Key Vault."""
        try:
            client = self._get_client()
            secrets = client.list_properties_of_secrets()
            return [secret.name for secret in secrets]
        except Exception as e:
            logger.error("azure_keyvault_list_failed", error=str(e))
            return []


class HashiCorpVaultManager(SecretManager):
    """Secret manager for HashiCorp Vault."""

    def __init__(self, vault_url: str, vault_token: str, mount_point: str = "secret"):
        self.vault_url = vault_url
        self.vault_token = vault_token
        self.mount_point = mount_point
        self._client: Any = None

    def _get_client(self) -> Any:
        """Get HashiCorp Vault client."""
        if self._client is None:
            try:
                import hvac

                self._client = hvac.Client(url=self.vault_url, token=self.vault_token)
            except ImportError as exc:
                raise ImportError("hvac is required for HashiCorp Vault integration") from exc
        return self._client

    async def get_secret(self, secret_name: str) -> str | None:
        """Get secret from HashiCorp Vault."""
        try:
            client = self._get_client()
            response = client.secrets.kv.v2.read_secret_version(
                path=secret_name, mount_point=self.mount_point
            )
            value = response["data"]["data"].get("value")
            return str(value) if value is not None else None
        except Exception as e:
            logger.error("hashicorp_vault_get_failed", secret_name=secret_name, error=str(e))
            return None

    async def set_secret(self, secret_name: str, secret_value: str) -> bool:
        """Store secret in HashiCorp Vault."""
        try:
            client = self._get_client()
            client.secrets.kv.v2.create_or_update_secret(
                path=secret_name, secret={"value": secret_value}, mount_point=self.mount_point
            )
            return True
        except Exception as e:
            logger.error("hashicorp_vault_set_failed", secret_name=secret_name, error=str(e))
            return False

    async def delete_secret(self, secret_name: str) -> bool:
        """Delete secret from HashiCorp Vault."""
        try:
            client = self._get_client()
            client.secrets.kv.v2.delete_metadata_and_all_versions(
                path=secret_name, mount_point=self.mount_point
            )
            return True
        except Exception as e:
            logger.error("hashicorp_vault_delete_failed", secret_name=secret_name, error=str(e))
            return False

    async def list_secrets(self) -> list[str]:
        """List all secrets in HashiCorp Vault."""
        try:
            client = self._get_client()
            response = client.secrets.kv.v2.list_secrets(mount_point=self.mount_point)
            return [str(key) for key in response["data"]["keys"]]
        except Exception as e:
            logger.error("hashicorp_vault_list_failed", error=str(e))
            return []


class CredentialManager:
    """High-level credential manager that combines encryption and secret management."""

    def __init__(self, secret_manager: SecretManager | None = None):
        self.secret_manager = secret_manager or EnvironmentSecretManager()
        self._encryption_key: bytes | None = None

    def _get_encryption_key(self) -> bytes:
        """Get or generate encryption key."""
        if self._encryption_key is not None:
            return self._encryption_key

        settings = get_settings()
        configured = getattr(settings.security, "encryption_key", None)
        if configured:
            self._encryption_key = (
                configured.encode() if isinstance(configured, str) else bytes(configured)
            )
            return self._encryption_key

        # Try to get from secret manager
        key_from_secret: str | None = None
        try:
            import asyncio

            key_from_secret = asyncio.run(self.secret_manager.get_secret("ENCRYPTION_KEY"))
        except Exception:
            pass

        if key_from_secret:
            self._encryption_key = key_from_secret.encode()
            return self._encryption_key

        # Generate new key and store it
        generated = Fernet.generate_key()
        self._encryption_key = generated
        logger.warning(
            "generated_new_encryption_key",
            message="Generated new encryption key. Store ENCRYPTION_KEY securely.",
        )

        # Try to store the key
        try:
            import asyncio

            asyncio.run(self.secret_manager.set_secret("ENCRYPTION_KEY", generated.decode()))
        except Exception as e:
            logger.error("failed_to_store_encryption_key", error=str(e))

        return generated

    def encrypt_credential(self, credential: str) -> str:
        """Encrypt a credential."""
        fernet = Fernet(self._get_encryption_key())
        return fernet.encrypt(credential.encode()).decode()

    def decrypt_credential(self, encrypted_credential: str) -> str:
        """Decrypt a credential."""
        fernet = Fernet(self._get_encryption_key())
        return fernet.decrypt(encrypted_credential.encode()).decode()

    async def store_credential(self, name: str, value: str, encrypt: bool = True) -> bool:
        """Store a credential (optionally encrypted)."""
        if encrypt:
            value = self.encrypt_credential(value)

        return await self.secret_manager.set_secret(name, value)

    async def retrieve_credential(self, name: str, encrypted: bool = True) -> str | None:
        """Retrieve a credential (optionally decrypt)."""
        value = await self.secret_manager.get_secret(name)

        if value and encrypted:
            try:
                value = self.decrypt_credential(value)
            except Exception as e:
                logger.error("credential_decryption_failed", name=name, error=str(e))
                return None

        return value

    async def rotate_credential(self, name: str, new_value: str, encrypt: bool = True) -> bool:
        """Rotate a credential."""
        # Store old value as backup
        old_value = await self.retrieve_credential(name, encrypted=encrypt)
        if old_value:
            backup_name = f"{name}_backup_{int(time.time())}"
            await self.store_credential(backup_name, old_value, encrypt=encrypt)

        # Store new value
        return await self.store_credential(name, new_value, encrypt=encrypt)


def get_secret_manager() -> SecretManager:
    """Get the configured secret manager."""
    get_settings()

    # Check for secret manager configuration in environment
    secret_manager_type = os.getenv("SECRET_MANAGER_TYPE", "environment").lower()

    if secret_manager_type == "aws":
        region = os.getenv("AWS_REGION", "us-east-1")
        return AWSSecretsManager(region_name=region)
    elif secret_manager_type == "azure":
        vault_url = os.getenv("AZURE_KEYVAULT_URL")
        if not vault_url:
            raise ValueError("AZURE_KEYVAULT_URL is required for Azure Key Vault")
        return AzureKeyVaultManager(vault_url=vault_url)
    elif secret_manager_type == "hashicorp":
        vault_url = os.getenv("VAULT_URL")
        vault_token = os.getenv("VAULT_TOKEN")
        if not vault_url or not vault_token:
            raise ValueError("VAULT_URL and VAULT_TOKEN are required for HashiCorp Vault")
        mount_point = os.getenv("VAULT_MOUNT_POINT", "secret")
        return HashiCorpVaultManager(vault_url, vault_token, mount_point)
    else:
        return EnvironmentSecretManager()


def get_credential_manager() -> CredentialManager:
    """Get the configured credential manager."""
    secret_manager = get_secret_manager()
    return CredentialManager(secret_manager)


# Global credential manager instance
_credential_manager: CredentialManager | None = None


def get_global_credential_manager() -> CredentialManager:
    """Get the global credential manager instance."""
    global _credential_manager
    if _credential_manager is None:
        _credential_manager = get_credential_manager()
    return _credential_manager
