"""
Module de connexion à l'API Shopify
Récupère les infos commandes et clients pour enrichir les réponses SAV
"""
import requests
from typing import Dict, List, Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class ShopifyHandler:
    """Gestionnaire de l'API Shopify"""

    def __init__(self, shop_name: str, access_token: str):
        """
        Initialise le handler Shopify

        Args:
            shop_name: Nom de la boutique (ex: avena-paris)
            access_token: Token d'accès API Shopify
        """
        self.shop_name = shop_name
        self.access_token = access_token
        self.base_url = f"https://{shop_name}.myshopify.com/admin/api/2024-01"
        self.headers = {
            "X-Shopify-Access-Token": access_token,
            "Content-Type": "application/json"
        }

    def _make_request(self, endpoint: str, method: str = "GET",
                      params: Dict = None) -> Optional[Dict]:
        """Effectue une requête à l'API Shopify"""
        url = f"{self.base_url}/{endpoint}"

        try:
            response = requests.request(
                method=method,
                url=url,
                headers=self.headers,
                params=params,
                timeout=30
            )

            if response.status_code == 200:
                return response.json()
            elif response.status_code == 404:
                logger.warning(f"Ressource non trouvée: {endpoint}")
                return None
            else:
                logger.error(f"Erreur API Shopify {response.status_code}: {response.text}")
                return None

        except Exception as e:
            logger.error(f"Erreur requête Shopify: {e}")
            return None

    def get_order_by_number(self, order_number: str) -> Optional[Dict]:
        """
        Récupère une commande par son numéro

        Args:
            order_number: Numéro de commande (ex: "1234")

        Returns:
            Dictionnaire avec les infos de la commande ou None
        """
        # Shopify utilise le nom de la commande avec # prefix
        data = self._make_request(
            "orders.json",
            params={"name": f"#{order_number}", "status": "any"}
        )

        if data and data.get('orders'):
            order = data['orders'][0]
            return self._format_order(order)

        # Essai sans le #
        data = self._make_request(
            "orders.json",
            params={"name": order_number, "status": "any"}
        )

        if data and data.get('orders'):
            order = data['orders'][0]
            return self._format_order(order)

        return None

    def get_order_by_id(self, order_id: str) -> Optional[Dict]:
        """Récupère une commande par son ID Shopify"""
        data = self._make_request(f"orders/{order_id}.json")

        if data and data.get('order'):
            return self._format_order(data['order'])

        return None

    def search_orders_by_email(self, email: str, limit: int = 5) -> List[Dict]:
        """
        Recherche les commandes d'un client par email

        Args:
            email: Email du client
            limit: Nombre max de commandes à retourner

        Returns:
            Liste des commandes formatées
        """
        data = self._make_request(
            "orders.json",
            params={
                "email": email,
                "status": "any",
                "limit": limit
            }
        )

        if data and data.get('orders'):
            return [self._format_order(order) for order in data['orders']]

        return []

    def get_customer_by_email(self, email: str) -> Optional[Dict]:
        """
        Récupère les infos d'un client par email

        Args:
            email: Email du client

        Returns:
            Dictionnaire avec les infos client
        """
        data = self._make_request(
            "customers/search.json",
            params={"query": f"email:{email}"}
        )

        if data and data.get('customers'):
            customer = data['customers'][0]
            return self._format_customer(customer)

        return None

    def _format_order(self, order: Dict) -> Dict:
        """Formate les données d'une commande pour l'usage SAV"""

        # Statut de fulfillment en français
        fulfillment_status_map = {
            None: "Non traité",
            "fulfilled": "Expédié",
            "partial": "Partiellement expédié",
            "unfulfilled": "En préparation"
        }

        # Statut financier en français
        financial_status_map = {
            "paid": "Payé",
            "pending": "En attente de paiement",
            "refunded": "Remboursé",
            "partially_refunded": "Partiellement remboursé",
            "voided": "Annulé"
        }

        # Extraction du tracking
        tracking_info = None
        tracking_url = None

        if order.get('fulfillments'):
            for fulfillment in order['fulfillments']:
                if fulfillment.get('tracking_number'):
                    tracking_info = fulfillment['tracking_number']
                    tracking_url = fulfillment.get('tracking_url')
                    break

        # Liste des produits
        line_items = []
        for item in order.get('line_items', []):
            line_items.append({
                'name': item.get('name'),
                'quantity': item.get('quantity'),
                'price': item.get('price'),
                'variant': item.get('variant_title')
            })

        # Adresse de livraison
        shipping_address = None
        if order.get('shipping_address'):
            addr = order['shipping_address']
            shipping_address = {
                'name': f"{addr.get('first_name', '')} {addr.get('last_name', '')}".strip(),
                'address': addr.get('address1'),
                'city': addr.get('city'),
                'zip': addr.get('zip'),
                'country': addr.get('country')
            }

        return {
            'id': order.get('id'),
            'order_number': order.get('name', '').replace('#', ''),
            'email': order.get('email'),
            'customer_name': f"{order.get('customer', {}).get('first_name', '')} {order.get('customer', {}).get('last_name', '')}".strip(),
            'created_at': order.get('created_at'),
            'total_price': order.get('total_price'),
            'currency': order.get('currency'),
            'financial_status': financial_status_map.get(order.get('financial_status'), order.get('financial_status')),
            'fulfillment_status': fulfillment_status_map.get(order.get('fulfillment_status'), order.get('fulfillment_status')),
            'tracking_number': tracking_info,
            'tracking_url': tracking_url,
            'line_items': line_items,
            'shipping_address': shipping_address,
            'note': order.get('note'),
            'tags': order.get('tags')
        }

    def _format_customer(self, customer: Dict) -> Dict:
        """Formate les données d'un client"""
        return {
            'id': customer.get('id'),
            'email': customer.get('email'),
            'first_name': customer.get('first_name'),
            'last_name': customer.get('last_name'),
            'full_name': f"{customer.get('first_name', '')} {customer.get('last_name', '')}".strip(),
            'phone': customer.get('phone'),
            'orders_count': customer.get('orders_count'),
            'total_spent': customer.get('total_spent'),
            'created_at': customer.get('created_at'),
            'tags': customer.get('tags'),
            'note': customer.get('note')
        }

    def get_order_context(self, order_number: str = None,
                          email: str = None) -> Dict:
        """
        Récupère tout le contexte nécessaire pour une réponse SAV

        Args:
            order_number: Numéro de commande (optionnel)
            email: Email du client (optionnel)

        Returns:
            Dictionnaire avec toutes les infos contextuelles
        """
        context = {
            'order': None,
            'customer': None,
            'recent_orders': [],
            'found': False
        }

        # Si on a un numéro de commande, on le cherche
        if order_number:
            order = self.get_order_by_number(order_number)
            if order:
                context['order'] = order
                context['found'] = True

                # Utilise l'email de la commande pour enrichir
                if order.get('email') and not email:
                    email = order['email']

        # Si on a un email, on récupère le client et ses commandes
        if email:
            customer = self.get_customer_by_email(email)
            if customer:
                context['customer'] = customer

            recent_orders = self.search_orders_by_email(email, limit=3)
            if recent_orders:
                context['recent_orders'] = recent_orders
                context['found'] = True

                # Si on n'avait pas de commande spécifique, prend la plus récente
                if not context['order'] and recent_orders:
                    context['order'] = recent_orders[0]

        return context


def test_shopify_connection(shop_name: str, access_token: str) -> Dict:
    """Teste la connexion Shopify et retourne le résultat"""
    handler = ShopifyHandler(shop_name, access_token)

    result = {
        'success': False,
        'message': '',
        'shop_name': shop_name
    }

    try:
        # Test simple : récupère les infos du shop
        data = handler._make_request("shop.json")

        if data and data.get('shop'):
            shop_info = data['shop']
            result['success'] = True
            result['message'] = f"Connecté à {shop_info.get('name')} ({shop_info.get('email')})"
            result['shop_info'] = {
                'name': shop_info.get('name'),
                'email': shop_info.get('email'),
                'domain': shop_info.get('domain')
            }
        else:
            result['message'] = "Échec de connexion - vérifiez vos identifiants"

    except Exception as e:
        result['message'] = f"Erreur: {str(e)}"

    return result
