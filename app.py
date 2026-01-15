"""
Application principale Flask - Avena SAV
Dashboard de gestion des emails SAV avec IA
"""
import os
import re
from flask import Flask, render_template, request, jsonify, redirect, url_for
from datetime import datetime
import threading
import time
import logging
from werkzeug.middleware.proxy_fix import ProxyFix

from config import get_config
from models import db, Email, ShopifyToken, SentEmail
from modules.email_handler import ZohoEmailHandler, test_zoho_connection
from modules.shopify_handler import ShopifyHandler, test_shopify_connection
from modules.ai_responder import AIResponder, test_ai_connection
from modules.shopify_oauth import ShopifyOAuth, ShopifyTokenStorage, ShopifyTokenStorageDB, get_oauth_handler, get_oauth_handler_for_shop, get_permanent_access_token
from modules.parcelpanel_handler import get_parcelpanel_manager, test_parcelpanel_connection

# Configuration logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def create_app():
    """Factory pour crÃ©er l'application Flask"""
    app = Flask(__name__)

    # Chargement config
    config = get_config()
    app.config.from_object(config)

    # Support pour les proxys (Railway, Heroku, etc.)
    # Permet Ã  Flask de dÃ©tecter correctement HTTPS derriÃ¨re un reverse proxy
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

    # Force HTTPS pour les URLs gÃ©nÃ©rÃ©es (important pour OAuth)
    app.config['PREFERRED_URL_SCHEME'] = 'https'

    # Init database
    db.init_app(app)

    with app.app_context():
        db.create_all()

    return app


app = create_app()

# Handlers globaux (initialisÃ©s au premier besoin)
email_handler = None
shopify_handlers = {}  # Dict de handlers par shop
ai_responder = None
token_storage = None


def get_token_storage_instance():
    """Lazy loading du storage de tokens - utilise la base de donnÃ©es pour persistance"""
    global token_storage
    if token_storage is None:
        # Utilise le stockage en base de donnÃ©es (persistant mÃªme aprÃ¨s redÃ©ploiement)
        token_storage = ShopifyTokenStorageDB(db, ShopifyToken)
    return token_storage


def get_email_handler():
    """Lazy loading du handler email"""
    global email_handler
    if email_handler is None:
        email_handler = ZohoEmailHandler(
            email_address=app.config['ZOHO_EMAIL'],
            password=app.config['ZOHO_PASSWORD'],
            imap_server=app.config['ZOHO_IMAP_SERVER'],
            smtp_server=app.config['ZOHO_SMTP_SERVER']
        )
    return email_handler


def get_shopify_handler(shop_name: str = None):
    """
    Lazy loading du handler Shopify pour un shop spÃ©cifique

    Args:
        shop_name: Nom du shop (ex: avena-paris). Si None, utilise le shop par dÃ©faut.

    Returns:
        ShopifyHandler ou None si aucun token disponible
    """
    global shopify_handlers

    # Si pas de shop spÃ©cifiÃ©, essaie le shop par dÃ©faut
    if shop_name is None:
        shop_name = app.config.get('SHOPIFY_SHOP_NAME')

    if not shop_name:
        # Essaie de prendre le premier shop connectÃ©
        storage = get_token_storage_instance()
        shops = storage.get_all_shops()
        if shops:
            shop_name = list(shops.keys())[0]
        else:
            logger.warning("Aucun shop Shopify configurÃ©")
            return None

    # VÃ©rifie si on a dÃ©jÃ  un handler pour ce shop
    if shop_name in shopify_handlers:
        return shopify_handlers[shop_name]

    # 1. D'abord essaie les tokens permanents configurÃ©s dans SHOPIFY_CREDENTIALS
    access_token = get_permanent_access_token(shop_name)

    # 2. Si pas de token permanent, essaie le storage DB/fichier (OAuth)
    if not access_token:
        storage = get_token_storage_instance()
        access_token = storage.get_token(shop_name)

    # 3. Si pas de token OAuth, essaie le token legacy
    if not access_token and shop_name == app.config.get('SHOPIFY_SHOP_NAME'):
        access_token = app.config.get('SHOPIFY_ACCESS_TOKEN')

    if not access_token:
        logger.warning(f"Pas de token disponible pour {shop_name}")
        return None

    # CrÃ©e le handler
    handler = ShopifyHandler(
        shop_name=shop_name,
        access_token=access_token
    )

    shopify_handlers[shop_name] = handler
    return handler


def get_all_shopify_handlers():
    """Retourne les handlers pour tous les shops connectÃ©s"""
    storage = get_token_storage_instance()
    shops = storage.get_all_shops()

    handlers = {}
    for shop_name in shops.keys():
        handler = get_shopify_handler(shop_name)
        if handler:
            handlers[shop_name] = handler

    return handlers


def get_ai_responder():
    """Lazy loading du responder IA"""
    global ai_responder
    if ai_responder is None:
        ai_responder = AIResponder(
            api_key=app.config['ANTHROPIC_API_KEY'],
            company_name=app.config.get('COMPANY_NAME', 'Avena Paris')
        )
    return ai_responder


# ============================================
# ROUTES - PAGES
# ============================================

@app.route('/')
def index():
    """Page d'accueil - Dashboard"""
    return render_template('dashboard.html')


@app.route('/settings')
def settings():
    """Page de configuration"""
    return render_template('settings.html')


