"""
Module IA - Classification et génération de réponses avec Claude
Intègre les données Parcelpanel pour le tracking en temps réel
"""
import anthropic
from typing import Dict, Optional, Tuple
import json
import logging

logger = logging.getLogger(__name__)


# Catégories de demandes SAV avec type de traitement
# AUTO = L'IA peut répondre automatiquement (avec infos Parcelpanel)
# MANUAL = Nécessite validation humaine avant envoi
CATEGORIES = {
    "SUIVI": {
        "description": "Demande de suivi de commande (où est ma commande, délai de livraison)",
        "type": "AUTO",  # Auto si tracking disponible
        "requires_tracking": True
    },
    "QUESTION_PRODUIT": {
        "description": "Question sur les produits (taille, couleur, disponibilité, composition)",
        "type": "AUTO",  # IA peut répondre avec infos produit
        "requires_tracking": False
    },
    "LIVRAISON": {
        "description": "Question sur la livraison (délais, transporteurs, zones)",
        "type": "AUTO",  # Réponses standardisées
        "requires_tracking": False
    },
    "RETOUR": {
        "description": "Demande de retour, échange ou remboursement",
        "type": "MANUAL",  # Nécessite validation humaine
        "requires_tracking": False
    },
    "PROBLEME": {
        "description": "Problème avec un produit (défectueux, ne correspond pas, colis endommagé)",
        "type": "MANUAL",  # Nécessite validation humaine
        "requires_tracking": False
    },
    "MODIFICATION": {
        "description": "Demande de modification de commande (adresse, annulation)",
        "type": "MANUAL",  # Nécessite validation humaine
        "requires_tracking": False
    },
    "AUTRE": {
        "description": "Autre type de demande ne rentrant pas dans les catégories précédentes",
        "type": "MANUAL",  # Par défaut, validation humaine
        "requires_tracking": False
    }
}

# Exemples de réponses pour chaque catégorie (style Avena Paris)
# Ces exemples aident l'IA à reproduire le ton et le style
RESPONSE_EXAMPLES = {
    "SUIVI": """Bonjour,

Merci pour votre message !

Votre commande #{order_number} a bien été expédiée et est actuellement {status}.

Vous pouvez suivre votre colis en temps réel via ce lien : {tracking_url}

La livraison est estimée pour le {estimated_delivery}.

N'hésitez pas si vous avez d'autres questions !

Bonne journée,
L'équipe Avena Paris""",

    "QUESTION_PRODUIT": """Bonjour,

Merci pour votre intérêt pour nos produits !

{answer_to_question}

N'hésitez pas à nous contacter si vous avez d'autres questions, nous sommes là pour vous aider !

À très vite sur notre boutique,
L'équipe Avena Paris""",

    "LIVRAISON": """Bonjour,

Merci pour votre message !

Concernant nos délais de livraison :
- France métropolitaine : 2-4 jours ouvrés
- Europe : 4-7 jours ouvrés
- International : 7-14 jours ouvrés

Nous expédions via Colissimo, Mondial Relay ou Chronopost selon votre choix.

Dès que votre commande sera expédiée, vous recevrez un email avec le numéro de suivi.

Belle journée,
L'équipe Avena Paris""",

    "RETOUR": """Bonjour,

Nous avons bien reçu votre demande de retour.

Vous disposez de 14 jours pour nous retourner votre article dans son état d'origine, non porté et avec les étiquettes.

Voici la procédure :
1. Emballez soigneusement l'article
2. Utilisez l'étiquette de retour jointe à votre colis (ou contactez-nous pour en recevoir une)
3. Déposez le colis dans un point relais ou bureau de poste

Le remboursement sera effectué sous 5-7 jours ouvrés après réception et vérification du colis.

N'hésitez pas si vous avez des questions !

Cordialement,
L'équipe Avena Paris"""
}


