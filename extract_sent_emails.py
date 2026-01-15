#!/usr/bin/env python3
"""
Script pour extraire les emails envoyés (réponses SAV) vers un fichier JSON
Ces données serviront à entraîner l'IA pour répondre dans le même style
"""
import json
import os
import re
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

from modules.email_handler import ZohoEmailHandler

def extract_sent_emails(output_file: str = "sent_emails_training.json", limit: int = 500):
    """Extrait les emails envoyés vers un fichier JSON pour l'apprentissage"""

    email = os.getenv('ZOHO_EMAIL')
    password = os.getenv('ZOHO_PASSWORD')

    if not email or not password:
        print("Erreur: ZOHO_EMAIL et ZOHO_PASSWORD doivent être définis")
        return

    handler = ZohoEmailHandler(email, password)

    print("Connexion à Zoho Mail...")
    if not handler.connect_imap():
        print("Erreur de connexion")
        return

    # Dossiers possibles pour les emails envoyés
    sent_folders = ["Sent", "Envoyé", "Envoyés", "Sent Items", "Sent Mail"]

    sent_emails = []

    for folder in sent_folders:
        print(f"Tentative avec le dossier: {folder}")
        handler.disconnect_imap()
        handler.connect_imap()

        emails = handler.fetch_unread_emails(folder=folder, limit=limit)
        if emails:
            print(f"Trouvé {len(emails)} emails dans {folder}")
            sent_emails.extend(emails)
            break

    if not sent_emails:
        print("Aucun email envoyé trouvé")
        handler.disconnect_imap()
        return

    # Analyse et structure les données
    training_data = []

    # Patterns pour catégoriser les réponses
    categories = {
        'SUIVI': [
            r'suivi', r'livraison', r'colis', r'expédi', r'tracking',
            r'où en est', r'quand.*recev', r'délai', r'transporteur',
            r'colissimo', r'chronopost', r'mondial relay', r'la poste'
        ],
        'RETOUR': [
            r'retour', r'rembours', r'échang', r'renvoy', r'renvoie',
            r'reprendre', r'récupér'
        ],
        'PROBLEME': [
            r'problème', r'défectueu', r'cassé', r'abîmé', r'erreur',
            r'manqu', r'incomplet', r'mauvais', r'endommagé'
        ],
        'QUESTION': [
            r'question', r'renseign', r'information', r'savoir',
            r'comment', r'pourquoi', r'est-ce que'
        ],
        'MODIFICATION': [
            r'modifi', r'chang', r'annul', r'adresse', r'commande'
        ]
    }

    for email_data in sent_emails:
        subject = email_data.get('subject', '') or ''
        body = email_data.get('body', '') or ''
        recipient = email_data.get('sender_email', '')  # Dans les envoyés, c'est le destinataire

        # Ignore les emails vides
        if not body.strip():
            continue

        # Détermine la catégorie basée sur le contenu
        detected_category = 'AUTRE'
        subject_body = (subject + ' ' + body).lower()

        for cat, patterns in categories.items():
            for pattern in patterns:
                if re.search(pattern, subject_body, re.IGNORECASE):
                    detected_category = cat
                    break
            if detected_category != 'AUTRE':
                break

        # Extrait le numéro de commande si présent
        order_match = re.search(r'#?(\d{4,6})', subject + ' ' + body)
        order_number = order_match.group(1) if order_match else None

        # Détecte si c'est une réponse automatique ou manuelle
        is_template_response = any(phrase in body.lower() for phrase in [
            'bonjour,', 'cordialement', 'à bientôt', 'avena paris',
            'merci pour votre', 'nous avons bien reçu'
        ])

        training_entry = {
            'date': email_data.get('received_at').isoformat() if email_data.get('received_at') else None,
            'recipient': recipient,
            'subject': subject,
            'body': body,
            'category': detected_category,
            'order_number': order_number,
            'word_count': len(body.split()),
            'is_template': is_template_response
        }

        training_data.append(training_entry)

    # Statistiques
    stats = {
        'total_emails': len(training_data),
        'by_category': {},
        'avg_word_count': 0,
        'templates_count': 0
    }

    for entry in training_data:
        cat = entry['category']
        stats['by_category'][cat] = stats['by_category'].get(cat, 0) + 1
        stats['avg_word_count'] += entry['word_count']
        if entry['is_template']:
            stats['templates_count'] += 1

    if training_data:
        stats['avg_word_count'] = round(stats['avg_word_count'] / len(training_data))

    # Sauvegarde
    output = {
        'extracted_at': datetime.now().isoformat(),
        'stats': stats,
        'emails': training_data
    }

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    handler.disconnect_imap()

    print(f"\n✓ Export terminé: {output_file}")
    print(f"  Total: {stats['total_emails']} emails exportés")
    print(f"  Par catégorie: {stats['by_category']}")
    print(f"  Moyenne mots/email: {stats['avg_word_count']}")
    print(f"  Templates détectés: {stats['templates_count']}")

if __name__ == "__main__":
    extract_sent_emails(limit=600)