@app.route('/stores')
def stores():
    """Page de gestion des stores Shopify connectÃ©s"""
    import json

    # RÃ©cupÃ¨re les shops connectÃ©s via OAuth (DB)
    storage = get_token_storage_instance()
    connected_shops = storage.get_all_shops()

    # Ajoute aussi les shops avec access_token permanent dans SHOPIFY_CREDENTIALS
    credentials_json = os.environ.get('SHOPIFY_CREDENTIALS', '{}')
    try:
        credentials = json.loads(credentials_json)
        for shop_key, creds in credentials.items():
            if creds.get('access_token') and shop_key not in connected_shops:
                connected_shops[shop_key] = {
                    'shop_domain': f"{shop_key}.myshopify.com",
                    'shop_name': shop_key,
                    'connected_at': 'Permanent Token',
                    'permanent': True
                }
    except json.JSONDecodeError:
        pass

    return render_template('stores.html', shops=connected_shops)


# ============================================
# ROUTES - SHOPIFY OAUTH
# ============================================

@app.route('/shopify/install')
def shopify_install():
    """
    Lance l'installation OAuth pour un shop Shopify
    ParamÃ¨tre: ?shop=nom-du-shop (sans .myshopify.com)
    """
    shop = request.args.get('shop')

    if not shop:
        return render_template('shopify_install.html')

    # VÃ©rifie que les credentials OAuth sont configurÃ©s
    if not app.config.get('SHOPIFY_CLIENT_ID') or not app.config.get('SHOPIFY_CLIENT_SECRET'):
        return jsonify({
            'success': False,
            'message': 'SHOPIFY_CLIENT_ID et SHOPIFY_CLIENT_SECRET non configurÃ©s'
        }), 500

    try:
        # Utilise les credentials spÃ©cifiques au shop si disponibles
        oauth = get_oauth_handler_for_shop(shop)

        # GÃ©nÃ¨re une clÃ© state pour la sÃ©curitÃ© CSRF
        import secrets
        state = secrets.token_urlsafe(32)

        # Stocke le state en session
        from flask import session
        session['shopify_oauth_state'] = state
        session['shopify_oauth_shop'] = shop

        # Construit l'URL de redirection
        redirect_uri = url_for('shopify_callback', _external=True)

        # GÃ©nÃ¨re l'URL d'installation
        install_url = oauth.generate_install_url(
            shop_domain=shop,
            redirect_uri=redirect_uri,
            state=state
        )

        return redirect(install_url)

    except Exception as e:
        logger.error(f"Erreur installation Shopify: {e}")
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500


@app.route('/shopify/callback')
def shopify_callback():
    """
    Callback OAuth aprÃ¨s autorisation Shopify
    ReÃ§oit le code d'autorisation et l'Ã©change contre un access token
    """
    # RÃ©cupÃ¨re les paramÃ¨tres
    code = request.args.get('code')
    shop = request.args.get('shop')
    state = request.args.get('state')
    hmac_param = request.args.get('hmac')

    if not code or not shop:
        return render_template('oauth_error.html',
                               error="ParamÃ¨tres manquants dans le callback OAuth")

    # VÃ©rifie le state (protection CSRF)
    from flask import session
    expected_state = session.get('shopify_oauth_state')
    if state and expected_state and state != expected_state:
        return render_template('oauth_error.html',
                               error="State invalide - possible attaque CSRF")

    try:
        # Utilise les credentials spÃ©cifiques au shop si disponibles
        oauth = get_oauth_handler_for_shop(shop)

        # Ãchange le code contre un token
        access_token, error = oauth.exchange_code_for_token(shop, code)

        if error:
            return render_template('oauth_error.html', error=error)

        if not access_token:
            return render_template('oauth_error.html',
                                   error="Impossible d'obtenir l'access token")

        # RÃ©cupÃ¨re les infos du shop
        shop_info = oauth.get_shop_info(shop, access_token)

        # Stocke le token
        storage = get_token_storage_instance()
        storage.store_token(shop, access_token, shop_info)

        # Nettoie la session
        session.pop('shopify_oauth_state', None)
        session.pop('shopify_oauth_shop', None)

        # Invalide le cache du handler pour ce shop
        shop_key = shop.replace('.myshopify.com', '')
        if shop_key in shopify_handlers:
            del shopify_handlers[shop_key]

        logger.info(f"Shop {shop} connectÃ© avec succÃ¨s")

        return render_template('oauth_success.html',
                               shop=shop,
                               shop_info=shop_info)

    except Exception as e:
        logger.error(f"Erreur callback OAuth: {e}")
        return render_template('oauth_error.html', error=str(e))


@app.route('/shopify/disconnect/<shop_name>')
def shopify_disconnect(shop_name):
    """DÃ©connecte un shop Shopify"""
    storage = get_token_storage_instance()
    storage.remove_token(shop_name)

    # Invalide le cache du handler
    if shop_name in shopify_handlers:
        del shopify_handlers[shop_name]

    logger.info(f"Shop {shop_name} dÃ©connectÃ©")

    return redirect(url_for('stores'))


@app.route('/api/shops', methods=['GET'])
def api_get_shops():
    """API: Liste des shops connectÃ©s"""
    storage = get_token_storage_instance()
    shops = storage.get_all_shops()

    # Retire les tokens de la rÃ©ponse pour la sÃ©curitÃ©
    safe_shops = {}
    for shop_name, data in shops.items():
        safe_shops[shop_name] = {
            'shop_domain': data.get('shop_domain'),
            'shop_name': data.get('shop_name'),
            'shop_email': data.get('shop_email'),
            'connected_at': data.get('connected_at')
        }

    return jsonify({
        'success': True,
        'shops': safe_shops,
        'count': len(shops)
    })


# ============================================
# ROUTES - API
# ============================================

