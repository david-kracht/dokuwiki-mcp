from typing import Literal, Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings

URLRewriteMode = Literal[0, 1, 2]

class Settings(BaseSettings):
    # Die Basis-URL deines DokuWikis (intern im Docker: http://dokuwiki)
    dokuwiki_url: str = "http://dokuwiki"

    # DokuWiki userewrite Modus:
    # 0 = kein URL-Rewrite, 1 = Webserver-Rewrite, 2 = DokuWiki-internes Rewrite
    dokuwiki_url_rewrite: URLRewriteMode = 0

    @field_validator("dokuwiki_url_rewrite", mode="before")
    @classmethod
    def _parse_url_rewrite_mode(cls, value):
        # .env values are strings; coerce to int so Literal[0,1,2] validation works.
        if isinstance(value, str):
            value = value.strip()
            if value.isdigit():
                return int(value)
        return value
    
    # Authentifizierung (Priorität: Token > User/Pass)
    dokuwiki_token: Optional[str] = None
    dokuwiki_user: Optional[str] = None
    dokuwiki_password: Optional[str] = None

    class Config:
        env_file = ".env"
        extra = "ignore"

def get_settings() -> Settings:
    return Settings()