"""
Module de gestion du tracking via Parcelpanel API
Récupère les infos de suivi en temps réel pour chaque shop
"""
import requests
from typing import Dict, Optional, List
import logging
import os
import json

logger = logging.getLogger(__name__)


class ParcelpanelHandler:
    """Gestionnaire de tracking Parcelpanel pour un shop spécifique"""

    BASE_URL = "https://api.parcelpanel.com/api/v3"

    def __init__(self, api_key: str, shop_domain: str = None):
        """
        Initialise le handler Parcelpanel

        Args:
            api_key: Clé API Parcelpanel pour ce shop
            shop_domain: Domaine du shop (optionnel, pour logging)
        """
        self.api_key = api_key
        self.shop_domain = shop_domain
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

    def get_tracking_info(self, tracking_number: str) -> Optional[Dict]:
        """
        Récupère les informations de tracking pour un numéro de suivi

        Args:
            tracking_number: Numéro de suivi du colis

        Returns:
            Dict avec les infos de tracking ou None si erreur
        """
        try:
            url = f"{self.BASE_URL}/parcels"
            params = {"tracking_number": tracking_number}

            response = requests.get(url, headers=self.headers, params=params, timeout=10)

            if response.status_code == 200:
                data = response.json()
                if data.get("data"):
                    parcel = data["data"][0] if isinstance(data["data"], list) else data["data"]
                    return self._parse_tracking_response(parcel)

            logger.warning(f"Parcelpanel: pas de données pour {tracking_number}")
            return None

        except Exception as e:
            logger.error(f"Erreur Parcelpanel get_tracking_info: {e}")
            return None

    def get_tracking_by_order(self, order_number: str) -> Optional[Dict]:
        """
        Récupère les informations de tracking par numéro de commande

        Args:
            order_number: Numéro de commande

        Returns:
            Dict avec les infos de tracking ou None si erreur
        """
        try:
            url = f"{self.BASE_URL}/parcels"
            params = {"order_number": order_number}

            response = requests.get(url, headers=self.headers, params=params, timeout=10)

            if response.status_code == 200:
                data = response.json()
                if data.get("data"):
                    parcel = data["data"][0] if isinstance(data["data"], list) else data["data"]
                    return self._parse_tracking_response(parcel)

            logger.warning(f"Parcelpanel: pas de données pour commande {order_number}")
            return None

        except Exception as e:
            logger.error(f"Erreur Parcelpanel get_tracking_by_order: {e}")
            return None

    def _parse_tracking_response(self, parcel: Dict) -> Dict:
        """
        Parse la réponse Parcelpanel en format standardisé

        Args:
            parcel: Données brutes du colis

        Returns:
            Dict formaté avec les infos essentielles
        """
        # Statuts Parcelpanel traduits
        status_translations = {
            "pending": "En attente de prise en charge",
            "info_received": "Informations reçues par le transporteur",
            "in_transit": "En transit",
            "out_for_delivery": "En cours de livraison",
            "delivered": "Livré",
            "exception": "Problème de livraison",
            "expired": "Suivi expiré",
            "failed_attempt": "Tentative de livraison échouée"
        }

        tracking_info = {
            "tracking_number": parcel.get("tracking_number"),
            "order_number": parcel.get("order_number"),
            "carrier": parcel.get("courier_name") or parcel.get("carrier"),
            "status": parcel.get("status"),
            "status_text": status_translations.get(parcel.get("status"), parcel.get("status")),
            "estimated_delivery": parcel.get("estimated_delivery_date"),
            "last_update": parcel.get("last_updated_at"),
            "tracking_url": parcel.get("tracking_url"),
            "destination_country": parcel.get("destination_country"),
            "events": []
        }

        # Parse les événements de tracking
        if parcel.get("checkpoints") or parcel.get("tracking_details"):
            events = parcel.get("checkpoints") or parcel.get("tracking_details") or []
            for event in events[:10]:  # Limite aux 10 derniers événements
                tracking_info["events"].append({
                    "date": event.get("checkpoint_time") or event.get("date"),
                    "location": event.get("location") or event.get("city"),
                    "description": event.get("message") or event.get("description"),
                    "status": event.get("substatus") or event.get("status")
                })

        return tracking_info

    def get_tracking_summary(self, tracking_number: str) -> str:
        """
        Génère un résumé textuel du tracking pour l'IA

        Args:
            tracking_number: Numéro de suivi

        Returns:
            Résumé formaté pour inclusion dans le prompt IA
        """
        info = self.get_tracking_info(tracking_number)

        if not info:
            return "Aucune information de tracking disponible."

        summary_parts = [
            f"📦 Statut: {info['status_text']}",
            f"🚚 Transporteur: {info['carrier'] or 'Non spécifié'}",
        ]

        if info.get("estimated_delivery"):
            summary_parts.append(f"📅 Livraison estimée: {info['estimated_delivery']}")

        if info.get("tracking_url"):
            summary_parts.append(f"🔗 Suivi: {info['tracking_url']}")

        if info.get("events") and len(info["events"]) > 0:
            last_event = info["events"][0]
            summary_parts.append(f"📍 Dernier événement: {last_event.get('description', 'N/A')} ({last_event.get('date', '')})")

        return "\n".join(summary_parts)