@app.route('/api/emails', methods=['GET'])
def get_emails():
    """RÃ©cupÃ¨re la liste des emails"""
    status = request.args.get('status', 'pending')

    query = Email.query

    if status != 'all':
        query = query.filter_by(status=status)

    emails = query.order_by(Email.received_at.desc()).all()

    # Ajoute l'info has_reply pour chaque email
    emails_data = []
    for e in emails:
        email_dict = e.to_dict()
        # Vérifie si on a une réponse envoyée pour cet email - CASE INSENSITIVE
        sender_lower = e.sender_email.lower() if e.sender_email else ''
        has_reply = SentEmail.query.filter(
            (SentEmail.original_email_id == e.id) |
            (db.func.lower(SentEmail.recipient_email) == sender_lower)
        ).first() is not None
        email_dict['has_reply'] = has_reply
        emails_data.append(email_dict)

    return jsonify({
        'success': True,
        'emails': emails_data,
        'count': len(emails)
    })


@app.route('/api/debug/sent-emails', methods=['GET'])
def debug_sent_emails():
    """Debug: Liste des emails envoyés et correspondances"""
    sent_emails = SentEmail.query.limit(20).all()
    received_emails = Email.query.limit(20).all()

    # Trouve les correspondances
    sent_recipients = set(s.recipient_email.lower() for s in sent_emails if s.recipient_email)
    received_senders = set(e.sender_email.lower() for e in received_emails if e.sender_email)

    matches = sent_recipients.intersection(received_senders)

    return jsonify({
        'sent_count': SentEmail.query.count(),
        'received_count': Email.query.count(),
        'sent_recipients_sample': list(sent_recipients)[:10],
        'received_senders_sample': list(received_senders)[:10],
        'matches': list(matches),
        'match_count': len(matches)
    })


@app.route('/api/emails/<int:email_id>', methods=['GET'])
def get_email(email_id):
    """RÃ©cupÃ¨re un email spÃ©cifique"""
    email = Email.query.get_or_404(email_id)
    return jsonify({
        'success': True,
        'email': email.to_dict()
    })


@app.route('/api/emails/<int:email_id>/approve', methods=['POST'])
def approve_email(email_id):
    """Approuve et envoie une rÃ©ponse"""
    email_record = Email.query.get_or_404(email_id)

    # RÃ©cupÃ¨re la rÃ©ponse (modifiÃ©e ou originale)
    data = request.get_json() or {}
    response_text = data.get('response', email_record.generated_response)

    # VÃ©rifie si la rÃ©ponse a Ã©tÃ© modifiÃ©e
    if response_text != email_record.generated_response:
        email_record.modified_before_send = True
        email_record.generated_response = response_text

    # Envoie l'email
    handler = get_email_handler()
    subject = f"Re: {email_record.subject}"

    success = handler.send_email(
        to_email=email_record.sender_email,
        subject=subject,
        body=response_text,
        reply_to_message_id=email_record.message_id
    )

    if success:
        email_record.status = 'sent'
        email_record.sent_at = datetime.utcnow()
        db.session.commit()

        return jsonify({
            'success': True,
            'message': f'Email envoyÃ© Ã  {email_record.sender_email}'
        })
    else:
        return jsonify({
            'success': False,
            'message': 'Erreur lors de l\'envoi'
        }), 500


@app.route('/api/emails/<int:email_id>/ignore', methods=['POST'])
def ignore_email(email_id):
    """Ignore un email (ne pas rÃ©pondre)"""
    email_record = Email.query.get_or_404(email_id)
    email_record.status = 'ignored'
    email_record.processed_at = datetime.utcnow()
    db.session.commit()

    return jsonify({
        'success': True,
        'message': 'Email marquÃ© comme ignorÃ©'
    })


@app.route('/api/emails/<int:email_id>/regenerate', methods=['POST'])
def regenerate_response(email_id):
    """RÃ©gÃ©nÃ¨re la rÃ©ponse IA"""
    email_record = Email.query.get_or_404(email_id)

    # RÃ©cupÃ¨re le contexte Shopify (si connectÃ©)
    shopify = get_shopify_handler()
    if shopify:
        order_context = shopify.get_order_context(
            order_number=email_record.order_number,
            email=email_record.sender_email
        )
    else:
        order_context = {'order': None, 'customer': None}

    # RÃ©gÃ©nÃ¨re la rÃ©ponse
    ai = get_ai_responder()
    email_data = {
        'subject': email_record.subject,
        'body': email_record.body,
        'sender_name': email_record.sender_name
    }

    new_response = ai.generate_response(
        email_data=email_data,
        order_context=order_context,
        category=email_record.category or 'AUTRE'
    )

    email_record.generated_response = new_response
    db.session.commit()

    return jsonify({
        'success': True,
        'response': new_response
    })



