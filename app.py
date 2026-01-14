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
from models import db, Email
from modules.email_handler import ZohoEmailHandler, test_zoho_connection
from modules.shopify_handler import ShopifyHandler, test_shopify_connection
from modules.ai_responder import AIResponder, test_ai_connection
from modules.shopify_oauth import ShopifyOAuth, ShopifyTokenStorage, get_oauth_handler, get_token_storage

# Configuration logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def create_app():
    """Factory pour créer l'application Flask"""
    app = Flask(__name__)

    # Chargement config
    config = get_config()
    app.config.from_object(config)

    # Support pour les proxys (Railway, Heroku, etc.)
    # Permet à Flask de détecter correctement HTTPS derrière un reverse proxy
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

    # Force HTTPS pour les URLs générées (important pour OAuth)
    app.config['PREFERRED_URL_SCHEME'] = 'https'

    # Init database
    db.init_app(app)

    with app.app_context():
        db.create_all()

    return app


app = create_app()

# Handlers globaux (initialisés au premier besoin)
email_handler = None
shopify_handlers = {}  # Dict de handlers par shop
ai_responder = None
token_storage = None


def get_token_storage_instance():
    """Lazy loading du storage de tokens"""
    global token_storage
    if token_storage is None:
        token_storage = get_token_storage()
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
    Lazy loading du handler Shopify pour un shop spécifique

    Args:
        shop_name: Nom du shop (ex: avena-paris). Si None, utilise le shop par défaut.

    Returns:
        ShopifyHandler ou None si aucun token disponible
    """
    global shopify_handlers

    # Si pas de shop spécifié, essaie le shop par défaut
    if shop_name is None:
        shop_name = app.config.get('SHOPIFY_SHOP_NAME')

    if not shop_name:
        # Essaie de prendre le premier shop connecté
        storage = get_token_storage_instance()
        shops = storage.get_all_shops()
        if shops:
            shop_name = list(shops.keys())[0]
        else:
            logger.warning("Aucun shop Shopify configuré")
            return None

    # Vérifie si on a déjà un handler pour ce shop
    if shop_name in shopify_handlers:
        return shopify_handlers[shop_name]

    # Récupère le token
    storage = get_token_storage_instance()
    access_token = storage.get_token(shop_name)

    # Si pas de token OAuth, essaie le token legacy
    if not access_token and shop_name == app.config.get('SHOPIFY_SHOP_NAME'):
        access_token = app.config.get('SHOPIFY_ACCESS_TOKEN')

    if not access_token:
        logger.warning(f"Pas de token disponible pour {shop_name}")
        return None

    # Crée le handler
    handler = ShopifyHandler(
        shop_name=shop_name,
        access_token=access_token
    )

    shopify_handlers[shop_name] = handler
    return handler


def get_all_shopify_handlers():
    """Retourne les handlers pour tous les shops connectés"""
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
    """Page de gestion des stores Shopify connectés"""
    storage = get_token_storage_instance()
    connected_shops = storage.get_all_shops()
    return render_template('stores.html', shops=connected_shops)


# ============================================
# ROUTES - SHOPIFY OAUTH
# ============================================

@app.route('/shopify/install')
def shopify_install():
    """
    Lance l'installation OAuth pour un shop Shopify
    Paramètre: ?shop=nom-du-shop (sans .myshopify.com)
    """
    shop = request.args.get('shop')

    if not shop:
        return render_template('shopify_install.html')

    # Vérifie que les credentials OAuth sont configurés
    if not app.config.get('SHOPIFY_CLIENT_ID') or not app.config.get('SHOPIFY_CLIENT_SECRET'):
        return jsonify({
            'success': False,
            'message': 'SHOPIFY_CLIENT_ID et SHOPIFY_CLIENT_SECRET non configurés'
        }), 500

    try:
        oauth = get_oauth_handler()

        # Génère une clé state pour la sécurité CSRF
        import secrets
        state = secrets.token_urlsafe(32)

        # Stocke le state en session
        from flask import session
        session['shopify_oauth_state'] = state
        session['shopify_oauth_shop'] = shop

        # Construit l'URL de redirection
        redirect_uri = url_for('shopify_callback', _external=True)

        # Génère l'URL d'installation
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
    Callback OAuth après autorisation Shopify
    Reçoit le code d'autorisation et l'échange contre un access token
    """
    # Récupère les paramètres
    code = request.args.get('code')
    shop = request.args.get('shop')
    state = request.args.get('state')
    hmac_param = request.args.get('hmac')

    if not code or not shop:
        return render_template('oauth_error.html',
                               error="Paramètres manquants dans le callback OAuth")

    # Vérifie le state (protection CSRF)
    from flask import session
    expected_state = session.get('shopify_oauth_state')
    if state and expected_state and state != expected_state:
        return render_template('oauth_error.html',
                               error="State invalide - possible attaque CSRF")

    try:
        oauth = get_oauth_handler()

        # Échange le code contre un token
        access_token, error = oauth.exchange_code_for_token(shop, code)

        if error:
            return render_template('oauth_error.html', error=error)

        if not access_token:
            return render_template('oauth_error.html',
                                   error="Impossible d'obtenir l'access token")

        # Récupère les infos du shop
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

        logger.info(f"Shop {shop} connecté avec succès")

        return render_template('oauth_success.html',
                               shop=shop,
                               shop_info=shop_info)

    except Exception as e:
        logger.error(f"Erreur callback OAuth: {e}")
        return render_template('oauth_error.html', error=str(e))


