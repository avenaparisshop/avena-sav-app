"""
Module de détection automatique de spam pour Avena SAV
Apprend des emails marqués comme spam par l'utilisateur
"""
import re
import logging
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)

# Patterns connus de spam (basés sur les emails du dossier Courrier indésirable)
# Ces patterns sont extraits des emails que l'utilisateur a déjà marqués comme spam

SPAM_SENDER_PATTERNS = [
    # Domaines suspects (faux Facebook/Meta/TikTok)
    r'@.*\.edu\.',  # Emails depuis des .edu suspects
    r'@.*\.ac\.',   # Emails depuis des domaines académiques suspects
    r'facebook.*@(?!facebookmail\.com)',  # Faux Facebook
    r'meta.*@(?!meta\.com|metamail\.com)',  # Faux Meta
    r'tiktok.*@(?!tiktok\.com)',  # Faux TikTok
    r'@.*ksmg\.org',  # Domaine spam connu
    r'@.*thoimmo\.com',  # Domaine spam connu
    r'@ns\.',  # Sous-domaines ns suspects
]

SPAM_SUBJECT_PATTERNS = [
    # Menaces de compte
    r'account.*suspend',
    r'account.*restrict',
    r'compte.*suspendu',
    r'compte.*restreint',
    r'account.*disabled',
    r'compte.*désactivé',
    r'violation.*policy',
    r'violation.*règl',
    r'enforcement.*measure',
    r'mesure.*application',

    # Urgence Facebook/Meta
    r'facebook.*urgent',
    r'meta.*urgent',
    r'page.*facebook.*viola',
    r'pagina.*facebook.*viola',
    r'advertising.*account',
    r'compte.*publicitaire',

    # Phishing générique
    r'verify.*account',
    r'vérif.*compte',
    r'confirm.*identity',
    r'confirm.*identité',
    r'update.*payment',
    r'mettre.*jour.*paiement',
    r'unusual.*activity',
    r'activité.*inhabituelle',

    # Faux problèmes de livraison
    r'delivery.*fail',
    r'livraison.*échou',
    r'package.*held',
    r'colis.*retenu',

    # Arnaques classiques
    r'lottery.*winner',
    r'gagn.*loterie',
    r'inheritance',
    r'héritage',
    r'nigerian.*prince',
]

SPAM_BODY_PATTERNS = [
    # Liens suspects
    r'click.*here.*immediately',
    r'cliquez.*ici.*immédiatement',
    r'act.*now.*avoid',
    r'agissez.*maintenant',
    r'within.*24.*hours',
    r'dans.*24.*heures',
    r'account.*will.*be.*deleted',
    r'compte.*sera.*supprimé',

    # Demandes d'infos sensibles
    r'send.*password',
    r'envoy.*mot.*passe',
    r'credit.*card.*number',
    r'numéro.*carte',
    r'social.*security',
    r'numéro.*sécurité.*sociale',
]

# Expéditeurs légitimes à ne jamais bloquer
WHITELIST_SENDERS = [
    r'@shopify\.com$',
    r'@shop\.app$',
    r'@klaviyo\.com$',
    r'@mailchimp\.com$',
    r'@stripe\.com$',
    r'@paypal\.com$',
    r'@colissimo\.fr$',
    r'@laposte\.fr$',
    r'@chronopost\.fr$',
    r'@ups\.com$',
    r'@dhl\.com$',
    r'@fedex\.com$',
    r'@mondialrelay\.fr$',
    r'@avena-paris\.com$',
    r'@avenaparis\.com$',
]

# Sujets légitimes (commandes, suivi, etc.)
WHITELIST_SUBJECTS = [
    r'commande.*#\d+',
    r'order.*#\d+',
    r'suivi.*colis',
    r'tracking',
    r'expédition',
    r'shipment',
    r'livraison.*confirmée',
    r'delivery.*confirmed',
]


def is_whitelisted(sender_email: str, subject: str) -> bool:
    """Vérifie si l'email est dans la whitelist (ne jamais bloquer)"""
    sender_lower = sender_email.lower()
    subject_lower = subject.lower() if subject else ''

    # Check whitelist expéditeurs
    for pattern in WHITELIST_SENDERS:
        if re.search(pattern, sender_lower, re.IGNORECASE):
            return True

    # Check whitelist sujets
    for pattern in WHITELIST_SUBJECTS:
        if re.search(pattern, subject_lower, re.IGNORECASE):
            return True

    return False