@app.route('/api/fetch-emails', methods=['POST'])
def fetch_new_emails():
    """Recupere les nouveaux emails depuis Zoho - enregistre d'abord, classifie apres"""
    try:
        handler = get_email_handler()

        # Verifie la connexion IMAP
        if not handler.connect_imap():
            logger.error("Impossible de se connecter au serveur IMAP")
            return jsonify({
                'success': False,
                'message': 'Erreur connexion IMAP - verifiez les identifiants Zoho'
            }), 500

        # Import du detecteur de spam (rapide, pas d'IA)
        from modules.spam_detector import detect_spam

        # Recupere les emails - limite a 50 pour eviter les timeouts
        logger.info("Debut recuperation emails depuis IMAP...")
        new_emails = handler.fetch_emails_from_folders(
            folders=["INBOX"],
            limit_per_folder=50
        )
        logger.info(f"Emails recuperes: {len(new_emails)}")

        processed = 0
        spam_count = 0
        to_classify = 0

        for email_data in new_emails:
            # Verifie si deja en base
            existing = Email.query.filter_by(message_id=email_data['message_id']).first()
            if existing:
                continue

            # Detection automatique de spam (RAPIDE - pas d'IA)
            is_spam, spam_score, spam_reason = detect_spam(
                email_data.get('sender_email', ''),
                email_data.get('sender_name', ''),
                email_data.get('subject', ''),
                email_data.get('body', '')
            )

            # Definit la categorie selon le spam
            if is_spam:
                category = 'SPAM'
                confidence = spam_score
                status = 'ignored'
                spam_count += 1
            else:
                # PAS de classification IA ici - on met en attente
                category = 'PENDING'  # Sera classifie apres
                confidence = 0.0
                status = 'pending'
                to_classify += 1

            # Cree l'enregistrement IMMEDIATEMENT
            email_record = Email(
                message_id=email_data['message_id'],
                sender_email=email_data['sender_email'],
                sender_name=email_data.get('sender_name'),
                subject=email_data['subject'],
                body=email_data['body'],
                received_at=email_data.get('received_at'),
                category=category,
                confidence=confidence,
                order_number=email_data.get('order_number'),
                generated_response=None,
                status=status
            )

            db.session.add(email_record)
            db.session.commit()  # Commit chaque email individuellement
            processed += 1
            logger.info(f"Email {processed} enregistre: {email_data.get('subject', '')[:50]}")

        handler.disconnect_imap()

        return jsonify({
            'success': True,
            'message': f'{processed} emails ({spam_count} spam, {to_classify} a classifier)',
            'processed': processed,
            'spam_detected': spam_count,
            'to_classify': to_classify
        })

    except Exception as e:
        import traceback
        logger.error(f"Erreur fetch emails: {e}")
        logger.error(traceback.format_exc())
        return jsonify({
            'success': False,
            'message': f'Erreur: {str(e)}'
        }), 500


@app.route('/api/classify-next', methods=['POST'])
def classify_next_email():
    """Classifie UN SEUL email en attente avec l'IA - appele en boucle par le frontend"""
    try:
        # Trouve le prochain email a classifier (PENDING ou sans categorie valide)
        email = Email.query.filter(
            (Email.category == 'PENDING') |
            (Email.category == None) |
            (Email.category == 'AUTRE') |
            (~Email.category.in_(['AUTO', 'MANUEL', 'SPAM']))
        ).first()

        if not email:
            return jsonify({
                'success': True,
                'done': True,
                'message': 'Tous les emails sont classifies'
            })

        # Classification IA
        try:
            ai_responder = get_ai_responder()
            if ai_responder:
                category, confidence = ai_responder.classify_email(
                    email.subject or '',
                    email.body or ''
                )
                email.category = category
                email.confidence = confidence
                logger.info(f"Email {email.id} classifie: {category} ({confidence:.0%})")
            else:
                email.category = 'MANUEL'
                email.confidence = 0.0
                logger.warning(f"AI non disponible - email {email.id} mis en MANUEL")
        except Exception as e:
            logger.error(f"Erreur classification email {email.id}: {e}")
            email.category = 'MANUEL'
            email.confidence = 0.0

        db.session.commit()

        # Compte combien il en reste
        remaining = Email.query.filter(
            (Email.category == 'PENDING') |
            (Email.category == None) |
            (Email.category == 'AUTRE') |
            (~Email.category.in_(['AUTO', 'MANUEL', 'SPAM']))
        ).count()

        return jsonify({
            'success': True,
            'done': False,
            'classified': {
                'id': email.id,
                'subject': email.subject,
                'category': email.category,
                'confidence': email.confidence
            },
            'remaining': remaining,
            'message': f'Email classifie: {email.category}'
        })

    except Exception as e:
        logger.error(f"Erreur classify-next: {e}")
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500


@app.route('/api/reclassify-emails', methods=['POST'])
def reclassify_all_emails():
    """Reclassifie tous les emails en attente avec l'IA et le detecteur de spam"""
    try:
        from modules.spam_detector import detect_spam

        # Recupere tous les emails pending sans categorie ou avec anciennes categories
        emails_to_classify = Email.query.filter(
            (Email.status == 'pending') |
            (Email.category == None) |
            (Email.category == 'AUTRE') |
            (Email.category.notin_(['AUTO', 'MANUEL', 'SPAM']))
        ).all()

        logger.info(f"Reclassification de {len(emails_to_classify)} emails...")

        reclassified = 0
        spam_detected = 0

        for email in emails_to_classify:
            # D'abord verifier si c'est du spam
            is_spam, spam_score, spam_reason = detect_spam(
                email.sender_email or '',
                email.sender_name or '',
                email.subject or '',
                email.body or ''
            )

            if is_spam:
                email.category = 'SPAM'
                email.confidence = spam_score
                email.status = 'ignored'
                spam_detected += 1
                logger.info(f"Email {email.id} marque SPAM: {spam_reason}")
            else:
                # Classification IA
                try:
                    ai_responder = get_ai_responder()
                    if ai_responder:
                        category, confidence = ai_responder.classify_email(
                            email.subject or '',
                            email.body or ''
                        )
                        email.category = category
                        email.confidence = confidence
                        logger.info(f"Email {email.id} classifie: {category} ({confidence:.0%})")
                except Exception as e:
                    logger.error(f"Erreur classification email {email.id}: {e}")
                    email.category = 'MANUEL'
                    email.confidence = 0.0

            reclassified += 1

        db.session.commit()

        return jsonify({
            'success': True,
            'message': f'{reclassified} emails reclassifies ({spam_detected} spam)',
            'reclassified': reclassified,
            'spam_detected': spam_detected
        })

    except Exception as e:
        logger.error(f"Erreur reclassification: {e}")
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500


