from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str
    wordpress_proxy_secret: str
    docs_enabled: bool = False
    webuntis_server: str
    webuntis_school: str
    webuntis_username: str
    webuntis_password: str
    asv_csv_path: str
    asv_csv_column_externe_id: str = "idnumber"
    asv_csv_column_vorname: str = "firstname"
    asv_csv_column_nachname: str = "lastname"
    asv_csv_column_klasse: str = "Klasse"
    asv_csv_column_eintrittsdatum: str = "Eintrittsdatum"
    asv_csv_column_austrittsdatum: str = "Austrittsdatum"
    webuntis_sync_retry_delay_minutes: int = 30
    webuntis_sync_retry_max_attempts: int = 4
    smtp_host: str
    smtp_from_address: str
    dashboard_base_url: str
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_use_starttls: bool = True

    @field_validator("wordpress_proxy_secret")
    @classmethod
    def _validate_wordpress_proxy_secret(cls, value: str) -> str:
        """Fail-fast bei Konstruktion: verhindert schwache/Platzhalter-Secrets in Produktion.

        Laeuft nur bei `Settings()`-Konstruktion, nicht bei spaeteren
        `monkeypatch.setattr(settings, "wordpress_proxy_secret", ...)`-Zuweisungen in Tests
        (kein `validate_assignment=True` in model_config) -- bestehende Tests mit kurzen
        Werten wie "test-secret" bleiben dadurch unveraendert lauffaehig.
        """
        normalisiert = value.strip()
        if not normalisiert or len(normalisiert) < 32 or normalisiert.lower() == "changeme" or normalisiert.lower().startswith("test-"):
            raise ValueError(
                "WORDPRESS_PROXY_SECRET ist leer, zu kurz (< 32 Zeichen) oder ein bekannter "
                "Platzhalter (\"changeme\"/\"test-...\"). Bitte ein starkes Secret setzen, "
                "z.B. mit \"openssl rand -hex 32\" erzeugt."
            )
        return value


settings = Settings()
