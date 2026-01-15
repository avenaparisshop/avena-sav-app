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

    # === DOMAINES SPAM EXTRAITS DE ZOHO (Courrier indésirable) ===
    r'@.*\.edu\.pe$',       # Pérou - ayacucho.edu.pe
    r'@.*\.edu\.mx$',       # Mexique - cobatlaxcala.edu.mx
    r'@.*\.edu\.ag$',       # Antigua - jss.edu.ag
    r'@.*\.ac\.th$',        # Thaïlande - banjong.ac.th
    r'@.*\.ac\.tz$',        # Tanzanie - mustudent.ac.tz
    r'@.*amcoedu\.org$',    # mx.amcoedu.org
    r'@.*sell9proxy\.com$', # ns.sell9proxy.com
    r'@.*bigblue\.io$',     # bigblue.io - démarchage
    r'@.*medias-france\.fr$',  # medias-france.fr
    r'@.*datanetsystemslimited\.co\.uk$',  # UK spam
    r'@.*omnisend\.com$',   # omnisend.com - spam marketing
    r'@mail\.ru$',          # mail.ru - spam russe

    # === FAUX SUPPORT SHOPIFY (Gmail) ===
    r'shopify.*@gmail\.com',           # shopifykelvinteam, shopifyappguide, etc.
    r'info\.shopify.*@gmail\.com',     # info.shopifystoresb.co, etc.
    r'contact\.shopify.*@gmail\.com',  # contact.shopifymailer
    r'mailer\.shopify.*@gmail\.com',   # mailer.shopifycomplianceservice
    r'support.*shopify.*@gmail\.com',  # support Shopify fake

    # === GMAIL SUSPECTS (patterns de noms) ===
    r'.*digital\d+@gmail\.com',        # horlarfydigital128, bastechdigital003
    r'.*expert\d+@gmail\.com',         # bolajiexpert409
    r'.*concept\d+@gmail\.com',        # elizabethconcept09
    r'.*diamond\d+@gmail\.com',        # kennydiamond39
    r'.*agency\d+@gmail\.com',         # wuraagency7
    r'.*blessing@gmail\.com',          # ashiabyblessing
    r'.*samson\d+@gmail\.com',         # danielsamson7654
    r'.*zaid\d+@gmail\.com',           # aminahzaid670
    r'.*millen\d+@gmail\.com',         # elisemillen5
    r'.*delta@gmail\.com',             # monicaadelta
    r'.*treasured\d+@gmail\.com',      # treasured399
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

    # === ARNAQUES SHOPIFY EN ITALIEN (extraites de Zoho) ===
    r'problema.*di.*pagamento.*checkout',  # Problema di pagamento (checkout)
    r'problemi.*di.*checkout',             # problemi di checkout Shopify
    r'supporto.*urgente.*problemi',        # Supporto urgente: problemi
    r'aggiornamento.*sul.*checkout',       # aggiornamento sul checkout
    r'avviso.*di.*sicurezza',              # Avviso di Sicurezza
    r'pagamenti.*di.*due.*clienti',        # pagamenti di due clienti bloccati
    r'conformità.*alla.*licenza',          # conformità alla licenza proprietaria
    r'problème.*lors.*du.*processus',      # FR: problème lors du processus de paiement

    # === SUJETS VIDES OU GÉNÉRIQUES SUSPECTS ===
    r'^aucun.*objet$',                     # (Aucun objet)
    r'^hello$',                            # Juste "Hello"
    r'^hola$',                             # Juste "Hola"
    r'^hi$',                               # Juste "Hi"
    r'^hey$',                              # Juste "Hey"
    r'^avenaparis$',                       # Juste "Avenaparis"
    r'^avena.*paris$',                     # Juste "Avena Paris"
    r'^quick.*chat$',                      # Quick chat
    r'^new.*message.*for',                 # New message for Avenaparis

    # === DÉMARCHAGE / PROSPECTION ===
    r'web.*design.*development.*services', # Web Design & Development Services
    r'hire.*contemporary.*web',            # Hire Contemporary Web
    r'dropshipping.*cost.*down',           # Dropshipping cost down
    r'buyers.*decide.*trust',              # Buyers Decide Trust in Seconds
    r'smart.*reviews.*start',              # Smart Reviews Start With
    r'i\'ll.*rebuild.*it',                 # I'll Rebuild It
    r'cannes.*connect',                    # Cannes&Connect
    r'selection.*finale',                  # Sélection finale
    r'how.*do.*you.*see.*this',            # How do you see this
    r'i.*love.*your.*product',             # I love your product ❤

    # === DÉMARCHAGE COMMERCIAL NON SOLLICITÉ ===
    # Services B2B / Agences
    r'boost.*your.*business',
    r'boost.*votre.*entreprise',
    r'grow.*your.*business',
    r'développ.*votre.*activité',
    r'increase.*your.*sales',
    r'augment.*vos.*ventes',
    r'partnership.*opportunity',
    r'opportunité.*partenariat',
    r'collaboration.*proposal',
    r'proposition.*collaboration',
    r'business.*proposal',
    r'proposition.*commerciale',
    r'offer.*services',
    r'propos.*services',
    r'looking.*for.*partner',
    r'recherch.*partenaire',

    # SEO / Marketing digital
    r'seo.*services',
    r'référencement.*site',
    r'rank.*google',
    r'premier.*google',
    r'améliorer.*visibilité',
    r'improve.*visibility',
    r'digital.*marketing',
    r'marketing.*digital',
    r'social.*media.*marketing',
    r'community.*manager',
    r'influencer.*marketing',
    r'marketing.*influence',
    r'lead.*generation',
    r'génération.*leads',

    # Développement web / Apps
    r'website.*redesign',
    r'refonte.*site',
    r'mobile.*app.*develop',
    r'développ.*application',
    r'ecommerce.*solution',
    r'solution.*ecommerce',
    r'shopify.*expert',
    r'expert.*shopify',

    # Services financiers non sollicités
    r'business.*loan',
    r'prêt.*entreprise',
    r'financement.*rapide',
    r'quick.*funding',
    r'merchant.*cash',
    r'avance.*trésorerie',

    # Sourcing / Fournisseurs
    r'factory.*direct',
    r'usine.*direct',
    r'wholesale.*supplier',
    r'fournisseur.*gros',
    r'alibaba',
    r'made.*in.*china',
    r'manufacturer.*offer',
    r'fabricant.*propos',
    r'product.*sourcing',
    r'sourcing.*produit',

    # Recrutement non sollicité
    r'outsourc.*team',
    r'équipe.*offshore',
    r'virtual.*assistant',
    r'assistant.*virtuel',
    r'hire.*developer',
    r'recrut.*développeur',

    # Invitations événements / webinars
    r'exclusive.*invitation',
    r'invitation.*exclusive',
    r'webinar.*invitation',
    r'invitation.*webinaire',
    r'free.*consultation',
    r'consultation.*gratuite',
    r'free.*audit',
    r'audit.*gratuit',
    r'limited.*time.*offer',
    r'offre.*limitée',
    r'special.*discount',
    r'réduction.*spéciale',

    # === INFLUENCEURS / AFFILIÉS / UGC ===
    r'influencer',
    r'influenceur',
    r'ugc.*creator',
    r'créateur.*ugc',
    r'content.*creator',
    r'créateur.*contenu',
    r'brand.*ambassador',
    r'ambassadeur',
    r'affiliate.*program',
    r'programme.*affiliation',
    r'commission.*based',
    r'basé.*commission',
    r'confirmed.*orders',
    r'commandes.*confirmées',
    r'success.*based',
    r'strategic.*creative',
    r'creative.*expert',
    r'creative.*agency',
    r'agence.*créative',

    # === QUESTIONS COMMERCIALES NON-CLIENTS ===
    r'do.*you.*ship.*to',
    r'livrez.*vous',
    r'expédiez.*vous',
    r'ship.*internationally',
    r'livraison.*international',
    r'wholesale.*inquiry',
    r'demande.*gros',
    r'bulk.*order',
    r'commande.*volume',
    r'reseller',
    r'revendeur',
    r'distributor',
    r'distributeur',
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

    # === DÉMARCHAGE COMMERCIAL (dans le corps) ===
    r'i.*came.*across.*your.*website',
    r'j.*ai.*découvert.*votre.*site',
    r'i.*found.*your.*company',
    r'j.*ai.*trouvé.*votre.*entreprise',
    r'i.*am.*reaching.*out',
    r'je.*me.*permets.*de.*vous.*contacter',
    r'je.*vous.*contacte.*car',
    r'we.*specialize.*in',
    r'nous.*sommes.*spécialisés',
    r'our.*agency',
    r'notre.*agence',
    r'our.*team.*can.*help',
    r'notre.*équipe.*peut.*vous.*aider',
    r'book.*a.*call',
    r'réserv.*un.*appel',
    r'schedule.*a.*meeting',
    r'planifi.*une.*réunion',
    r'let.*me.*know.*if.*interested',
    r'dites.*moi.*si.*vous.*êtes.*intéressé',
    r'would.*you.*be.*open.*to',
    r'seriez.*vous.*ouvert.*à',
    r'i.*would.*love.*to.*discuss',
    r'j.*aimerais.*discuter',
    r'quick.*question',
    r'petite.*question',
    r'shall.*i.*send.*more.*info',
    r'puis.*je.*vous.*envoyer.*plus.*d.*info',
    r'looking.*forward.*to.*your.*reply',
    r'dans.*l.*attente.*de.*votre.*réponse',
    r'best.*rates.*guarantee',
    r'meilleurs.*tarifs',
    r'increase.*traffic',
    r'augmenter.*trafic',
    r'boost.*conversions',
    r'optimiser.*conversions',
    r'roi.*guarantee',
    r'garantie.*retour.*investissement',
    r'free.*trial',
    r'essai.*gratuit',
    r'no.*obligation',
    r'sans.*engagement',

    # === DÉMARCHAGE INFLUENCEURS / AFFILIÉS / UGC ===
    r'confirmed.*orders',
    r'commandes.*confirmées',
    r'commission.*based',
    r'basé.*sur.*commission',
    r'success.*based.*commission',
    r'paid.*only.*after.*sales',
    r'payé.*après.*ventes',
    r'growth.*goals',
    r'objectifs.*croissance',
    r'ugc.*creator',
    r'créateur.*ugc',
    r'content.*creator',
    r'créateur.*contenu',
    r'brand.*ambassador',
    r'ambassadeur.*marque',
    r'affiliate',
    r'affiliation',
    r'influencer.*marketing',
    r'marketing.*influence',
    r'collab.*proposal',
    r'proposition.*collab',
    r'work.*together',
    r'travailler.*ensemble',
    r'partnership.*inquiry',
    r'demande.*partenariat',
    r'how.*does.*\d+.*orders.*sound',
    r'que.*pensez.*vous.*de.*\d+.*commandes',
    r'before.*january',
    r'avant.*janvier',
    r'before.*february',
    r'before.*march',
    r'interested.*in.*promoting',
    r'intéressé.*promouvoir',

    # === QUESTIONS SHIPPING NON-CLIENTS ===
    r'do.*you.*ship.*to',
    r'ship.*to.*the.*united.*states',
    r'ship.*to.*usa',
    r'ship.*to.*uk',
    r'ship.*internationally',
    r'livrez.*vous.*à',
    r'expédiez.*vous',
    r'international.*shipping',
    r'livraison.*internationale',

    # === DEMANDES B2B / WHOLESALE ===
    r'wholesale.*price',
    r'prix.*gros',
    r'bulk.*order',
    r'commande.*volume',
    r'reseller.*discount',
    r'remise.*revendeur',
    r'distributor.*inquiry',
    r'devenir.*distributeur',
    r'retail.*partnership',
    r'partenariat.*retail',
]