@app.route('/api/emails/<int:email_id>/generate', methods=['POST'])
def generate_email_response(email_id):
    """GÃ©nÃ¨re une rÃ©ponse IA pour un email spÃ©cifique - appelÃ© manuellement"""
    try:
        email_record = Email.query.get_or_404(email_id)

        # Si dÃ©jÃ  traitÃ©, retourne la rÃ©ponse existante
        if email_record.generated_response:
            return jsonify({
                'success': True,
                'response': email_record.generated_response,
                'category': email_record.category,
                'already_generated': True
            })

        ai = get_ai_responder()

        # DÃ©tecte la langue de l'email
        email_text = f"{email_record.subject} {email_record.body}"
        language = ai.detect_language(email_text)
        logger.info(f"Langue dÃ©tectÃ©e pour email {email_id}: {language}")

        # Mapping langue -> shop Shopify
        # Les shops sont: tgir1c-x2 (FR), qk16wv-2e (NL), jl1brs-gp (ES),
        # pz5e9e-2e (IT), u06wln-hf (DE), xptmak-r7 (PL), fyh99s-h9 (EN)
        lang_to_shop = {
            'fr': 'tgir1c-x2',      # France
            'nl': 'qk16wv-2e',      # Pays-Bas
            'es': 'jl1brs-gp',      # Espagne
            'it': 'pz5e9e-2e',      # Italie
            'de': 'u06wln-hf',      # Allemagne
            'pl': 'xptmak-r7',      # Pologne
            'en': 'fyh99s-h9'       # Anglais
        }

        target_shop = lang_to_shop.get(language, 'tgir1c-x2')  # DÃ©faut: France
        logger.info(f"Shop cible pour langue {language}: {target_shop}")

        # RÃ©cupÃ¨re le handler Shopify pour le bon shop
        shopify = get_shopify_handler(target_shop)

        # Classifie l'email
        category, confidence = ai.classify_email(
            subject=email_record.subject,
            body=email_record.body
        )

        # RÃ©cupÃ¨re le contexte Shopify (si connectÃ©)
        order_context = {}
        if shopify:
            order_context = shopify.get_order_context(
                order_number=email_record.order_number,
                email=email_record.sender_email
            )
            logger.info(f"Contexte Shopify: order={order_context.get('order') is not None}")
        else:
            order_context = {'order': None, 'customer': None}
            logger.warning(f"Pas de handler Shopify pour {target_shop}")

        # RÃ©cupÃ¨re les infos de tracking Parcelpanel en temps rÃ©el
        parcelpanel_manager = get_parcelpanel_manager()
        tracking_info = None

        if order_context.get('order'):
            order = order_context['order']
            tracking_number = order.get('tracking_number')
            order_num = order.get('order_number') or email_record.order_number

            # Essaie d'abord avec le numÃ©ro de tracking, sinon avec le numÃ©ro de commande
            if tracking_number:
                tracking_info = parcelpanel_manager.get_tracking_for_shop(
                    target_shop, tracking_number=tracking_number
                )
            if not tracking_info and order_num:
                tracking_info = parcelpanel_manager.get_tracking_for_shop(
                    target_shop, order_number=str(order_num)
                )

            if tracking_info:
                order_context['parcelpanel_tracking'] = tracking_info
                logger.info(f"Tracking Parcelpanel trouvÃ©: {tracking_info.get('status_text')}")

        # Met Ã  jour le numÃ©ro de commande si trouvÃ©
        if not email_record.order_number and order_context.get('order'):
            email_record.order_number = order_context['order'].get('order_number')

        # GÃ©nÃ¨re la rÃ©ponse dans la bonne langue
        email_data = {
            'subject': email_record.subject,
            'body': email_record.body,
            'sender_email': email_record.sender_email,
            'sender_name': email_record.sender_name,
            'order_number': email_record.order_number
        }

        response = ai.generate_response(
            email_data=email_data,
            order_context=order_context,
            category=category,
            language=language  # Passe la langue dÃ©tectÃ©e
        )

        # Met Ã  jour l'enregistrement
        email_record.category = category
        email_record.confidence = confidence
        email_record.generated_response = response
        db.session.commit()

        return jsonify({
            'success': True,
            'response': response,
            'category': category,
            'confidence': confidence,
            'language': language,
            'shop_used': target_shop,
            'order_context': {
                'has_order': order_context.get('order') is not None,
                'order_number': email_record.order_number
            }
        })

    except Exception as e:
        logger.error(f"Erreur gÃ©nÃ©ration rÃ©ponse: {e}")
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500


