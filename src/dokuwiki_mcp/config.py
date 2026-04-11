from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    # Die Basis-URL deines DokuWikis (intern im Docker: http://dokuwiki)
    dokuwiki_url: str = "http://dokuwiki"
    
    # Authentifizierung (Priorität: Token > User/Pass)
    dokuwiki_token: Optional[str] = None
    dokuwiki_user: Optional[str] = None
    dokuwiki_password: Optional[str] = None

    class Config:
        env_file = ".env"
        extra = "ignore"

def get_settings() -> Settings:
    return Settings()