def detect_spam(sender_email: str, sender_name: str, subject: str, body: str) -> Tuple[bool, float, str]:
    """
    Détecte si un email est du spam

    Returns:
        Tuple (is_spam, confidence, reason)
    """
    # D'abord vérifier la whitelist
    if is_whitelisted(sender_email, subject):
        return False, 0.0, "whitelisted"

    sender_lower = sender_email.lower() if sender_email else ''
    sender_name_lower = sender_name.lower() if sender_name else ''
    subject_lower = subject.lower() if subject else ''
    body_lower = body.lower() if body else ''

    spam_score = 0.0
    reasons = []

    # Check patterns expéditeur (poids: 0.4)
    for pattern in SPAM_SENDER_PATTERNS:
        if re.search(pattern, sender_lower, re.IGNORECASE):
            spam_score += 0.4
            reasons.append(f"sender_pattern:{pattern[:20]}")
            break

    # Check patterns sujet (poids: 0.35)
    subject_matches = 0
    for pattern in SPAM_SUBJECT_PATTERNS:
        if re.search(pattern, subject_lower, re.IGNORECASE):
            subject_matches += 1
            if subject_matches == 1:
                spam_score += 0.35
                reasons.append(f"subject_pattern:{pattern[:20]}")
            elif subject_matches > 1:
                spam_score += 0.1  # Bonus pour multiples matches

    # Check patterns body (poids: 0.25)
    body_matches = 0
    for pattern in SPAM_BODY_PATTERNS:
        if re.search(pattern, body_lower, re.IGNORECASE):
            body_matches += 1
            if body_matches == 1:
                spam_score += 0.25
                reasons.append(f"body_pattern:{pattern[:20]}")
            elif body_matches > 1:
                spam_score += 0.05

    # Bonus si le nom de l'expéditeur contient des mots suspects
    suspicious_names = ['facebook', 'meta', 'tiktok', 'instagram', 'support', 'security', 'admin']
    for word in suspicious_names:
        if word in sender_name_lower and not is_whitelisted(sender_email, subject):
            # Vérifie que ce n'est pas un vrai email officiel
            if not any(legit in sender_lower for legit in ['@facebook.com', '@meta.com', '@tiktok.com', '@instagram.com']):
                spam_score += 0.15
                reasons.append(f"suspicious_name:{word}")
                break

    # Cap le score à 1.0
    spam_score = min(spam_score, 1.0)

    # Seuil de détection: 0.5
    is_spam = spam_score >= 0.5

    reason = "; ".join(reasons) if reasons else "no_match"

    if is_spam:
        logger.info(f"SPAM détecté (score={spam_score:.2f}): {sender_email} - {subject[:50]}... | Raisons: {reason}")

    return is_spam, spam_score, reason


def classify_email(email_data: Dict) -> Dict:
    """
    Classifie un email et ajoute les infos de spam

    Args:
        email_data: Dict avec sender_email, sender_name, subject, body

    Returns:
        email_data enrichi avec is_spam, spam_score, spam_reason
    """
    is_spam, spam_score, reason = detect_spam(
        email_data.get('sender_email', ''),
        email_data.get('sender_name', ''),
        email_data.get('subject', ''),
        email_data.get('body', '')
    )

    email_data['is_spam'] = is_spam
    email_data['spam_score'] = spam_score
    email_data['spam_reason'] = reason

    return email_data


# Pour permettre d'ajouter dynamiquement des patterns (apprentissage)
def add_spam_sender_pattern(pattern: str):
    """Ajoute un pattern d'expéditeur spam"""
    if pattern not in SPAM_SENDER_PATTERNS:
        SPAM_SENDER_PATTERNS.append(pattern)
        logger.info(f"Pattern spam ajouté: {pattern}")


def add_spam_subject_pattern(pattern: str):
    """Ajoute un pattern de sujet spam"""
    if pattern not in SPAM_SUBJECT_PATTERNS:
        SPAM_SUBJECT_PATTERNS.append(pattern)
        logger.info(f"Pattern sujet spam ajouté: {pattern}")
