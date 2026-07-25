from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str
    wordpress_proxy_secret: str
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


settings = Settings()
