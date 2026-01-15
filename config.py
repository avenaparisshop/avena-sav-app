"""
Configuration de l'application Avena SAV
"""
import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Configuration principale"""

    # Flask
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-key-change-me')

    # Database URL - Railway fournit postgres:// mais SQLAlchemy moderne requiert postgresql://
    _database_url = os.getenv('DATABASE_URL', 'sqlite:///avena_sav.db')
    if _database_url.startswith('postgres://'):
        _database_url = _database_url.replace('postgres://', 'postgresql://', 1)
    SQLALCHEMY_DATABASE_URI = _database_url
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Zoho Mail
    ZOHO_EMAIL = os.getenv('ZOHO_EMAIL')
    ZOHO_PASSWORD = os.getenv('ZOHO_PASSWORD')
    ZOHO_IMAP_SERVER = os.getenv('ZOHO_IMAP_SERVER', 'imap.zoho.eu')
    ZOHO_SMTP_SERVER = os.getenv('ZOHO_SMTP_SERVER', 'smtp.zoho.eu')

    # Shopify OAuth (nouveau système Dev Dashboard)
    SHOPIFY_CLIENT_ID = os.getenv('SHOPIFY_CLIENT_ID')
    SHOPIFY_CLIENT_SECRET = os.getenv('SHOPIFY_CLIENT_SECRET')
    SHOPIFY_SCOPES = os.getenv('SHOPIFY_SCOPES', 'read_orders,read_customers')
    SHOPIFY_TOKENS_FILE = os.getenv('SHOPIFY_TOKENS_FILE', 'shopify_tokens.json')

    # Multi-boutiques: credentials par shop (JSON)
    # Format: {"shop-name": {"client_id": "...", "client_secret": "..."}, ...}
    # Exemple: {"tgir1c-x2": {"client_id": "abc", "client_secret": "xyz"}}
    SHOPIFY_CREDENTIALS = os.getenv('SHOPIFY_CREDENTIALS', '{}')

    # Shop par défaut (optionnel - pour rétrocompatibilité)
    SHOPIFY_SHOP_NAME = os.getenv('SHOPIFY_SHOP_NAME')
    SHOPIFY_ACCESS_TOKEN = os.getenv('SHOPIFY_ACCESS_TOKEN')  # Token legacy si disponible

    # Gemini (Google AI) - utilisé pour les réponses
    GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

    # Anthropic (legacy - gardé pour compatibilité)
    ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY')

    # Automation
    AUTO_SEND_TRACKING = os.getenv('AUTO_SEND_TRACKING', 'true').lower() == 'true'
    AUTO_SEND_RETURN_CONFIRM = os.getenv('AUTO_SEND_RETURN_CONFIRM', 'false').lower() == 'true'
    EMAIL_CHECK_INTERVAL = int(os.getenv('EMAIL_CHECK_INTERVAL', 300))

    # Company info (pour les réponses)
    COMPANY_NAME = "Avena Paris"
    COMPANY_EMAIL = os.getenv('ZOHO_EMAIL', 'sav@avena-paris.com')


class DevelopmentConfig(Config):
    """Configuration développement"""
    DEBUG = True
    FLASK_ENV = 'development'


class ProductionConfig(Config):
    """Configuration production"""
    DEBUG = False
    FLASK_ENV = 'production'


# Sélection de la config selon l'environnement
config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig
}


def get_config():
    """Retourne la configuration appropriée"""
    env = os.getenv('FLASK_ENV', 'development')
    return config.get(env, config['default'])