@app.route('/api/extract-sent-emails', methods=['POST'])
def extract_sent_emails():
    """Extrait les emails envoyes pour l'apprentissage IA"""
    import re
    import json

    try:
        handler = get_email_handler()

        # Dossiers possibles pour les emails envoyes
        sent_folders = ["Sent", "Envoye", "Envoyes", "Sent Items", "Sent Mail"]

        sent_emails = []

        for folder in sent_folders:
            handler.disconnect_imap()
            handler.connect_imap()
            emails = handler.fetch_unread_emails(folder=folder, limit=500)
            if emails:
                logger.info(f"Trouve {len(emails)} emails dans {folder}")
                sent_emails.extend(emails)
                break

        if not sent_emails:
            return jsonify({
                'success': False,
                'message': 'Aucun email envoye trouve'
            })

        # Analyse et structure les donnees pour l'apprentissage
        training_data = []

        # Patterns pour categoriser les reponses
        categories = {
            'SUIVI': [
                r'suivi', r'livraison', r'colis', r'expedi', r'tracking',
                r'ou en est', r'quand.*recev', r'delai', r'transporteur'
            ],
            'RETOUR': [
                r'retour', r'rembours', r'echang', r'renvoy', r'renvoie'
            ],
            'PROBLEME': [
                r'probleme', r'defectueu', r'casse', r'abime', r'erreur',
                r'manqu', r'incomplet', r'mauvais', r'endommage'
            ],
            'QUESTION': [
                r'question', r'renseign', r'information', r'savoir'
            ],
            'MODIFICATION': [
                r'modifi', r'chang', r'annul', r'adresse', r'commande'
            ]
        }

        for email_data in sent_emails:
            subject = email_data.get('subject', '') or ''
            body = email_data.get('body', '') or ''
            recipient = email_data.get('sender_email', '')

            if not body.strip():
                continue

            # Determine la categorie
            detected_category = 'AUTRE'
            subject_body = (subject + ' ' + body).lower()

            for cat, patterns in categories.items():
                for pattern in patterns:
                    if re.search(pattern, subject_body, re.IGNORECASE):
                        detected_category = cat
                        break
                if detected_category != 'AUTRE':
                    break

            # Extrait le numero de commande
            order_match = re.search(r'#?(\d{4,6})', subject + ' ' + body)
            order_number = order_match.group(1) if order_match else None

            training_entry = {
                'date': email_data.get('received_at').isoformat() if email_data.get('received_at') else None,
                'recipient': recipient,
                'subject': subject,
                'body': body,
                'category': detected_category,
                'order_number': order_number,
                'word_count': len(body.split())
            }

            training_data.append(training_entry)

        # Statistiques
        stats = {
            'total_emails': len(training_data),
            'by_category': {}
        }

        for entry in training_data:
            cat = entry['category']
            stats['by_category'][cat] = stats['by_category'].get(cat, 0) + 1

        handler.disconnect_imap()

        return jsonify({
            'success': True,
            'stats': stats,
            'emails': training_data,
            'message': f'{len(training_data)} emails extraits pour apprentissage'
        })

    except Exception as e:
        logger.error(f"Erreur extraction emails envoyes: {e}")
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500


@app.route('/api/fetch-sent-emails', methods=['POST'])
def fetch_sent_emails():
    """Importe les emails envoyés depuis le dossier Sent pour les lier aux conversations"""
    try:
        handler = get_email_handler()

        # Dossiers possibles pour les emails envoyés (Zoho)
        sent_folders = ["Sent", "Sent Items", "Sent Mail", "Envoye", "Envoyes", "Envoyé", "Envoyés"]

        if not handler.connect_imap():
            return jsonify({
                'success': False,
                'message': 'Erreur connexion IMAP'
            }), 500

        sent_emails_data = []

        # Essaie chaque dossier jusqu'à trouver le bon
        for folder in sent_folders:
            try:
                handler.disconnect_imap()
                handler.connect_imap()

                # Sélectionne le dossier
                status, _ = handler.imap_connection.select(folder)
                if status != 'OK':
                    continue

                logger.info(f"Dossier Sent trouvé: {folder}")

                # Récupère les emails envoyés (les 50 plus récents pour éviter timeout)
                status, messages = handler.imap_connection.search(None, 'ALL')
                if status != 'OK':
                    continue

                email_ids = messages[0].split()
                # Prend les 50 plus récents (réduit de 200 à 50 pour éviter timeout)
                email_ids = list(reversed(email_ids[-50:]))

                import email as email_lib

                logger.info(f"Import de {len(email_ids)} emails envoyés...")
                processed_count = 0

                for email_id_bytes in email_ids:
                    try:
                        status, msg_data = handler.imap_connection.fetch(email_id_bytes, '(RFC822)')
                        if status != 'OK':
                            continue

                        raw_email = msg_data[0][1]
                        msg = email_lib.message_from_bytes(raw_email)

                        processed_count += 1
                        if processed_count % 10 == 0:
                            logger.info(f"Traité {processed_count}/{len(email_ids)} emails envoyés")

                        # Parse les headers
                        to_header = msg.get('To', '')
                        to_decoded = handler._decode_header_value(to_header)
                        # Extrait email du format "Name <email>"
                        to_match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', to_decoded)
                        recipient_email = to_match.group(0) if to_match else to_decoded

                        to_name_match = re.match(r'^(.+?)\s*<', to_decoded)
                        recipient_name = to_name_match.group(1).strip().strip('"') if to_name_match else ''

                        subject = handler._decode_header_value(msg.get('Subject', ''))
                        body = handler._extract_email_body(msg)
                        message_id = msg.get('Message-ID', '')
                        in_reply_to = msg.get('In-Reply-To', '')
                        references = msg.get('References', '')

                        # Date d'envoi
                        date_str = msg.get('Date', '')
                        try:
                            sent_at = email_lib.utils.parsedate_to_datetime(date_str)
                        except:
                            sent_at = datetime.utcnow()

                        sent_emails_data.append({
                            'message_id': message_id,
                            'recipient_email': recipient_email,
                            'recipient_name': recipient_name,
                            'subject': subject,
                            'body': body,
                            'sent_at': sent_at,
                            'in_reply_to': in_reply_to,
                            'references': references
                        })

                    except Exception as e:
                        logger.error(f"Erreur parsing email envoyé: {e}")
                        continue

                break  # On a trouvé le dossier Sent

            except Exception as e:
                logger.debug(f"Dossier {folder} non accessible: {e}")
                continue

        handler.disconnect_imap()

        if not sent_emails_data:
            return jsonify({
                'success': False,
                'message': 'Aucun email envoyé trouvé'
            })

        # Enregistre les emails en base
        imported = 0
        linked = 0

        for email_data in sent_emails_data:
            # Vérifie si déjà en base
            existing = SentEmail.query.filter_by(message_id=email_data['message_id']).first()
            if existing:
                continue

            # Essaie de lier à l'email original via In-Reply-To
            original_email_id = None
            if email_data['in_reply_to']:
                original = Email.query.filter_by(message_id=email_data['in_reply_to']).first()
                if original:
                    original_email_id = original.id
                    linked += 1

            # Si pas trouvé via In-Reply-To, essaie via l'adresse email et le sujet
            if not original_email_id and email_data['recipient_email']:
                # Cherche un email reçu du même expéditeur avec un sujet similaire
                subject_clean = email_data['subject'].replace('Re: ', '').replace('RE: ', '').strip()
                possible_original = Email.query.filter(
                    Email.sender_email == email_data['recipient_email'],
                    Email.subject.like(f'%{subject_clean[:30]}%')
                ).order_by(Email.received_at.desc()).first()

                if possible_original:
                    original_email_id = possible_original.id
                    linked += 1

            sent_record = SentEmail(
                message_id=email_data['message_id'],
                recipient_email=email_data['recipient_email'],
                recipient_name=email_data['recipient_name'],
                subject=email_data['subject'],
                body=email_data['body'],
                sent_at=email_data['sent_at'],
                in_reply_to=email_data['in_reply_to'],
                references=email_data['references'],
                original_email_id=original_email_id
            )

            db.session.add(sent_record)
            imported += 1

        db.session.commit()

        logger.info(f"Emails envoyés importés: {imported}, liés: {linked}")

        return jsonify({
            'success': True,
            'message': f'{imported} emails envoyés importés ({linked} liés à des conversations)',
            'imported': imported,
            'linked': linked
        })

    except Exception as e:
        import traceback
        logger.error(f"Erreur fetch sent emails: {e}")
        logger.error(traceback.format_exc())
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500