@app.route('/shopify/disconnect/<shop_name>')
def shopify_disconnect(shop_name):
    """Déconnecte un shop Shopify"""
    storage = get_token_storage_instance()
    storage.remove_token(shop_name)

    # Invalide le cache du handler
    if shop_name in shopify_handlers:
        del shopify_handlers[shop_name]

    logger.info(f"Shop {shop_name} déconnecté")

    return redirect(url_for('stores'))


@app.route('/api/shops', methods=['GET'])
def api_get_shops():
    """API: Liste des shops connectés"""
    storage = get_token_storage_instance()
    shops = storage.get_all_shops()

    # Retire les tokens de la réponse pour la sécurité
    safe_shops = {}
    for shop_name, data in shops.items():
        safe_shops[shop_name] = {
            'shop_domain': data.get('shop_domain'),
            'shop_info': data.get('shop_info'),
            'created_at': data.get('created_at')
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
    """Récupère la liste des emails"""
    status = request.args.get('status', 'pending')

    query = Email.query

    if status != 'all':
        query = query.filter_by(status=status)

    emails = query.order_by(Email.received_at.desc()).limit(50).all()

    return jsonify({
        'success': True,
        'emails': [e.to_dict() for e in emails],
        'count': len(emails)
    })


@app.route('/api/emails/<int:email_id>', methods=['GET'])
def get_email(email_id):
    """Récupère un email spécifique"""
    email = Email.query.get_or_404(email_id)
    return jsonify({
        'success': True,
        'email': email.to_dict()
    })


@app.route('/api/emails/<int:email_id>/approve', methods=['POST'])
def approve_email(email_id):
    """Approuve et envoie une réponse"""
    email_record = Email.query.get_or_404(email_id)

    # Récupère la réponse (modifiée ou originale)
    data = request.get_json() or {}
    response_text = data.get('response', email_record.generated_response)

    # Vérifie si la réponse a été modifiée
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
            'message': f'Email envoyé à {email_record.sender_email}'
        })
    else:
        return jsonify({
            'success': False,
            'message': 'Erreur lors de l\'envoi'
        }), 500


@app.route('/api/emails/<int:email_id>/ignore', methods=['POST'])
def ignore_email(email_id):
    """Ignore un email (ne pas répondre)"""
    email_record = Email.query.get_or_404(email_id)
    email_record.status = 'ignored'
    email_record.processed_at = datetime.utcnow()
    db.session.commit()

    return jsonify({
        'success': True,
        'message': 'Email marqué comme ignoré'
    })


