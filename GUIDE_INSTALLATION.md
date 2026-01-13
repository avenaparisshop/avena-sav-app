# 🚀 Guide d'Installation - Avena SAV App

Ce guide t'accompagne pas à pas pour installer et configurer ton application SAV automatisée.

---

## 📋 Prérequis

- Un compte Zoho Mail avec IMAP activé
- Un compte Shopify Partners (pour le Dev Dashboard)
- Un compte Anthropic (Claude API)
- Un compte Railway (gratuit) pour héberger l'app

---

## Étape 1 : Obtenir les clés API

### 1.1 Zoho Mail (IMAP)

1. **Connecte-toi** à [mail.zoho.eu](https://mail.zoho.eu)

2. **Active IMAP** :
   - Clique sur l'engrenage ⚙️ (Paramètres)
   - Va dans "Mail Accounts" → "IMAP"
   - Active "IMAP Access"

3. **Si tu as la double authentification (2FA)** :
   - Va dans [accounts.zoho.eu](https://accounts.zoho.eu)
   - Section "Security" → "App Passwords"
   - Crée un mot de passe pour "Desktop Mail Client"
   - **Note ce mot de passe** (tu ne pourras plus le voir après)

4. **Infos à noter** :
   ```
   ZOHO_EMAIL = ton-email@avena-paris.com
   ZOHO_PASSWORD = le-mot-de-passe-app (ou ton mdp normal si pas de 2FA)
   ZOHO_IMAP_SERVER = imap.zoho.eu
   ZOHO_SMTP_SERVER = smtp.zoho.eu
   ```

---

### 1.2 Shopify API (OAuth Multi-Stores)

> ⚠️ **Nouveau système (2024+)** : Shopify utilise maintenant OAuth via le Dev Dashboard au lieu des tokens statiques.

#### A. Créer l'application dans Shopify Partners

1. **Connecte-toi** au [Shopify Partners Dashboard](https://partners.shopify.com)

2. **Pour CHAQUE store** (France, NL, ES, IT, DE), tu dois :
   - Aller dans le bon **Organization** (chaque store a sa propre org)
   - Apps → Create app
   - Nom : "SAV Bot" (ou "SAV Bot FR", "SAV Bot NL", etc.)

3. **Configure l'app** :
   - Va dans **Configuration**
   - **App URL** : `https://ton-app.up.railway.app` (l'URL Railway)
   - **Allowed redirection URL(s)** : `https://ton-app.up.railway.app/shopify/callback`

4. **Configure les scopes API** :
   - Dans **Access scopes**, ajoute :
     - `read_orders` (Lecture des commandes)
     - `read_customers` (Lecture des clients)
   - Sauvegarde

5. **Note les identifiants OAuth** :
   - Va dans l'onglet **Overview**
   - Copie le **Client ID**
   - Clique "Get Client Secret" et copie le **Client Secret**

#### B. Structure multi-stores

Si tu as plusieurs stores (ex: Avena Paris FR, NL, ES...), **chaque store appartient à une organisation différente** dans Shopify Partners. Tu dois :

1. Créer une app SAV Bot dans **chaque organisation**
2. Noter les Client ID/Secret de chaque app

**Exemple pour Avena Paris :**

| Store | Organization ID | Client ID |
|-------|-----------------|-----------|
| France (ajejh8-ms) | 168334270 | 6ed36a6368e9a621351048f62732aef2 |
| Netherlands (z1w10j-ne) | 199778121 | b7530e65ea147fb9bbc773a4cabded53 |
| Spain | ... | ... |
| Italy | ... | ... |
| Germany | ... | ... |

#### C. Connexion des stores à l'app

Une fois l'app déployée sur Railway :

1. Ouvre l'URL de ton app
2. Va dans **Stores** (menu ou `/stores`)
3. Clique **Connecter un store**
4. Entre le nom du store (ex: `ajejh8-ms`)
5. Tu seras redirigé vers Shopify pour autoriser l'app
6. Après autorisation, le token est automatiquement sauvegardé

---

### 1.3 Claude API (Anthropic)

1. **Crée un compte** sur [console.anthropic.com](https://console.anthropic.com)

2. **Ajoute des crédits** :
   - Va dans "Plans & Billing"
   - Ajoute minimum $5 de crédits
   - (Ça coûte environ $0.003 par email traité)

3. **Crée une clé API** :
   - Va dans "API Keys"
   - Clique "Create Key"
   - Donne un nom : "Avena SAV"
   - **Copie la clé** (commence par `sk-ant-...`)

4. **Info à noter** :
   ```
   ANTHROPIC_API_KEY = sk-ant-xxxxxxxxxxxxxxxxxxxxx
   ```

---

## Étape 2 : Déployer sur Railway

Railway est une plateforme d'hébergement simple et gratuite pour commencer.

### 2.1 Créer un compte Railway

1. Va sur [railway.app](https://railway.app)
2. Connecte-toi avec GitHub (recommandé)

### 2.2 Déployer l'application

1. **Télécharge le code** de l'application (le dossier `avena-sav-app`)

2. **Crée un nouveau projet Railway** :
   - Clique "New Project"
   - Choisis "Deploy from GitHub repo" ou "Empty project"

3. **Si GitHub** :
   - Crée un nouveau repo GitHub avec le code
   - Connecte-le à Railway

4. **Si upload direct** :
   - Utilise la Railway CLI ou zip le projet

### 2.3 Configurer les variables d'environnement

Dans Railway, va dans ton projet → Variables et ajoute :

```bash
# Zoho Mail
ZOHO_EMAIL=sav@avena-paris.com
ZOHO_PASSWORD=ton-mot-de-passe
ZOHO_IMAP_SERVER=imap.zoho.eu
ZOHO_SMTP_SERVER=smtp.zoho.eu

# Shopify OAuth (nouveau système)
SHOPIFY_CLIENT_ID=6ed36a6368e9a621351048f62732aef2
SHOPIFY_CLIENT_SECRET=ton-client-secret
SHOPIFY_SCOPES=read_orders,read_customers
SHOPIFY_TOKENS_FILE=shopify_tokens.json

# (Optionnel) Shopify Legacy - si tu as un token statique existant
# SHOPIFY_SHOP_NAME=ajejh8-ms
# SHOPIFY_ACCESS_TOKEN=shpat_xxxxxx

# Claude API
ANTHROPIC_API_KEY=sk-ant-xxxxxx

# Flask
SECRET_KEY=une-longue-chaine-random-ici
FLASK_ENV=production

# Automatisation
AUTO_SEND_TRACKING=true
AUTO_SEND_RETURN_CONFIRM=false
EMAIL_CHECK_INTERVAL=300
```

> 💡 **Note Multi-Stores** : Si tu as plusieurs apps Shopify (une par store), tu utiliseras le même `SHOPIFY_CLIENT_ID` et `SHOPIFY_CLIENT_SECRET` pour le store principal. Les autres stores seront connectés via OAuth dans l'interface.

### 2.4 Configurer l'URL de callback dans Shopify

**IMPORTANT** : Après avoir déployé sur Railway et obtenu ton URL :

1. Va dans [Shopify Partners](https://partners.shopify.com)
2. Pour chaque app SAV Bot créée :
   - Va dans **Configuration**
   - Ajoute l'URL de callback : `https://ton-app.up.railway.app/shopify/callback`
   - Sauvegarde

### 2.5 Lancer l'application

1. Railway va automatiquement détecter que c'est une app Python
2. Il va installer les dépendances et lancer l'app
3. Tu recevras une URL du type : `https://avena-sav-xxx.up.railway.app`

---

## Étape 3 : Connecter les stores Shopify

### 3.1 Premier store

1. **Ouvre l'URL** de ton app Railway
2. Va dans **Stores** (`/stores`)
3. Clique **Connecter un nouveau store**
4. Entre le nom du store (ex: `ajejh8-ms` pour Avena Paris France)
5. Clique **Connecter**
6. Tu seras redirigé vers Shopify
7. Autorise l'application
8. Retour automatique sur la page de succès

### 3.2 Stores supplémentaires

Pour chaque store supplémentaire (NL, ES, IT, DE) :

1. **Important** : Assure-toi que l'app SAV Bot existe dans l'organisation de ce store
2. Répète le processus de connexion pour chaque store
3. Les tokens sont automatiquement sauvegardés

### 3.3 Vérifier les connexions

1. Va dans **Stores** (`/stores`)
2. Tu dois voir tous tes stores connectés avec ✅
3. Clique **Tester** pour vérifier que le token fonctionne

---

## Étape 4 : Tester l'installation

1. **Ouvre l'URL** de ton app Railway

2. **Va dans Paramètres** (icône engrenage)

3. **Clique "Tester les connexions"**
   - ✅ Zoho Mail : doit afficher "Connexion réussie"
   - ✅ Shopify : doit afficher les stores connectés
   - ✅ Claude : doit afficher "Connexion réussie"

4. **Si une connexion échoue**, vérifie :
   - Les identifiants dans les variables Railway
   - Que l'IMAP est bien activé sur Zoho
   - Que l'app Shopify a les bonnes permissions et l'URL de callback

---

## Étape 5 : Utilisation quotidienne

### Dashboard principal

1. **Actualiser** : Clique le bouton pour récupérer les nouveaux emails
2. **Liste des emails** : Affiche les demandes SAV à traiter
3. **Détail** : Voir le message client + réponse générée

### Traiter un email

1. **Clic** sur un email dans la liste
2. **Lis** le message du client
3. **Vérifie** la réponse générée par Claude
4. **Actions** :
   - ✅ **Approuver** : Envoie directement
   - ✏️ **Modifier** : Ajuste la réponse avant envoi
   - ❌ **Ignorer** : Ne pas répondre

### Gestion Multi-Stores

- L'app détecte automatiquement à quel store appartient une commande
- La recherche se fait sur tous les stores connectés
- Tu peux voir les infos du store dans les détails de la commande

### Automatisation

Par défaut, les emails de **suivi de commande** avec tracking disponible sont envoyés automatiquement. Tu peux désactiver ça dans les variables :

```
AUTO_SEND_TRACKING=false
```

---

## 🔧 Dépannage

### "Connexion Zoho échouée"
- Vérifie que IMAP est activé
- Si 2FA activé, utilise un mot de passe d'application
- Essaie avec `imap.zoho.com` au lieu de `imap.zoho.eu`

### "Connexion Shopify échouée" / "Token invalide"
- Vérifie que le store est bien connecté via OAuth
- Reconnecte le store depuis la page `/stores`
- Vérifie l'URL de callback dans Shopify Partners

### "Erreur OAuth : invalid_request"
- Vérifie que `SHOPIFY_CLIENT_ID` et `SHOPIFY_CLIENT_SECRET` sont corrects
- Vérifie que l'URL de callback est bien configurée dans Shopify Partners
- L'URL doit correspondre exactement : `https://ton-app.up.railway.app/shopify/callback`

### "Cette app ne peut pas être installée sur ce store"
- Tu dois créer une app SAV Bot dans **l'organisation** du store concerné
- Chaque store peut appartenir à une organisation différente

### "Connexion Claude échouée"
- Vérifie que tu as des crédits sur ton compte Anthropic
- Vérifie que la clé API est correcte et active

### "Numéro de commande non trouvé"
- L'app cherche des patterns comme #1234 ou "commande 1234"
- Si le client n'a pas mentionné le numéro, l'app cherche par email
- L'app recherche sur tous les stores connectés

---

## 💰 Coûts estimés

| Service | Coût |
|---------|------|
| Railway | Gratuit (500h/mois) ou ~$5/mois |
| Claude API | ~$0.003/email ≈ $1.50/500 emails |
| Zoho | Déjà payé |
| Shopify | Déjà payé |

**Total estimé** : $5-10/mois pour ~500 emails SAV

---

## 📝 Résumé des URLs importantes

| Service | URL |
|---------|-----|
| Shopify Partners | https://partners.shopify.com |
| Zoho Mail | https://mail.zoho.eu |
| Anthropic Console | https://console.anthropic.com |
| Railway | https://railway.app |

---

## 📞 Support

Des questions ? Besoin d'aide pour la config ?

Tu peux me recontacter sur Claude pour de l'aide !

---

Bonne utilisation ! 🎉