@app.route('/api/emails/<int:email_id>/conversation', methods=['GET'])
def get_email_conversation(email_id):
    """Récupère l'historique complet d'une conversation (emails reçus + envoyés)"""
    try:
        email = Email.query.get_or_404(email_id)
        sender_email_lower = email.sender_email.lower() if email.sender_email else ''

        conversation = []

        # 1. Ajoute l'email principal (reçu)
        email_dict = email.to_dict()
        email_dict['type'] = 'received'
        conversation.append(email_dict)

        # 2. Cherche les réponses envoyées liées à cet email
        # Via original_email_id
        sent_replies = SentEmail.query.filter_by(original_email_id=email_id).all()
        for sent in sent_replies:
            conversation.append(sent.to_dict())

        # 3. Cherche aussi via l'adresse email (même conversation) - CASE INSENSITIVE
        # Emails reçus de la même personne
        other_received = Email.query.filter(
            db.func.lower(Email.sender_email) == sender_email_lower,
            Email.id != email_id
        ).order_by(Email.received_at).all()

        for other in other_received:
            other_dict = other.to_dict()
            other_dict['type'] = 'received'
            # Évite les doublons
            if not any(c.get('message_id') == other_dict['message_id'] for c in conversation):
                conversation.append(other_dict)

        # Emails envoyés à la même personne - CASE INSENSITIVE
        other_sent = SentEmail.query.filter(
            db.func.lower(SentEmail.recipient_email) == sender_email_lower
        ).all()

        logger.info(f"Conversation pour {email_id}: sender={sender_email_lower}, found {len(other_sent)} sent emails")

        for sent in other_sent:
            sent_dict = sent.to_dict()
            # Évite les doublons
            if not any(c.get('message_id') == sent_dict['message_id'] for c in conversation):
                conversation.append(sent_dict)

        # Trie par date
        conversation.sort(key=lambda x: x.get('received_at') or x.get('sent_at') or '')

        # Détermine si on a répondu
        has_reply = any(c.get('type') == 'sent' for c in conversation)

        return jsonify({
            'success': True,
            'email_id': email_id,
            'conversation': conversation,
            'has_reply': has_reply,
            'message_count': len(conversation)
        })

    except Exception as e:
        logger.error(f"Erreur get conversation: {e}")
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500


@app.route('/api/emails/<int:email_id>/send-custom', methods=['POST'])
def send_custom_response(email_id):
    """Envoie une reponse personnalisee (modifiee par l'utilisateur)"""
    email_record = Email.query.get_or_404(email_id)

    data = request.get_json()
    if not data or not data.get('response'):
        return jsonify({
            'success': False,
            'message': 'Reponse manquante'
        }), 400

    response_text = data['response']

    # Marque comme modifie
    email_record.modified_before_send = True
    email_record.generated_response = response_text

    # Envoie l'email
    handler = get_email_handler()
    subject = f"Re: {email_record.subject}"

    success = handler.send_email(
        to_email=email_record.sender_email,
        subject=subject,
        body=response_text,
        reply_to_message_id=email_record.message_id
    )

    if success:
        email_record.status = 'sent'
        email_record.sent_at = datetime.utcnow()
        db.session.commit()

        return jsonify({
            'success': True,
            'message': f'Email envoye a {email_record.sender_email}'
        })
    else:
        return jsonify({
            'success': False,
            'message': 'Erreur lors de l\'envoi'
        }), 500


