"""
Modèles de base de données pour Avena SAV
"""
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class Email(db.Model):
    """Modèle pour stocker les emails SAV"""
    __tablename__ = 'emails'

    id = db.Column(db.Integer, primary_key=True)
    message_id = db.Column(db.String(255), unique=True, nullable=False)

    # Infos email
    sender_email = db.Column(db.String(255), nullable=False)
    sender_name = db.Column(db.String(255))
    subject = db.Column(db.String(500))
    body = db.Column(db.Text)
    received_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Classification IA
    category = db.Column(db.String(50))  # SUIVI, RETOUR, PROBLEME, QUESTION, AUTRE
    confidence = db.Column(db.Float)  # Score de confiance 0-1

    # Lien Shopify
    order_number = db.Column(db.String(50))
    customer_id = db.Column(db.String(50))

    # Réponse générée
    generated_response = db.Column(db.Text)

    # Statut
    status = db.Column(db.String(20), default='pending')  # pending, approved, sent, ignored
    processed_at = db.Column(db.DateTime)
    sent_at = db.Column(db.DateTime)

    # Métadonnées
    auto_sent = db.Column(db.Boolean, default=False)
    modified_before_send = db.Column(db.Boolean, default=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        """Convertit en dictionnaire pour l'API"""
        return {
            'id': self.id,
            'message_id': self.message_id,
            'sender_email': self.sender_email,
            'sender_name': self.sender_name,
            'subject': self.subject,
            'body': self.body,
            'received_at': self.received_at.isoformat() if self.received_at else None,
            'category': self.category,
            'confidence': self.confidence,
            'order_number': self.order_number,
            'generated_response': self.generated_response,
            'status': self.status,
            'auto_sent': self.auto_sent,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class ResponseTemplate(db.Model):
    """Templates de réponses personnalisables"""
    __tablename__ = 'response_templates'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    category = db.Column(db.String(50), nullable=False)
    template = db.Column(db.Text, nullable=False)
    is_active = db.Column(db.Boolean, default=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Settings(db.Model):
    """Paramètres de l'application"""
    __tablename__ = 'settings'

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False)
    value = db.Column(db.Text)
    description = db.Column(db.String(255))

    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
