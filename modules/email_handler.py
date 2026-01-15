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

    def _clean_html_to_text(self, html: str) -> str:
        """Convertit le HTML en texte propre"""
        if not html:
            return ""

        # Supprime les balises style et script avec leur contenu
        html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)

        # Supprime les commentaires HTML
        html = re.sub(r'<!--.*?-->', '', html, flags=re.DOTALL)

        # Supprime le DOCTYPE et les balises meta/head
        html = re.sub(r'<!DOCTYPE[^>]*>', '', html, flags=re.IGNORECASE)
        html = re.sub(r'<head[^>]*>.*?</head>', '', html, flags=re.DOTALL | re.IGNORECASE)

        # Remplace les balises de saut de ligne par des retours à la ligne
        html = re.sub(r'<br\s*/?>', '\n', html, flags=re.IGNORECASE)
        html = re.sub(r'</p>', '\n', html, flags=re.IGNORECASE)
        html = re.sub(r'</div>', '\n', html, flags=re.IGNORECASE)
        html = re.sub(r'</tr>', '\n', html, flags=re.IGNORECASE)
        html = re.sub(r'</li>', '\n', html, flags=re.IGNORECASE)

        # Supprime toutes les autres balises HTML
        html = re.sub(r'<[^>]+>', ' ', html)

        # Décode les entités HTML courantes
        html = html.replace('&nbsp;', ' ')
        html = html.replace('&amp;', '&')
        html = html.replace('&lt;', '<')
        html = html.replace('&gt;', '>')
        html = html.replace('&quot;', '"')
        html = html.replace('&#39;', "'")
        html = html.replace('&apos;', "'")
        html = re.sub(r'&#(\d+);', lambda m: chr(int(m.group(1))), html)

        # Nettoie les espaces multiples mais garde les retours à la ligne
        html = re.sub(r'[ \t]+', ' ', html)
        html = re.sub(r'\n\s*\n', '\n\n', html)
        html = re.sub(r'\n{3,}', '\n\n', html)

        return html.strip()

    def _extract_email_body(self, msg) -> str:
        """Extrait le corps de l'email (préfère le texte brut)"""
        body = ""
        html_body = ""

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
                elif content_type == "text/html" and not html_body:
                    try:
                        payload = part.get_payload(decode=True)
                        charset = part.get_content_charset() or 'utf-8'
                        html_body = payload.decode(charset, errors='replace')
                    except:
                        pass
        else:
            try:
                payload = msg.get_payload(decode=True)
                charset = msg.get_content_charset() or 'utf-8'
                content = payload.decode(charset, errors='replace')
                content_type = msg.get_content_type()

                if content_type == "text/html":
                    html_body = content
                else:
                    body = content
            except:
                pass

        # Si pas de texte brut, convertir le HTML
        if not body and html_body:
            body = self._clean_html_to_text(html_body)

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

    def list_folders(self) -> List[str]:
        """Liste tous les dossiers disponibles sur le serveur IMAP"""
        folders = []

        if not self.imap_connection:
            if not self.connect_imap():
                return folders

        try:
            status, folder_list = self.imap_connection.list()
            if status == 'OK':
                for folder_data in folder_list:
                    # Parse le nom du dossier depuis la réponse IMAP
                    if isinstance(folder_data, bytes):
                        folder_data = folder_data.decode('utf-8')
                    # Format typique: '(\\HasNoChildren) "/" "INBOX"'
                    parts = folder_data.split('"')
                    if len(parts) >= 2:
                        folder_name = parts[-2] if parts[-1] == '' else parts[-1]
                        folders.append(folder_name.strip())
                logger.info(f"Dossiers disponibles: {folders}")
        except Exception as e:
            logger.error(f"Erreur listing folders: {e}")

        return folders

    def fetch_emails_from_folders(self, folders: List[str] = None, limit: int = None) -> List[Dict]:
        """Récupère les emails de plusieurs dossiers"""
        if folders is None:
            folders = ["INBOX", "Archive"]

        all_emails = []
        seen_message_ids = set()

        for folder in folders:
            try:
                folder_emails = self.fetch_unread_emails(folder=folder, limit=limit)
                for email_data in folder_emails:
                    # Évite les doublons basés sur message_id
                    if email_data['message_id'] not in seen_message_ids:
                        seen_message_ids.add(email_data['message_id'])
                        email_data['folder'] = folder
                        all_emails.append(email_data)
            except Exception as e:
                logger.error(f"Erreur récupération dossier {folder}: {e}")
                continue

        # Trie par date décroissante
        all_emails.sort(key=lambda x: x.get('received_at') or datetime.min, reverse=True)

        logger.info(f"Total récupéré de tous les dossiers: {len(all_emails)} emails")
        return all_emails

    def fetch_unread_emails(self, folder: str = "INBOX", limit: int = None) -> List[Dict]:
        """Récupère tous les emails (lus et non lus) - sans limite par défaut"""
        emails = []

        if not self.imap_connection:
            if not self.connect_imap():
                return emails

        try:
            # Essaie différentes variantes du nom de dossier
            folder_variants = [folder, f'"{folder}"', folder.upper(), folder.lower()]
            selected = False

            for variant in folder_variants:
                try:
                    status, _ = self.imap_connection.select(variant)
                    if status == 'OK':
                        selected = True
                        logger.info(f"Dossier sélectionné: {variant}")
                        break
                except:
                    continue

            if not selected:
                logger.warning(f"Impossible de sélectionner le dossier {folder}")
                return emails

            # Récupère d'abord la liste des emails non lus pour savoir lesquels sont lus/non lus
            status, unseen_messages = self.imap_connection.search(None, 'UNSEEN')
            unseen_ids = set(unseen_messages[0].split()) if status == 'OK' and unseen_messages[0] else set()

            # Recherche de TOUS les emails (pas seulement non lus)
            status, messages = self.imap_connection.search(None, 'ALL')

            if status != 'OK':
                logger.error("Erreur lors de la recherche des emails")
                return emails

            email_ids = messages[0].split()
            logger.info(f"Nombre total d'emails trouvés dans {folder}: {len(email_ids)}")

            # Prend les emails les plus récents (applique une limite seulement si spécifiée)
            if limit is not None and len(email_ids) > limit:
                email_ids = email_ids[-limit:]
            # Inverse pour avoir les plus récents en premier
            email_ids = list(reversed(email_ids))

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

                    # Vérifie si l'email est lu ou non
                    is_read = email_id not in unseen_ids

                    emails.append({
                        'message_id': message_id,
                        'sender_email': sender_info['email'],
                        'sender_name': sender_info['name'],
                        'subject': subject,
                        'body': body,
                        'received_at': received_at,
                        'order_number': order_number,
                        'imap_id': email_id.decode() if isinstance(email_id, bytes) else email_id,
                        'is_read': is_read
                    })

                except Exception as e:
                    logger.error(f"Erreur parsing email {email_id}: {e}")
                    continue

            logger.info(f"Récupéré {len(emails)} emails (lus et non lus)")
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
            handler.imap_connection.select('INBOX')

            # Compte TOUS les emails
            status_all, messages_all = handler.imap_connection.search(None, 'ALL')
            # Compte les emails non lus
            status_unseen, messages_unseen = handler.imap_connection.search(None, 'UNSEEN')

            if status_all == 'OK':
                total_count = len(messages_all[0].split()) if messages_all[0] else 0
                unseen_count = len(messages_unseen[0].split()) if status_unseen == 'OK' and messages_unseen[0] else 0
                result['success'] = True
                result['message'] = f"Connexion réussie ! {total_count} emails ({unseen_count} non lus)."
                result['email_count'] = total_count
            else:
                result['message'] = "Connexion OK mais erreur lecture INBOX"

            handler.disconnect_imap()
        else:
            result['message'] = "Échec de connexion - vérifiez vos identifiants"

    except Exception as e:
        result['message'] = f"Erreur: {str(e)}"

    return result