@app.route('/api/parcelpanel/status', methods=['GET'])
def parcelpanel_status():
    """Verifie la configuration Parcelpanel pour tous les shops"""
    parcelpanel_manager = get_parcelpanel_manager()

    configured_shops = parcelpanel_manager.get_all_configured_shops()

    # Liste des 7 shops attendus
    expected_shops = [
        'tgir1c-x2',  # FR
        'qk16wv-2e',  # NL
        'jl1brs-gp',  # ES
        'pz5e9e-2e',  # IT
        'u06wln-hf',  # DE
        'xptmak-r7',  # PL
        'fyh99s-h9'   # EN
    ]

    shop_status = {}
    for shop in expected_shops:
        shop_status[shop] = {
            'configured': shop in configured_shops,
            'handler': parcelpanel_manager.get_handler(shop) is not None
        }

    missing_shops = [s for s in expected_shops if s not in configured_shops]

    return jsonify({
        'success': len(missing_shops) == 0,
        'configured_count': len(configured_shops),
        'expected_count': len(expected_shops),
        'configured_shops': configured_shops,
        'missing_shops': missing_shops,
        'shop_status': shop_status,
        'message': f'{len(configured_shops)}/{len(expected_shops)} shops Parcelpanel configures'
    })


@app.route('/api/parcelpanel/test/<shop_name>', methods=['POST'])
def test_parcelpanel_shop(shop_name):
    """Teste la connexion Parcelpanel pour un shop specifique"""
    parcelpanel_manager = get_parcelpanel_manager()
    handler = parcelpanel_manager.get_handler(shop_name)

    if not handler:
        return jsonify({
            'success': False,
            'message': f'Shop {shop_name} non configure pour Parcelpanel'
        })

    # Test avec un appel API simple
    result = test_parcelpanel_connection(handler.api_key)
    result['shop'] = shop_name

    return jsonify(result)


@app.route('/api/stats', methods=['GET'])
def get_stats():
    """RÃ©cupÃ¨re les statistiques"""
    total = Email.query.count()
    pending = Email.query.filter_by(status='pending').count()
    sent = Email.query.filter_by(status='sent').count()
    auto_sent = Email.query.filter_by(auto_sent=True).count()
    ignored = Email.query.filter_by(status='ignored').count()

    # Stats par catÃ©gorie
    categories = db.session.query(
        Email.category, db.func.count(Email.id)
    ).group_by(Email.category).all()

    return jsonify({
        'success': True,
        'stats': {
            'total': total,
            'pending': pending,
            'sent': sent,
            'auto_sent': auto_sent,
            'ignored': ignored,
            'categories': {cat: count for cat, count in categories if cat}
        }
    })


@app.route('/api/test-connections', methods=['POST'])
def test_connections():
    """Teste toutes les connexions (Zoho, Shopify, Claude)"""
    results = {}

    # Test Zoho
    if app.config.get('ZOHO_EMAIL') and app.config.get('ZOHO_PASSWORD'):
        results['zoho'] = test_zoho_connection(
            app.config['ZOHO_EMAIL'],
            app.config['ZOHO_PASSWORD'],
            app.config.get('ZOHO_IMAP_SERVER', 'imap.zoho.eu')
        )
    else:
        results['zoho'] = {'success': False, 'message': 'Non configurÃ©'}

    # Test Shopify (OAuth ou legacy)
    storage = get_token_storage_instance()
    shops = storage.get_all_shops()

    if shops:
        # Test avec le premier shop connectÃ© via OAuth
        shop_name = list(shops.keys())[0]
        access_token = storage.get_token(shop_name)
        results['shopify'] = test_shopify_connection(shop_name, access_token)
        results['shopify']['connected_shops'] = len(shops)
    elif app.config.get('SHOPIFY_SHOP_NAME') and app.config.get('SHOPIFY_ACCESS_TOKEN'):
        # Fallback: token legacy
        results['shopify'] = test_shopify_connection(
            app.config['SHOPIFY_SHOP_NAME'],
            app.config['SHOPIFY_ACCESS_TOKEN']
        )
    else:
        results['shopify'] = {'success': False, 'message': 'Aucun shop connectÃ©'}

    # Test Claude
    if app.config.get('ANTHROPIC_API_KEY'):
        results['claude'] = test_ai_connection(app.config['ANTHROPIC_API_KEY'])
    else:
        results['claude'] = {'success': False, 'message': 'Non configurÃ©'}

    all_ok = all(r.get('success') for r in results.values())

    return jsonify({
        'success': all_ok,
        'results': results
    })


# ============================================
# BACKGROUND TASK - Email Checker
# ============================================

def background_email_checker():
    """VÃ©rifie les emails en arriÃ¨re-plan"""
    while True:
        interval = app.config.get('EMAIL_CHECK_INTERVAL', 300)
        time.sleep(interval)

        with app.app_context():
            try:
                logger.info("VÃ©rification automatique des emails...")
                # Simule l'appel API
                # En production, on appellerait directement la logique
            except Exception as e:
                logger.error(f"Erreur background checker: {e}")


# ============================================
# MAIN
# ============================================

if __name__ == '__main__':
    # DÃ©marre le checker en background (optionnel)
    # checker_thread = threading.Thread(target=background_email_checker, daemon=True)
    # checker_thread.start()

    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
