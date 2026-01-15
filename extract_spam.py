#!/usr/bin/env python3
"""
Script pour extraire les emails spam/indésirables vers CSV
"""
import csv
import os
from datetime import datetime
from dotenv import load_dotenv

# Charge les variables d'environnement
load_dotenv()

from modules.email_handler import ZohoEmailHandler

def extract_spam_to_csv(output_file: str = "spam_emails.csv", limit: int = None):
    """Extrait les emails du dossier Courrier indésirable vers un CSV"""

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

    # Liste les dossiers pour trouver le bon nom
    print("Recherche du dossier spam...")
    folders = handler.list_folders()
    print(f"Dossiers disponibles: {folders}")

    # Essaie plusieurs noms possibles pour le dossier spam
    spam_folders = ["Courrier indésirable", "Spam", "Junk", "Bulk"]

    spam_emails = []

    for spam_folder in spam_folders:
        print(f"Tentative avec le dossier: {spam_folder}")
        handler.disconnect_imap()
        handler.connect_imap()

        emails = handler.fetch_unread_emails(folder=spam_folder, limit=limit)
        if emails:
            print(f"Trouvé {len(emails)} emails dans {spam_folder}")
            spam_emails.extend(emails)
            break

    if not spam_emails:
        print("Aucun email trouvé dans les dossiers spam")
        handler.disconnect_imap()
        return

    # Écriture du CSV
    print(f"Écriture de {len(spam_emails)} emails vers {output_file}...")

    with open(output_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)

        # En-têtes
        writer.writerow([
            'Date',
            'Expéditeur Email',
            'Expéditeur Nom',
            'Sujet',
            'Aperçu du contenu (100 chars)'
        ])

        for email_data in spam_emails:
            # Aperçu du contenu (premiers 100 caractères)
            body_preview = email_data.get('body', '')[:100].replace('\n', ' ').replace('\r', '')

            # Format date
            received_at = email_data.get('received_at')
            if received_at:
                date_str = received_at.strftime('%Y-%m-%d %H:%M') if isinstance(received_at, datetime) else str(received_at)
            else:
                date_str = ''

            writer.writerow([
                date_str,
                email_data.get('sender_email', ''),
                email_data.get('sender_name', ''),
                email_data.get('subject', ''),
                body_preview
            ])

    handler.disconnect_imap()
    print(f"✓ Export terminé: {output_file}")
    print(f"  Total: {len(spam_emails)} emails exportés")

if __name__ == "__main__":
    extract_spam_to_csv(limit=600)  # Limite pour éviter timeout