@app.route('/api/emails/<int:email_id>/regenerate', methods=['POST'])
def regenerate_response(email_id):
    """Régénère la réponse IA"""
    email_record = Email.query.get_or_404(email_id)

    # Récupère le contexte Shopify
    shopify = get_shopify_handler()
    order_context = shopify.get_order_context(
        order_number=email_record.order_number,
        email=email_record.sender_email
    )

    # Régénère la réponse
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
    """Récupère les nouveaux emails depuis Zoho"""
    try:
        handler = get_email_handler()
        shopify = get_shopify_handler()
        ai = get_ai_responder()

        # Récupère les emails non lus
        new_emails = handler.fetch_unread_emails()

        processed = 0
        auto_sent = 0

        for email_data in new_emails:
            # Vérifie si déjà traité
            existing = Email.query.filter_by(message_id=email_data['message_id']).first()
            if existing:
                continue

            # Classifie l'email
            category, confidence = ai.classify_email(
                subject=email_data['subject'],
                body=email_data['body']
            )

            # Récupère le contexte Shopify
            order_context = shopify.get_order_context(
                order_number=email_data.get('order_number'),
                email=email_data['sender_email']
            )

            # Met à jour le numéro de commande si trouvé via Shopify
            if not email_data.get('order_number') and order_context.get('order'):
                email_data['order_number'] = order_context['order'].get('order_number')

            # Génère la réponse
            response = ai.generate_response(
                email_data=email_data,
                order_context=order_context,
                category=category
            )

            # Crée l'enregistrement
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
                generated_response=response,
                status='pending'
            )

            # Vérifie si envoi automatique possible
            auto_rules = {
                'auto_send_tracking': app.config.get('AUTO_SEND_TRACKING', False),
                'auto_send_return': app.config.get('AUTO_SEND_RETURN_CONFIRM', False)
            }

            can_auto, reason = ai.should_auto_send(
                category=category,
                confidence=confidence,
                order_context=order_context,
                auto_rules=auto_rules
            )

            if can_auto:
                # Envoie automatiquement
                subject = f"Re: {email_data['subject']}"
                if handler.send_email(
                    to_email=email_data['sender_email'],
                    subject=subject,
                    body=response
                ):
                    email_record.status = 'sent'
                    email_record.auto_sent = True
                    email_record.sent_at = datetime.utcnow()
                    auto_sent += 1
                    logger.info(f"Email auto-envoyé à {email_data['sender_email']}")

            db.session.add(email_record)
            processed += 1

        db.session.commit()
        handler.disconnect_imap()

        return jsonify({
            'success': True,
            'message': f'{processed} emails traités, {auto_sent} envoyés automatiquement',
            'processed': processed,
            'auto_sent': auto_sent
        })

    except Exception as e:
        logger.error(f"Erreur fetch emails: {e}")
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500


@app.route('/api/stats', methods=['GET'])
def get_stats():
    """Récupère les statistiques"""
    total = Email.query.count()
    pending = Email.query.filter_by(status='pending').count()
    sent = Email.query.filter_by(status='sent').count()
    auto_sent = Email.query.filter_by(auto_sent=True).count()
    ignored = Email.query.filter_by(status='ignored').count()

    # Stats par catégorie
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
        results['zoho'] = {'success': False, 'message': 'Non configuré'}

    # Test Shopify (OAuth ou legacy)
    storage = get_token_storage_instance()
    shops = storage.get_all_shops()

    if shops:
        # Test avec le premier shop connecté via OAuth
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
        results['shopify'] = {'success': False, 'message': 'Aucun shop connecté'}

    # Test Claude
    if app.config.get('ANTHROPIC_API_KEY'):
        results['claude'] = test_ai_connection(app.config['ANTHROPIC_API_KEY'])
    else:
        results['claude'] = {'success': False, 'message': 'Non configuré'}

    all_ok = all(r.get('success') for r in results.values())

    return jsonify({
        'success': all_ok,
        'results': results
    })


# ============================================
# BACKGROUND TASK - Email Checker
# ============================================

def background_email_checker():
    """Vérifie les emails en arrière-plan"""
    while True:
        interval = app.config.get('EMAIL_CHECK_INTERVAL', 300)
        time.sleep(interval)

        with app.app_context():
            try:
                logger.info("Vérification automatique des emails...")
                # Simule l'appel API
                # En production, on appellerait directement la logique
            except Exception as e:
                logger.error(f"Erreur background checker: {e}")


# ============================================
# MAIN
# ============================================

if __name__ == '__main__':
    # Démarre le checker en background (optionnel)
    # checker_thread = threading.Thread(target=background_email_checker, daemon=True)
    # checker_thread.start()

    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