# Expéditeurs légitimes à ne jamais bloquer
# IMPORTANT: Ces domaines sont vérifiés strictement - les emails de ces domaines
# ne seront JAMAIS marqués comme spam
WHITELIST_SENDERS = [
    # === SHOPIFY (tous les domaines officiels) ===
    r'@shopify\.com$',
    r'@shopifymail\.com$',
    r'@shopifyemail\.com$',
    r'@shop\.app$',
    r'@shops\.app$',
    r'@myshopify\.com$',

    # === META / FACEBOOK / INSTAGRAM (tous les domaines officiels) ===
    r'@facebookmail\.com$',      # Notifications Facebook officielles
    r'@facebook\.com$',
    r'@fb\.com$',
    r'@meta\.com$',
    r'@metamail\.com$',
    r'@instagram\.com$',
    r'@mail\.instagram\.com$',
    r'@business\.fb\.com$',
    r'@support\.facebook\.com$',
    r'@notification\.facebook\.com$',
    r'@mediapartners\.facebook\.com$',

    # === GOOGLE / YOUTUBE ===
    r'@google\.com$',
    r'@googlemail\.com$',
    r'@youtube\.com$',
    r'@accounts\.google\.com$',

    # === TIKTOK (domaines officiels) ===
    r'@tiktok\.com$',
    r'@tiktokmail\.com$',
    r'@bytedance\.com$',

    # === MARKETING / CRM ===
    r'@klaviyo\.com$',
    r'@klaviyomail\.com$',
    r'@mailchimp\.com$',
    r'@mailchimpapp\.com$',
    r'@sendinblue\.com$',
    r'@brevo\.com$',
    r'@hubspot\.com$',
    r'@hubspotmail\.com$',

    # === PAIEMENTS ===
    r'@stripe\.com$',
    r'@stripemail\.com$',
    r'@paypal\.com$',
    r'@paypal\.fr$',
    r'@e\.paypal\.com$',
    r'@e\.paypal\.fr$',
    r'@mollie\.com$',
    r'@alma\.eu$',

    # === TRANSPORTEURS FRANCE ===
    r'@colissimo\.fr$',
    r'@laposte\.fr$',
    r'@notification\.laposte\.fr$',
    r'@chronopost\.fr$',
    r'@mondialrelay\.fr$',
    r'@mondialrelay\.com$',
    r'@relais-colis\.com$',
    r'@gls-france\.com$',
    r'@dpd\.fr$',

    # === TRANSPORTEURS INTERNATIONAUX ===
    r'@ups\.com$',
    r'@upsemail\.com$',
    r'@dhl\.com$',
    r'@dhl\.fr$',
    r'@fedex\.com$',
    r'@track\.aftership\.com$',
    r'@parcelpanel\.com$',
    r'@17track\.net$',

    # === E-COMMERCE / MARKETPLACES ===
    r'@amazon\.fr$',
    r'@amazon\.com$',
    r'@marketplace\.amazon\.fr$',
    r'@etsy\.com$',
    r'@ebay\.fr$',
    r'@ebay\.com$',

    # === ZOHO (votre propre système) ===
    r'@zoho\.com$',
    r'@zohomail\.com$',

    # === AVENA (votre domaine) ===
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
    suspicious_names = [
        'facebook', 'meta', 'tiktok', 'instagram', 'support', 'security', 'admin',
        # Noms génériques de démarcheurs
        'strategic', 'creative', 'agency', 'marketing', 'growth', 'partner',
        'influencer', 'ugc', 'ambassador', 'affiliate', 'expert', 'consultant',
        'solutions', 'services', 'digital', 'media', 'studio', 'labs'
    ]
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