class AIResponder:
    """Gestionnaire IA pour classification et génération de réponses"""

    def __init__(self, api_key: str, company_name: str = "Avena Paris"):
        """
        Initialise le responder IA

        Args:
            api_key: Clé API Anthropic
            company_name: Nom de l'entreprise pour les réponses
        """
        self.client = anthropic.Anthropic(api_key=api_key)
        self.company_name = company_name
        self.model = "claude-sonnet-4-20250514"  # Bon rapport qualité/prix

    def detect_language(self, text: str) -> str:
        """
        Détecte la langue d'un texte

        Returns:
            Code langue (fr, en, de, es, it, nl, pl)
        """
        # Mots clés pour détection rapide
        lang_keywords = {
            'fr': ['bonjour', 'merci', 'commande', 'livraison', 'retour', 'colis', 'je', 'vous', 'nous', 'mon', 'ma', 'mes'],
            'en': ['hello', 'thank', 'order', 'delivery', 'return', 'package', 'my', 'your', 'please', 'the', 'tracking'],
            'de': ['hallo', 'danke', 'bestellung', 'lieferung', 'paket', 'meine', 'ihre', 'bitte', 'wann', 'zurück'],
            'es': ['hola', 'gracias', 'pedido', 'envío', 'paquete', 'mi', 'cuando', 'dónde', 'devolver', 'entrega'],
            'it': ['ciao', 'grazie', 'ordine', 'spedizione', 'pacco', 'mio', 'quando', 'dove', 'reso', 'consegna'],
            'nl': ['hallo', 'bedankt', 'bestelling', 'levering', 'pakket', 'mijn', 'wanneer', 'retour', 'verzending'],
            'pl': ['cześć', 'dzięki', 'zamówienie', 'dostawa', 'paczka', 'moje', 'kiedy', 'gdzie', 'zwrot', 'przesyłka']
        }

        text_lower = text.lower()
        scores = {}

        for lang, keywords in lang_keywords.items():
            score = sum(1 for kw in keywords if kw in text_lower)
            scores[lang] = score

        # Langue avec le plus de correspondances
        detected = max(scores, key=scores.get)

        # Si pas assez de confiance, défaut français
        if scores[detected] < 2:
            return 'fr'

        logger.info(f"Langue détectée: {detected} (score: {scores[detected]})")
        return detected

    def classify_email(self, subject: str, body: str) -> Tuple[str, float]:
        """
        Classifie un email SAV en AUTO ou MANUEL

        Args:
            subject: Sujet de l'email
            body: Corps de l'email

        Returns:
            Tuple (catégorie AUTO ou MANUEL, score de confiance)
        """
        prompt = f"""Tu es un assistant spécialisé dans la classification des emails de service client pour Avena Paris, une boutique e-commerce de mode/beauté.

Analyse cet email et classifie-le dans UNE des 2 catégories suivantes :

AUTO = L'IA peut répondre automatiquement. Exemples :
- Demande de suivi de commande (où est ma commande, tracking, délai)
- Question sur les produits (taille, couleur, disponibilité)
- Question sur la livraison (délais, transporteurs)
- Questions simples sur les politiques (retours, échanges)

MANUEL = Nécessite une intervention humaine. Exemples :
- Demande de retour ou remboursement
- Problème avec un produit (défectueux, erreur, colis endommagé)
- Modification de commande (adresse, annulation)
- Réclamation, plainte
- Cas complexes ou sensibles

EMAIL À CLASSIFIER :
Sujet : {subject}
Corps : {body}

Réponds UNIQUEMENT avec un JSON : {{"category": "AUTO", "confidence": 0.95}} ou {{"category": "MANUEL", "confidence": 0.95}}
"""

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=100,
                messages=[{"role": "user", "content": prompt}]
            )

            result_text = response.content[0].text.strip()

            # Parse le JSON - nettoie si besoin
            if result_text.startswith("```"):
                result_text = result_text.split("```")[1]
                if result_text.startswith("json"):
                    result_text = result_text[4:]

            result = json.loads(result_text)

            category = result.get("category", "MANUEL").upper()
            confidence = float(result.get("confidence", 0.5))

            # Valide : seulement AUTO ou MANUEL
            if category not in ['AUTO', 'MANUEL']:
                category = 'MANUEL'  # Par défaut = validation humaine

            logger.info(f"Email classifié: {category} (confiance: {confidence})")
            return category, confidence

        except Exception as e:
            logger.error(f"Erreur classification: {e}")
            return "MANUEL", 0.0  # Par défaut = validation humaine

    def is_auto_eligible(self, category: str, confidence: float, order_context: Dict) -> Tuple[bool, str]:
        """
        Détermine si un email peut être répondu automatiquement

        Returns:
            Tuple (peut_auto, raison)
        """
        cat_config = CATEGORIES.get(category, {})

        # Vérifie si la catégorie permet l'auto
        if cat_config.get('type') != 'AUTO':
            return False, f"Catégorie {category} nécessite validation manuelle"

        # Vérifie la confiance minimum
        if confidence < 0.85:
            return False, f"Confiance insuffisante ({confidence:.0%})"

        # Pour SUIVI, on a besoin du tracking depuis Shopify
        if category == 'SUIVI':
            has_tracking = (
                order_context.get('order') and
                (order_context['order'].get('tracking_number') or
                 order_context['order'].get('fulfillment_status') == 'Expédié')
            )
            if not has_tracking:
                return False, "Pas d'info de tracking disponible"

        return True, f"Auto-réponse possible pour {category}"

    def generate_response(self, email_data: Dict, order_context: Dict,
                          category: str, language: str = None) -> str:
        """
        Génère une réponse personnalisée à un email SAV

        Args:
            email_data: Données de l'email (subject, body, sender_name, etc.)
            order_context: Contexte Shopify + Parcelpanel (order, customer, parcelpanel_tracking, etc.)
            category: Catégorie de la demande
            language: Code langue pour la réponse (fr, en, de, es, it, nl, pl)

        Returns:
            Réponse générée
        """

        # Détecte la langue si non fournie
        if not language:
            text = f"{email_data.get('subject', '')} {email_data.get('body', '')}"
            language = self.detect_language(text)

        # Noms des langues pour le prompt
        lang_names = {
            'fr': 'français',
            'en': 'anglais',
            'de': 'allemand',
            'es': 'espagnol',
            'it': 'italien',
            'nl': 'néerlandais',
            'pl': 'polonais'
        }
        lang_name = lang_names.get(language, 'français')

        # Construit le contexte pour Claude
        context_parts = []

        # Infos client
        customer_name = email_data.get('sender_name') or "Client"
        if order_context.get('customer'):
            customer = order_context['customer']
            customer_name = customer.get('full_name') or customer.get('first_name') or customer_name
            context_parts.append(f"Client : {customer_name}")
            if customer.get('orders_count'):
                context_parts.append(f"Historique : {customer['orders_count']} commande(s)")

        # Infos commande Shopify
        if order_context.get('order'):
            order = order_context['order']
            context_parts.append(f"\nCOMMANDE #{order.get('order_number')} :")
            context_parts.append(f"- Statut commande : {order.get('fulfillment_status')}")
            context_parts.append(f"- Paiement : {order.get('financial_status')}")

            # TRACKING depuis Shopify
            if order.get('tracking_number'):
                context_parts.append(f"\n📦 INFORMATIONS DE SUIVI :")
                context_parts.append(f"- Numéro de suivi : {order['tracking_number']}")

                if order.get('tracking_company'):
                    context_parts.append(f"- Transporteur : {order['tracking_company']}")

                if order.get('shipment_status'):
                    # Traduction des statuts Shopify
                    status_map = {
                        'confirmed': 'Pris en charge',
                        'in_transit': 'En cours de livraison',
                        'out_for_delivery': 'En livraison aujourd\'hui',
                        'delivered': 'Livré',
                        'attempted_delivery': 'Tentative de livraison',
                        'ready_for_pickup': 'À retirer en point relais',
                        'failure': 'Problème de livraison'
                    }
                    status_text = status_map.get(order['shipment_status'], order['shipment_status'])
                    context_parts.append(f"- Statut livraison : {status_text}")

                if order.get('shipped_at'):
                    context_parts.append(f"- Date d'expédition : {order['shipped_at'][:10]}")

                if order.get('tracking_url'):
                    context_parts.append(f"- Lien de suivi : {order['tracking_url']}")

            if order.get('line_items'):
                items = [f"{i['quantity']}x {i['name']}" for i in order['line_items'][:3]]
                context_parts.append(f"- Produits : {', '.join(items)}")

        context_str = "\n".join(context_parts) if context_parts else "Aucune information de commande trouvée"

        # Instructions selon la catégorie
        category_instructions = {
            "SUIVI": """
- UTILISE LES INFORMATIONS DE TRACKING EN TEMPS RÉEL si disponibles (statut actuel, localisation, date estimée)
- Si un tracking est disponible, donne le statut précis, le transporteur et le lien de suivi
- Si pas de tracking, indique que la commande est en préparation et donne un délai estimé (2-5 jours ouvrés)
- Reste rassurant et professionnel""",

            "RETOUR": """
- Indique la procédure de retour (14 jours, produit non porté, étiquette retour)
- Propose un échange ou remboursement
- Demande des précisions si nécessaire (raison, taille souhaitée pour échange)""",

            "PROBLEME": """
- Présente des excuses pour le désagrément
- Propose une solution (renvoi du produit, remboursement, geste commercial)
- Demande des photos si pertinent
- Montre de l'empathie""",

            "QUESTION": """
- Réponds de manière informative et chaleureuse
- Propose de l'aide supplémentaire
- Invite à passer commande si pertinent""",

            "MODIFICATION": """
- Vérifie si la modification est encore possible (selon le statut)
- Si expédié, explique qu'il n'est plus possible de modifier
- Propose des alternatives si besoin""",

            "AUTRE": """
- Réponds de manière générique mais professionnelle
- Redirige vers le bon service si nécessaire
- Reste aimable et serviable"""
        }

        instructions = category_instructions.get(category, category_instructions["AUTRE"])

        prompt = f"""Tu es un assistant service client pour {self.company_name}, une boutique e-commerce de mode parisienne.
Tu dois rédiger une réponse professionnelle, chaleureuse et efficace à cet email client.

IMPORTANT - LANGUE : L'email du client est en {lang_name}. Tu DOIS répondre ENTIÈREMENT en {lang_name}.

CONTEXTE CLIENT/COMMANDE :
{context_str}

EMAIL DU CLIENT :
Sujet : {email_data.get('subject', '')}
Message : {email_data.get('body', '')}

TYPE DE DEMANDE : {category}

INSTRUCTIONS SPÉCIFIQUES :
{instructions}

CONSIGNES DE RÉDACTION :
- ÉCRIS TOUTE LA RÉPONSE EN {lang_name.upper()}
- Commence par une salutation appropriée dans la langue du client
- Sois professionnel mais chaleureux, pas robotique
- Va droit au but, évite les phrases inutiles
- Utilise le vouvoiement (ou équivalent formel dans la langue)
- Si tu as des informations de tracking, utilise-les pour donner une réponse précise et rassurante
- Termine par une formule de politesse et "L'équipe {self.company_name}"
- Ne mets PAS de crochets ou de placeholders comme [XX] dans la réponse
- La réponse doit être prête à envoyer telle quelle

Rédige UNIQUEMENT la réponse en {lang_name}, sans commentaire ni explication."""

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=1000,
                messages=[{"role": "user", "content": prompt}]
            )

            generated_response = response.content[0].text.strip()
            logger.info(f"Réponse générée ({len(generated_response)} caractères)")
            return generated_response

        except Exception as e:
            logger.error(f"Erreur génération: {e}")
            return self._get_fallback_response(customer_name, category)

    def _get_fallback_response(self, customer_name: str, category: str) -> str:
        """Réponse de secours si l'IA échoue"""
        return f"""Bonjour {customer_name},

Nous avons bien reçu votre message et nous vous remercions de nous avoir contactés.

Notre équipe va traiter votre demande dans les plus brefs délais et reviendra vers vous rapidement.

En attendant, n'hésitez pas à nous contacter si vous avez d'autres questions.

Cordialement,
L'équipe {self.company_name}"""

    def should_auto_send(self, category: str, confidence: float,
                         order_context: Dict, auto_rules: Dict) -> Tuple[bool, str]:
        """
        Détermine si une réponse peut être envoyée automatiquement

        Args:
            category: Catégorie de la demande
            confidence: Score de confiance de la classification
            order_context: Contexte de la commande
            auto_rules: Règles d'automatisation configurées

        Returns:
            Tuple (peut envoyer auto, raison)
        """

        # Règles de base
        if confidence < 0.85:
            return False, "Confiance insuffisante"

        # Suivi de commande avec tracking
        if category == "SUIVI":
            if not auto_rules.get('auto_send_tracking', True):
                return False, "Auto-envoi désactivé pour les suivis"

            # Vérifie si on a des infos de tracking (Shopify ou Parcelpanel)
            order = order_context.get('order')
            parcelpanel = order_context.get('parcelpanel_tracking')

            if parcelpanel and parcelpanel.get('status'):
                return True, "Suivi avec tracking Parcelpanel disponible"
            elif order and order.get('tracking_number'):
                return True, "Suivi avec tracking Shopify disponible"
            else:
                return False, "Pas de tracking disponible"

        # Les autres catégories nécessitent une validation manuelle
        return False, f"Catégorie {category} requiert validation manuelle"


def test_ai_connection(api_key: str) -> Dict:
    """Teste la connexion à l'API Claude"""
    result = {
        'success': False,
        'message': ''
    }

    try:
        client = anthropic.Anthropic(api_key=api_key)

        # Test simple
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=50,
            messages=[{"role": "user", "content": "Dis simplement 'Connexion OK'"}]
        )

        if response.content:
            result['success'] = True
            result['message'] = "Connexion à Claude réussie !"
        else:
            result['message'] = "Réponse vide de Claude"

    except anthropic.AuthenticationError:
        result['message'] = "Clé API invalide"
    except Exception as e:
        result['message'] = f"Erreur: {str(e)}"

    return result