class ParcelpanelManager:
    """Gestionnaire multi-shops pour Parcelpanel"""

    def __init__(self):
        """Initialise le manager avec les clés API depuis les variables d'environnement"""
        self.handlers = {}
        self._load_api_keys()

    def _load_api_keys(self):
        """Charge les clés API depuis PARCELPANEL_API_KEYS (JSON)"""
        # Format attendu: {"shop-name": "api-key", ...}
        # Exemple: {"tgir1c-x2": "pp_xxxxx", "qk16wv-2e": "pp_yyyyy"}
        api_keys_json = os.environ.get('PARCELPANEL_API_KEYS', '{}')

        try:
            api_keys = json.loads(api_keys_json)
            for shop_name, api_key in api_keys.items():
                if api_key:
                    self.handlers[shop_name] = ParcelpanelHandler(api_key, shop_name)
                    logger.info(f"Parcelpanel handler créé pour {shop_name}")
        except json.JSONDecodeError as e:
            logger.error(f"Erreur parsing PARCELPANEL_API_KEYS: {e}")

    def get_handler(self, shop_name: str) -> Optional[ParcelpanelHandler]:
        """
        Récupère le handler Parcelpanel pour un shop spécifique

        Args:
            shop_name: Nom du shop (ex: tgir1c-x2)

        Returns:
            ParcelpanelHandler ou None si pas configuré
        """
        return self.handlers.get(shop_name)

    def get_tracking_for_shop(self, shop_name: str, tracking_number: str = None,
                               order_number: str = None) -> Optional[Dict]:
        """
        Récupère le tracking pour un shop spécifique

        Args:
            shop_name: Nom du shop
            tracking_number: Numéro de suivi (optionnel)
            order_number: Numéro de commande (optionnel)

        Returns:
            Dict avec infos tracking ou None
        """
        handler = self.get_handler(shop_name)
        if not handler:
            logger.warning(f"Pas de handler Parcelpanel pour {shop_name}")
            return None

        if tracking_number:
            return handler.get_tracking_info(tracking_number)
        elif order_number:
            return handler.get_tracking_by_order(order_number)

        return None

    def get_all_configured_shops(self) -> List[str]:
        """Retourne la liste des shops configurés pour Parcelpanel"""
        return list(self.handlers.keys())


# Instance globale du manager
_parcelpanel_manager = None


def get_parcelpanel_manager() -> ParcelpanelManager:
    """Lazy loading du manager Parcelpanel"""
    global _parcelpanel_manager
    if _parcelpanel_manager is None:
        _parcelpanel_manager = ParcelpanelManager()
    return _parcelpanel_manager


def test_parcelpanel_connection(api_key: str) -> Dict:
    """
    Teste la connexion à l'API Parcelpanel

    Args:
        api_key: Clé API à tester

    Returns:
        Dict avec success et message
    """
    result = {
        'success': False,
        'message': ''
    }

    try:
        handler = ParcelpanelHandler(api_key)

        # Test simple - appel API
        url = f"{handler.BASE_URL}/parcels"
        response = requests.get(url, headers=handler.headers, params={"limit": 1}, timeout=10)

        if response.status_code == 200:
            result['success'] = True
            result['message'] = "Connexion Parcelpanel réussie !"
        elif response.status_code == 401:
            result['message'] = "Clé API invalide"
        else:
            result['message'] = f"Erreur API: {response.status_code}"

    except Exception as e:
        result['message'] = f"Erreur: {str(e)}"

    return result
