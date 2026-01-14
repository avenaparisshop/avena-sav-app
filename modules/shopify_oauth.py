"""
Module OAuth pour Shopify
Gère l'authentification OAuth 2.0 avec le nouveau Dev Dashboard Shopify
"""
import os
import hmac
import hashlib
import base64
import requests
from urllib.parse import urlencode, parse_qs
from typing import Dict, Optional, Tuple
import logging
import json

logger = logging.getLogger(__name__)


class ShopifyOAuth:
    """Gestionnaire OAuth pour Shopify"""

    def __init__(self, client_id: str, client_secret: str, scopes: str = "read_orders,read_customers"):
        """
        Initialise le gestionnaire OAuth

        Args:
            client_id: Client ID de l'application (depuis Dev Dashboard)
            client_secret: Client Secret de l'application
            scopes: Scopes API demandés (séparés par des virgules)
        """
        self.client_id = client_id
        self.client_secret = client_secret
        self.scopes = scopes

    def generate_install_url(self, shop_domain: str, redirect_uri: str, state: str = None) -> str:
        """
        Génère l'URL d'installation OAuth pour un shop

        Args:
            shop_domain: Domaine du shop (ex: avena-paris.myshopify.com)
            redirect_uri: URL de callback après autorisation
            state: Paramètre state pour sécurité CSRF (optionnel)

        Returns:
            URL d'autorisation OAuth complète
        """
        # Normalise le domaine du shop
        if not shop_domain.endswith('.myshopify.com'):
            shop_domain = f"{shop_domain}.myshopify.com"

        params = {
            'client_id': self.client_id,
            'scope': self.scopes,
            'redirect_uri': redirect_uri,
        }

        if state:
            params['state'] = state

        auth_url = f"https://{shop_domain}/admin/oauth/authorize?{urlencode(params)}"
        return auth_url

    def verify_hmac(self, params: Dict[str, str]) -> bool:
        """
        Vérifie la signature HMAC des paramètres de callback

        Args:
            params: Paramètres de la requête de callback

        Returns:
            True si la signature est valide
        """
        if 'hmac' not in params:
            return False

        # Récupère le HMAC reçu
        received_hmac = params.pop('hmac', None)

        # Reconstruit la chaîne de paramètres
        sorted_params = sorted(params.items())
        encoded_params = urlencode(sorted_params)

        # Calcule le HMAC attendu
        computed_hmac = hmac.new(
            self.client_secret.encode('utf-8'),
            encoded_params.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        # Remet le hmac dans les params
        params['hmac'] = received_hmac

        return hmac.compare_digest(computed_hmac, received_hmac)

    def exchange_code_for_token(self, shop_domain: str, code: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Échange le code d'autorisation contre un Access Token

        Args:
            shop_domain: Domaine du shop
            code: Code d'autorisation reçu du callback

        Returns:
            Tuple (access_token, error_message)
        """
        # Normalise le domaine
        if not shop_domain.endswith('.myshopify.com'):
            shop_domain = f"{shop_domain}.myshopify.com"

        url = f"https://{shop_domain}/admin/oauth/access_token"

        payload = {
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'code': code
        }

        try:
            response = requests.post(url, json=payload, timeout=30)

            if response.status_code == 200:
                data = response.json()
                access_token = data.get('access_token')
                if access_token:
                    logger.info(f"Access token obtenu pour {shop_domain}")
                    return access_token, None
                else:
                    return None, "Access token non trouvé dans la réponse"

            else:
                error_msg = f"Erreur {response.status_code}: {response.text}"
                logger.error(error_msg)
                return None, error_msg

        except Exception as e:
            error_msg = f"Erreur lors de l'échange du code: {str(e)}"
            logger.error(error_msg)
            return None, error_msg

    def get_shop_info(self, shop_domain: str, access_token: str) -> Optional[Dict]:
        """
        Récupère les informations du shop pour vérifier le token

        Args:
            shop_domain: Domaine du shop
            access_token: Token d'accès

        Returns:
            Informations du shop ou None
        """
        if not shop_domain.endswith('.myshopify.com'):
            shop_domain = f"{shop_domain}.myshopify.com"

        url = f"https://{shop_domain}/admin/api/2024-01/shop.json"
        headers = {
            "X-Shopify-Access-Token": access_token,
            "Content-Type": "application/json"
        }

        try:
            response = requests.get(url, headers=headers, timeout=30)
            if response.status_code == 200:
                return response.json().get('shop')
            return None
        except Exception as e:
            logger.error(f"Erreur récupération shop info: {e}")
            return None


class ShopifyTokenStorage:
    """Gestionnaire de stockage des tokens Shopify (fichier JSON simple)"""

    def __init__(self, storage_path: str = "shopify_tokens.json"):
        """
        Initialise le storage

        Args:
            storage_path: Chemin vers le fichier de stockage
        """
        self.storage_path = storage_path
        self._ensure_file_exists()

    def _ensure_file_exists(self):
        """Crée le fichier s'il n'existe pas"""
        if not os.path.exists(self.storage_path):
            with open(self.storage_path, 'w') as f:
                json.dump({}, f)

    def _load_tokens(self) -> Dict:
        """Charge les tokens depuis le fichier"""
        try:
            with open(self.storage_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Erreur chargement tokens: {e}")
            return {}

    def _save_tokens(self, tokens: Dict):
        """Sauvegarde les tokens dans le fichier"""
        try:
            with open(self.storage_path, 'w') as f:
                json.dump(tokens, f, indent=2)
        except Exception as e:
            logger.error(f"Erreur sauvegarde tokens: {e}")

    def store_token(self, shop_domain: str, access_token: str, shop_info: Dict = None):
        """
        Stocke un token pour un shop

        Args:
            shop_domain: Domaine du shop
            access_token: Token d'accès
            shop_info: Informations additionnelles sur le shop
        """
        tokens = self._load_tokens()

        # Normalise le domaine (enlève .myshopify.com pour la clé)
        shop_key = shop_domain.replace('.myshopify.com', '')

        tokens[shop_key] = {
            'access_token': access_token,
            'shop_domain': shop_domain,
            'shop_info': shop_info,
            'created_at': str(__import__('datetime').datetime.utcnow())
        }

        self._save_tokens(tokens)
        logger.info(f"Token stocké pour {shop_key}")

    def get_token(self, shop_domain: str) -> Optional[str]:
        """
        Récupère le token pour un shop

        Args:
            shop_domain: Domaine du shop

        Returns:
            Access token ou None
        """
        tokens = self._load_tokens()
        shop_key = shop_domain.replace('.myshopify.com', '')

        if shop_key in tokens:
            return tokens[shop_key].get('access_token')
        return None

    def get_all_shops(self) -> Dict:
        """Retourne tous les shops connectés"""
        return self._load_tokens()

    def remove_token(self, shop_domain: str):
        """Supprime le token d'un shop"""
        tokens = self._load_tokens()
        shop_key = shop_domain.replace('.myshopify.com', '')

        if shop_key in tokens:
            del tokens[shop_key]
            self._save_tokens(tokens)
            logger.info(f"Token supprimé pour {shop_key}")


class ShopifyTokenStorageDB:
    """Gestionnaire de stockage des tokens Shopify en base de données (persistant)"""

    def __init__(self, db_instance, token_model):
        """
        Initialise le storage DB

        Args:
            db_instance: Instance SQLAlchemy
            token_model: Modèle ShopifyToken
        """
        self.db = db_instance
        self.TokenModel = token_model

    def store_token(self, shop_domain: str, access_token: str, shop_info: Dict = None):
        """Stocke un token pour un shop"""
        shop_key = shop_domain.replace('.myshopify.com', '')

        # Vérifie si existe déjà
        existing = self.TokenModel.query.filter_by(shop_domain=shop_key).first()

        if existing:
            existing.access_token = access_token
            if shop_info:
                existing.shop_name = shop_info.get('name')
                existing.shop_email = shop_info.get('email')
        else:
            new_token = self.TokenModel(
                shop_domain=shop_key,
                access_token=access_token,
                shop_name=shop_info.get('name') if shop_info else None,
                shop_email=shop_info.get('email') if shop_info else None
            )
            self.db.session.add(new_token)

        self.db.session.commit()
        logger.info(f"Token stocké en DB pour {shop_key}")

    def get_token(self, shop_domain: str) -> Optional[str]:
        """Récupère le token pour un shop"""
        shop_key = shop_domain.replace('.myshopify.com', '')
        token_record = self.TokenModel.query.filter_by(shop_domain=shop_key).first()
        return token_record.access_token if token_record else None

    def get_all_shops(self) -> Dict:
        """Retourne tous les shops connectés"""
        tokens = self.TokenModel.query.all()
        return {t.shop_domain: t.to_dict() for t in tokens}

    def remove_token(self, shop_domain: str):
        """Supprime le token d'un shop"""
        shop_key = shop_domain.replace('.myshopify.com', '')
        token_record = self.TokenModel.query.filter_by(shop_domain=shop_key).first()
        if token_record:
            self.db.session.delete(token_record)
            self.db.session.commit()
            logger.info(f"Token supprimé de la DB pour {shop_key}")


def get_oauth_handler() -> ShopifyOAuth:
    """Factory pour créer un handler OAuth avec les variables d'environnement (credentials par défaut)"""
    client_id = os.getenv('SHOPIFY_CLIENT_ID')
    client_secret = os.getenv('SHOPIFY_CLIENT_SECRET')
    scopes = os.getenv('SHOPIFY_SCOPES', 'read_orders,read_customers')

    if not client_id or not client_secret:
        raise ValueError("SHOPIFY_CLIENT_ID et SHOPIFY_CLIENT_SECRET doivent être définis")

    return ShopifyOAuth(client_id, client_secret, scopes)


def get_oauth_handler_for_shop(shop_domain: str) -> ShopifyOAuth:
    """
    Factory pour créer un handler OAuth avec les credentials spécifiques à une boutique.

    Cherche d'abord dans SHOPIFY_CREDENTIALS (JSON multi-boutiques),
    puis fallback sur SHOPIFY_CLIENT_ID/SECRET par défaut.

    Args:
        shop_domain: Domaine du shop (ex: tgir1c-x2 ou tgir1c-x2.myshopify.com)

    Returns:
        ShopifyOAuth configuré avec les bons credentials
    """
    # Normalise le nom du shop (enlève .myshopify.com)
    shop_key = shop_domain.replace('.myshopify.com', '')

    scopes = os.getenv('SHOPIFY_SCOPES', 'read_orders,read_customers')

    # Essaie de récupérer les credentials spécifiques au shop
    credentials_json = os.getenv('SHOPIFY_CREDENTIALS', '{}')
    try:
        credentials = json.loads(credentials_json)
    except json.JSONDecodeError:
        logger.warning("SHOPIFY_CREDENTIALS n'est pas un JSON valide, utilisation des credentials par défaut")
        credentials = {}

    if shop_key in credentials:
        shop_creds = credentials[shop_key]
        client_id = shop_creds.get('client_id')
        client_secret = shop_creds.get('client_secret')

        if client_id and client_secret:
            logger.info(f"Utilisation des credentials spécifiques pour {shop_key}")
            return ShopifyOAuth(client_id, client_secret, scopes)
        else:
            logger.warning(f"Credentials incomplets pour {shop_key}, utilisation des credentials par défaut")

    # Fallback sur les credentials par défaut
    logger.info(f"Utilisation des credentials par défaut pour {shop_key}")
    return get_oauth_handler()


def get_permanent_access_token(shop_domain: str) -> Optional[str]:
    """
    Récupère un access_token permanent depuis SHOPIFY_CREDENTIALS si disponible.

    Cela permet de configurer des access tokens générés directement dans
    le Shopify Admin (Custom Apps) sans passer par OAuth.

    Args:
        shop_domain: Domaine du shop (ex: tgir1c-x2 ou tgir1c-x2.myshopify.com)

    Returns:
        Access token permanent ou None si non configuré
    """
    shop_key = shop_domain.replace('.myshopify.com', '')

    credentials_json = os.getenv('SHOPIFY_CREDENTIALS', '{}')
    try:
        credentials = json.loads(credentials_json)
    except json.JSONDecodeError:
        return None

    if shop_key in credentials:
        access_token = credentials[shop_key].get('access_token')
        if access_token:
            logger.info(f"Access token permanent trouvé pour {shop_key}")
            return access_token

    return None


def get_token_storage() -> ShopifyTokenStorage:
    """Factory pour le storage de tokens (fichier JSON - legacy)"""
    storage_path = os.getenv('SHOPIFY_TOKENS_FILE', 'shopify_tokens.json')
    return ShopifyTokenStorage(storage_path)
