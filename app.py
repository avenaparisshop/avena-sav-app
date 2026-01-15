"""
Application principale Flask - Avena SAV
Dashboard de gestion des emails SAV avec IA
"""
import os
from flask import Flask, render_template, request, jsonify, redirect, url_for
from datetime import datetime
import threading
import time
import logging
from werkzeug.middleware.proxy_fix import ProxyFix

from config import get_config
from models import db, Email, ShopifyToken
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

    return jsonify({
        'success': True,
        'emails': [e.to_dict() for e in emails],
        'count': len(emails)
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
    """RÃ©cupÃ¨re les nouveaux emails depuis Zoho - SANS traitement IA"""
    try:
        handler = get_email_handler()

        # Récupère les emails de TOUS les dossiers importants
        # INBOX, Archive, Newsletter, Notification (pas Spam/Courrier indésirable)
        # Limite à 500 emails par dossier pour éviter les timeouts IMAP
        new_emails = handler.fetch_emails_from_folders(
            folders=["INBOX", "Archive", "Archiver", "Newsletter", "Notification"],
            limit_per_folder=500
        )

        processed = 0

        for email_data in new_emails:
            # VÃ©rifie si dÃ©jÃ  en base
            existing = Email.query.filter_by(message_id=email_data['message_id']).first()
            if existing:
                continue

            # CrÃ©e l'enregistrement SANS traitement IA
            email_record = Email(
                message_id=email_data['message_id'],
                sender_email=email_data['sender_email'],
                sender_name=email_data.get('sender_name'),
                subject=email_data['subject'],
                body=email_data['body'],
                received_at=email_data.get('received_at'),
                category=None,  # Pas de classification automatique
                confidence=None,
                order_number=email_data.get('order_number'),
                generated_response=None,  # Pas de rÃ©ponse gÃ©nÃ©rÃ©e
                status='pending'
            )

            db.session.add(email_record)
            processed += 1

        db.session.commit()
        handler.disconnect_imap()

        return jsonify({
            'success': True,
            'message': f'{processed} nouveaux emails rÃ©cupÃ©rÃ©s',
            'processed': processed
        })

    except Exception as e:
        logger.error(f"Erreur fetch emails: {e}")
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
