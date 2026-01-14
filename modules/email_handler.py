"""
Module de gestion des emails via Zoho Mail (IMAP/SMTP)
"""
import imaplib
import smtplib
import email
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import decode_header
from datetime import datetime
import re
from typing import List, Dict, Optional
import logging

logger = logging.getLogger(__name__)


class ZohoEmailHandler:
    """Gestionnaire d'emails Zoho via IMAP/SMTP"""

    def __init__(self, email_address: str, password: str,
                 imap_server: str = "imap.zoho.eu",
                 smtp_server: str = "smtp.zoho.eu"):
        self.email_address = email_address
        self.password = password
        self.imap_server = imap_server
        self.smtp_server = smtp_server
        self.imap_connection = None
        self.smtp_connection = None

    def connect_imap(self) -> bool:
        """Connexion au serveur IMAP Zoho"""
        try:
            self.imap_connection = imaplib.IMAP4_SSL(self.imap_server, 993)
            self.imap_connection.login(self.email_address, self.password)
            logger.info(f"Connecté à {self.imap_server} avec succès")
            return True
        except Exception as e:
            logger.error(f"Erreur connexion IMAP: {e}")
            return False

    def disconnect_imap(self):
        """Déconnexion IMAP"""
        if self.imap_connection:
            try:
                self.imap_connection.logout()
            except:
                pass
            self.imap_connection = None

    def _decode_header_value(self, value: str) -> str:
        """Décode une valeur d'en-tête email"""
        if not value:
            return ""

        decoded_parts = decode_header(value)
        result = []
        for part, encoding in decoded_parts:
            if isinstance(part, bytes):
                try:
                    result.append(part.decode(encoding or 'utf-8', errors='replace'))
                except:
                    result.append(part.decode('utf-8', errors='replace'))
            else:
                result.append(part)
        return ''.join(result)

    def _extract_email_body(self, msg) -> str:
        """Extrait le corps de l'email (préfère le texte brut)"""
        body = ""

        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition"))

                # Ignore les pièces jointes
                if "attachment" in content_disposition:
                    continue

                if content_type == "text/plain":
                    try:
                        payload = part.get_payload(decode=True)
                        charset = part.get_content_charset() or 'utf-8'
                        body = payload.decode(charset, errors='replace')
                        break  # Préfère le texte brut
                    except:
                        pass
                elif content_type == "text/html" and not body:
                    try:
                        payload = part.get_payload(decode=True)
                        charset = part.get_content_charset() or 'utf-8'
                        body = payload.decode(charset, errors='replace')
                        # Nettoie le HTML basique
                        body = re.sub(r'<[^>]+>', ' ', body)
                        body = re.sub(r'\s+', ' ', body).strip()
                    except:
                        pass
        else:
            try:
                payload = msg.get_payload(decode=True)
                charset = msg.get_content_charset() or 'utf-8'
                body = payload.decode(charset, errors='replace')
            except:
                pass

        return body.strip()

    def _parse_sender(self, from_header: str) -> Dict[str, str]:
        """Parse l'en-tête From pour extraire nom et email"""
        from_decoded = self._decode_header_value(from_header)

        # Pattern: "Nom <email@domain.com>" ou juste "email@domain.com"
        match = re.match(r'^(.+?)\s*<(.+?)>$', from_decoded)
        if match:
            return {
                'name': match.group(1).strip().strip('"'),
                'email': match.group(2).strip()
            }

        # Juste l'email
        email_match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', from_decoded)
        if email_match:
            return {
                'name': '',
                'email': email_match.group(0)
            }

        return {'name': '', 'email': from_decoded}

    def fetch_unread_emails(self, folder: str = "INBOX", limit: int = 50) -> List[Dict]:
        """Récupère les emails non lus"""
        emails = []

        if not self.imap_connection:
            if not self.connect_imap():
                return emails

        try:
            self.imap_connection.select(folder)

            # Recherche des emails non lus
            status, messages = self.imap_connection.search(None, 'ALL')

            if status != 'OK':
                logger.error("Erreur lors de la recherche des emails")
                return emails

            email_ids = messages[0].split()

            # Limite le nombre d'emails à traiter
            email_ids = email_ids[-limit:] if len(email_ids) > limit else email_ids

            for email_id in email_ids:
                try:
                    # Récupère l'email complet
                    status, msg_data = self.imap_connection.fetch(email_id, '(RFC822)')

                    if status != 'OK':
                        continue

                    raw_email = msg_data[0][1]
                    msg = email.message_from_bytes(raw_email)

                    # Parse les infos
                    sender_info = self._parse_sender(msg.get('From', ''))
                    subject = self._decode_header_value(msg.get('Subject', ''))
                    body = self._extract_email_body(msg)
                    message_id = msg.get('Message-ID', '')

                    # Date de réception
                    date_str = msg.get('Date', '')
                    try:
                        received_at = email.utils.parsedate_to_datetime(date_str)
                    except:
                        received_at = datetime.utcnow()

                    # Cherche un numéro de commande dans le sujet ou le corps
                    order_number = self._extract_order_number(subject + ' ' + body)

                    emails.append({
                        'message_id': message_id,
                        'sender_email': sender_info['email'],
                        'sender_name': sender_info['name'],
                        'subject': subject,
                        'body': body,
                        'received_at': received_at,
                        'order_number': order_number,
                        'imap_id': email_id.decode() if isinstance(email_id, bytes) else email_id
                    })

                except Exception as e:
                    logger.error(f"Erreur parsing email {email_id}: {e}")
                    continue

            logger.info(f"Récupéré {len(emails)} emails non lus")
            return emails

        except Exception as e:
            logger.error(f"Erreur fetch emails: {e}")
            return emails

    def _extract_order_number(self, text: str) -> Optional[str]:
        """Extrait un numéro de commande du texte"""
        # Patterns courants pour les numéros de commande
        patterns = [
            r'#(\d{4,})',  # #12345
            r'commande\s*[:#]?\s*(\d{4,})',  # commande 12345
            r'order\s*[:#]?\s*(\d{4,})',  # order 12345
            r'n[°o]?\s*(\d{4,})',  # n°12345 ou no12345
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1)

        return None

    def mark_as_read(self, imap_id: str):
        """Marque un email comme lu"""
        if self.imap_connection:
            try:
                self.imap_connection.store(imap_id.encode(), '+FLAGS', '\\Seen')
            except Exception as e:
                logger.error(f"Erreur mark as read: {e}")

    def send_email(self, to_email: str, subject: str, body: str,
                   reply_to_message_id: Optional[str] = None) -> bool:
        """Envoie un email via SMTP Zoho"""
        try:
            # Connexion SMTP
            smtp = smtplib.SMTP_SSL(self.smtp_server, 465)
            smtp.login(self.email_address, self.password)

            # Création du message
            msg = MIMEMultipart()
            msg['From'] = self.email_address
            msg['To'] = to_email
            msg['Subject'] = subject

            # Headers pour le threading
            if reply_to_message_id:
                msg['In-Reply-To'] = reply_to_message_id
                msg['References'] = reply_to_message_id

            msg.attach(MIMEText(body, 'plain', 'utf-8'))

            # Envoi
            smtp.send_message(msg)
            smtp.quit()

            logger.info(f"Email envoyé à {to_email}")
            return True

        except Exception as e:
            logger.error(f"Erreur envoi email: {e}")
            return False


# Fonction utilitaire pour tester la connexion
def test_zoho_connection(email_address: str, password: str,
                          imap_server: str = "imap.zoho.eu") -> Dict:
    """Teste la connexion Zoho et retourne le résultat"""
    handler = ZohoEmailHandler(email_address, password, imap_server)

    result = {
        'success': False,
        'message': '',
        'email_count': 0
    }

    try:
        if handler.connect_imap():
            # Compte les emails non lus
            handler.imap_connection.select('INBOX')
            status, messages = handler.imap_connection.search(None, 'UNSEEN')

            if status == 'OK':
                email_count = len(messages[0].split()) if messages[0] else 0
                result['success'] = True
                result['message'] = f"Connexion réussie ! {email_count} emails non lus."
                result['email_count'] = email_count
            else:
                result['message'] = "Connexion OK mais erreur lecture INBOX"

            handler.disconnect_imap()
        else:
            result['message'] = "Échec de connexion - vérifiez vos identifiants"

    except Exception as e:
        result['message'] = f"Erreur: {str(e)}"

    return result
