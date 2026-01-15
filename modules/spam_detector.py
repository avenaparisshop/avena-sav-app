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

# === DOMAINES OFFICIELS (pour vérification des faux) ===
# Ces domaines sont les SEULS légitimes pour ces marques
OFFICIAL_DOMAINS = {
    'shopify': ['@shopify.com', '@shopifymail.com', '@shopifyemail.com', '@shop.app', '@myshopify.com'],
    'meta': ['@meta.com', '@metamail.com', '@fb.com'],
    'facebook': ['@facebookmail.com', '@facebook.com', '@fb.com', '@support.facebook.com'],
    'instagram': ['@instagram.com', '@mail.instagram.com'],
    'tiktok': ['@tiktok.com', '@tiktokmail.com', '@bytedance.com'],
    'google': ['@google.com', '@googlemail.com', '@accounts.google.com'],
    'paypal': ['@paypal.com', '@paypal.fr', '@e.paypal.com', '@e.paypal.fr'],
    'stripe': ['@stripe.com', '@stripemail.com'],
}

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

    # === FAUX SUPPORT SHOPIFY (n'importe quel domaine sauf officiel) ===
    r'shopify.*@gmail\.com',           # shopifykelvinteam, shopifyappguide, etc.
    r'info\.shopify.*@gmail\.com',     # info.shopifystoresb.co, etc.
    r'contact\.shopify.*@gmail\.com',  # contact.shopifymailer
    r'mailer\.shopify.*@gmail\.com',   # mailer.shopifycomplianceservice
    r'support.*shopify.*@gmail\.com',  # support Shopify fake
    r'shopify.*@.*\.com$',             # Tout email avec "shopify" qui n'est pas @shopify.com
    r'shopify.*@outlook\.com',         # Faux Shopify Outlook
    r'shopify.*@hotmail\.com',         # Faux Shopify Hotmail
    r'shopify.*@yahoo\.com',           # Faux Shopify Yahoo

    # === FAUX SUPPORT META/FACEBOOK (n'importe quel domaine sauf officiel) ===
    r'meta.*@gmail\.com',              # Faux Meta Gmail
    r'facebook.*@gmail\.com',          # Faux Facebook Gmail
    r'fb.*support.*@gmail\.com',       # Faux FB support
    r'meta.*@outlook\.com',            # Faux Meta Outlook
    r'facebook.*@outlook\.com',        # Faux Facebook Outlook
    r'meta.*@hotmail\.com',            # Faux Meta Hotmail
    r'facebook.*@hotmail\.com',        # Faux Facebook Hotmail
    r'instagram.*@gmail\.com',         # Faux Instagram Gmail
    r'instagram.*@outlook\.com',       # Faux Instagram Outlook

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

    # === GMAIL DÉMARCHEURS AFRICAINS (patterns très courants) ===
    r'[a-z]+\d{2,}@gmail\.com',        # prénom + 2+ chiffres: adeola07, sodiq7773, etc.
    r'[a-z]+[a-z]+\d{1,}@gmail\.com',  # prénomnom + chiffres
    r'.*praise.*@gmail\.com',          # ajaykopraise, praise, etc.
    r'.*blessed.*@gmail\.com',         # braydenblessed, etc.
    r'.*prince.*@gmail\.com',          # gideonprince, etc.
    r'.*king.*@gmail\.com',            # kingXXX
    r'.*lord.*@gmail\.com',            # lordXXX
    r'.*star.*@gmail\.com',            # praisestar, allstar, etc.
    r'.*smart.*@gmail\.com',           # smartXXX, ibsmart
    r'.*tech.*@gmail\.com',            # techXXX
    r'.*global.*@gmail\.com',          # globalXXX
    r'.*world.*@gmail\.com',           # worldXXX
    r'.*best.*@gmail\.com',            # bestXXX
    r'.*top.*@gmail\.com',             # topXXX
    r'.*pro\d*@gmail\.com',            # proXXX
    r'.*ceo.*@gmail\.com',             # ceoXXX
    r'.*boss.*@gmail\.com',            # bossXXX
    r'.*chief.*@gmail\.com',           # chiefXXX

    # === GMAIL AVEC MOTS SUSPECTS ===
    r'.*\.hello@gmail\.com',           # bassman.hello, etc. (format prénom.hello)
    r'.*hello\..*@gmail\.com',         # hello.xxx@gmail.com
    r'.*\.hi@gmail\.com',              # xxx.hi@gmail.com
    r'.*contact\..*@gmail\.com',       # contact.xxx@gmail.com
    r'.*info\..*@gmail\.com',          # info.xxx@gmail.com
    r'.*support\..*@gmail\.com',       # support.xxx@gmail.com
    r'.*sales\..*@gmail\.com',         # sales.xxx@gmail.com
    r'.*marketing\..*@gmail\.com',     # marketing.xxx@gmail.com
    r'.*business\..*@gmail\.com',      # business.xxx@gmail.com
    r'.*official\..*@gmail\.com',      # official.xxx@gmail.com
    r'.*team\..*@gmail\.com',          # team.xxx@gmail.com
    r'.*service\..*@gmail\.com',       # service.xxx@gmail.com

    # === GMAIL NOMS GÉNÉRIQUES SUSPECTS ===
    r'graecemarry@gmail\.com',         # graecemarry - spammeur connu
    r'.*marry\d*@gmail\.com',          # xxxmarry, marry123
    r'.*grace\d*@gmail\.com',          # gracexxx (sans commande = suspect)
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
    r'^hello.*avenaparis',                 # Hello Avenaparis (Radex-style)
    r'^hi.*avenaparis',                    # Hi Avenaparis
    r'^hey.*avenaparis',                   # Hey Avenaparis
    r'^\d+\s*new\s*order',                 # "1 NEW ORDER" - faux pattern de commande
    r'^new\s*order$',                      # Juste "New order" sans numéro
    r'^order\s*confirmation$',             # Faux "Order confirmation" générique
    r'^greetings$',                        # Juste "GREETINGS"
    r'^salut$',                            # Juste "Salut"
    r'^salut.*avena',                      # Salut Avenaparis
    r'^bonjour$',                          # Juste "Bonjour"
    r'^important.*message$',               # "IMPORTANT MESSAGE"
    r'^urgent$',                           # Juste "Urgent"
    r'^urgent.*message',                   # Urgent message
    r'^question$',                         # Juste "Question"
    r'^quick.*question',                   # Quick question about...
    r'^inquiry$',                          # Juste "Inquiry"
    r'^request$',                          # Juste "Request"
    r'^opportunity$',                      # Juste "Opportunity"
    r'^proposal$',                         # Juste "Proposal"
    r'^partnership$',                      # Juste "Partnership"
    r'^collaboration$',                    # Juste "Collaboration"
    r'is.*this.*your.*active',             # Is this your active business inbox
    r'your.*active.*business',             # your active business
    r'anyone.*here.*to.*attend',           # Hello anyone here to attend to me

    # === DÉMARCHAGE AVEC "IDÉE" / "IDEA" ===
    r'id[ée]e.*rapide',                    # Idée rapide pour...
    r'quick.*idea',                        # Quick idea for...
    r'id[ée]e.*pour.*avena',               # Idée pour Avenaparis
    r'idea.*for.*avena',                   # Idea for Avenaparis
    r'thought.*for.*avena',                # Thought for Avenaparis

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

    # === PHRASES DE DÉMARCHAGE TRÈS COURANTES ===
    r'is.*your.*store.*live',              # Is your store live and making sales?
    r'your.*store.*live.*and.*making',     # your store live and making sales
    r'help.*you.*consistently.*generate',  # help you consistently generate
    r'generate.*\d+.*sales.*per.*day',     # generate 25-30 sales per day
    r'newly.*proven.*strategy',            # newly proven strategy
    r'would.*you.*be.*open.*to.*learning', # Would you be open to learning
    r'open.*to.*learning.*how',            # open to learning how it works
    r'increase.*conversions',              # increase conversions
    r'boost.*your.*sales',                 # boost your sales
    r'grow.*your.*store',                  # grow your store
    r'scale.*your.*business',              # scale your business
    r'hello.*there',                       # Hello there! (démarchage)
    r'hello.*anyone.*here',                # Hello anyone here to attend to me
    r'anyone.*here.*to.*attend',           # anyone here to attend to me
    r'attend.*to.*me',                     # attend to me
    r'get.*back.*to.*me',                  # get back to me
    r'let.*me.*know.*if.*you.*are',        # let me know if you are interested
    r'kindly.*get.*back',                  # kindly get back to me
    r'kindly.*reply',                      # kindly reply
    r'awaiting.*your.*response',           # awaiting your response
    r'hope.*to.*hear.*from.*you',          # hope to hear from you
    r'looking.*forward.*to.*hearing',      # looking forward to hearing

    # === DÉMARCHAGE SERVICES (freelancers, agences) ===
    r'i.*specialize.*in',                  # I specialize in...
    r'my.*name.*is.*and.*i',               # My name is X and I...
    r'i.*am.*a.*freelance',                # I am a freelance...
    r'i.*am.*a.*professional',             # I am a professional...
    r'i.*offer.*my.*services',             # I offer my services
    r'we.*offer.*our.*services',           # We offer our services
    r'i.*can.*help.*you.*with',            # I can help you with
    r'we.*can.*help.*you.*with',           # We can help you with
    r'i.*noticed.*your.*store',            # I noticed your store
    r'i.*noticed.*your.*website',          # I noticed your website
    r'i.*came.*across.*your',              # I came across your store/website
    r'i.*found.*your.*store',              # I found your store
    r'i.*was.*browsing.*your',             # I was browsing your website
    r'your.*store.*caught.*my',            # Your store caught my attention
    r'i.*would.*like.*to.*offer',          # I would like to offer
    r'we.*would.*like.*to.*offer',         # We would like to offer
    r'i.*have.*experience.*in',            # I have experience in
    r'years.*of.*experience',              # X years of experience
    r'let.*me.*introduce.*myself',         # Let me introduce myself
    r'allow.*me.*to.*introduce',           # Allow me to introduce
    r'i.*am.*reaching.*out.*because',      # I am reaching out because
    r'i.*am.*writing.*to.*you.*because',   # I am writing to you because
    r'i.*wanted.*to.*reach.*out',          # I wanted to reach out
    r'just.*wanted.*to.*reach.*out',       # Just wanted to reach out
    r'reaching.*out.*to.*see.*if',         # Reaching out to see if
    r'i.*have.*a.*proposal',               # I have a proposal
    r'i.*have.*an.*idea',                  # I have an idea
    r'i.*have.*a.*question.*for.*you',     # I have a question for you
    r'quick.*question.*for.*you',          # Quick question for you
    r'i.*have.*something.*interesting',    # I have something interesting
    r'i.*think.*i.*can.*help',             # I think I can help
    r'i.*believe.*i.*can.*help',           # I believe I can help
    r'are.*you.*interested.*in',           # Are you interested in
    r'would.*you.*be.*interested',         # Would you be interested
    r'interested.*in.*working.*together',  # Interested in working together
    r'let\'s.*work.*together',             # Let's work together
    r'let\'s.*collaborate',                # Let's collaborate
    r'open.*for.*collaboration',           # Open for collaboration
    r'looking.*for.*collaboration',        # Looking for collaboration
    r'partnership.*opportunity',           # Partnership opportunity
    r'business.*opportunity',              # Business opportunity
    r'exciting.*opportunity',              # Exciting opportunity
    r'great.*opportunity',                 # Great opportunity
    r'unique.*opportunity',                # Unique opportunity

    # === SERVICES SPÉCIFIQUES SOUVENT PROPOSÉS PAR SPAM ===
    r'video.*editing',                     # Video editing services
    r'photo.*editing',                     # Photo editing
    r'graphic.*design',                    # Graphic design
    r'logo.*design',                       # Logo design
    r'web.*design',                        # Web design
    r'website.*design',                    # Website design
    r'app.*development',                   # App development
    r'mobile.*app',                        # Mobile app
    r'seo.*service',                       # SEO services
    r'social.*media.*management',          # Social media management
    r'content.*creation',                  # Content creation
    r'copywriting',                        # Copywriting
    r'email.*marketing',                   # Email marketing
    r'lead.*generation',                   # Lead generation
    r'virtual.*assistant',                 # Virtual assistant
    r'customer.*service.*support',         # Customer service support
    r'data.*entry',                        # Data entry
    r'bookkeeping',                        # Bookkeeping
    r'accounting.*service',                # Accounting services
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

# === PATTERNS DE VRAIS CLIENTS ===
# Ces phrases indiquent que quelqu'un parle de SA PROPRE commande = client légitime
CLIENT_PATTERNS = [
    # Références à une commande personnelle
    r'ma\s*commande',                    # ma commande
    r'mon\s*colis',                      # mon colis
    r'mon\s*achat',                      # mon achat
    r'my\s*order',                       # my order
    r'my\s*package',                     # my package
    r'mi\s*pedido',                      # mi pedido (ES)
    r'mijn\s*bestelling',                # mijn bestelling (NL)
    r'meine\s*bestellung',               # meine Bestellung (DE)
    r'il\s*mio\s*ordine',                # il mio ordine (IT)

    # Numéros de commande mentionnés
    r'commande\s*n[°o]?\s*\d+',          # commande n°12345
    r'order\s*n[°o]?\s*\d+',             # order n°12345
    r'#\d{4,}',                          # #12345 (numéro de commande)
    r'n°\s*\d{4,}',                      # n° 12345

    # Questions sur leur commande
    r'où\s*en\s*est\s*ma',               # où en est ma commande
    r'where\s*is\s*my',                  # where is my order
    r'quand\s*vais.*je\s*recevoir',      # quand vais-je recevoir
    r'when\s*will\s*i\s*receive',        # when will I receive
    r'pas\s*encore\s*reçu',              # pas encore reçu
    r'not\s*yet\s*received',             # not yet received
    r'toujours\s*pas\s*reçu',            # toujours pas reçu
    r'still\s*waiting',                  # still waiting for
    r'j\'attends',                       # j'attends ma commande
    r'i\s*ordered',                      # I ordered
    r'j\'ai\s*commandé',                 # j'ai commandé
    r'j\'ai\s*passé\s*commande',         # j'ai passé commande

    # Problèmes avec leur commande
    r'article\s*manquant',               # article manquant
    r'missing\s*item',                   # missing item
    r'produit\s*défectueux',             # produit défectueux
    r'defective\s*product',              # defective product
    r'colis\s*endommagé',                # colis endommagé
    r'package\s*damaged',                # package damaged
    r'mauvaise\s*taille',                # mauvaise taille
    r'wrong\s*size',                     # wrong size
    r'erreur\s*dans\s*ma',               # erreur dans ma commande
    r'error\s*in\s*my',                  # error in my order

    # Retours et remboursements personnels
    r'je\s*souhaite\s*retourner',        # je souhaite retourner
    r'i\s*want\s*to\s*return',           # I want to return
    r'je\s*voudrais\s*être\s*remboursé', # je voudrais être remboursé
    r'i\s*would\s*like\s*a\s*refund',    # I would like a refund
    r'demande\s*de\s*retour',            # demande de retour
    r'return\s*request',                 # return request
    r'échanger\s*mon',                   # échanger mon article
    r'exchange\s*my',                    # exchange my item

    # Suivi de leur commande
    r'suivi\s*de\s*ma',                  # suivi de ma commande
    r'tracking\s*(number|info)',         # tracking number/info
    r'numéro\s*de\s*suivi',              # numéro de suivi
    r'statut\s*de\s*ma',                 # statut de ma commande
    r'status\s*of\s*my',                 # status of my order

    # Modifications de leur commande
    r'modifier\s*ma\s*commande',         # modifier ma commande
    r'change\s*my\s*order',              # change my order
    r'annuler\s*ma\s*commande',          # annuler ma commande
    r'cancel\s*my\s*order',              # cancel my order
    r'changer\s*l\'adresse',             # changer l'adresse de livraison
    r'change\s*the\s*address',           # change the address
]


def is_fake_brand_email(sender_email: str, subject: str, sender_name: str, body: str = "") -> Tuple[bool, str]:
    """
    Détecte si l'email se fait passer pour une marque connue (Shopify, Meta, Facebook, etc.)
    mais n'utilise pas le vrai domaine officiel.

    RÈGLE: Si le sujet, le nom de l'expéditeur OU LE BODY mentionne Shopify/Meta/Facebook/etc.
    mais que le domaine email n'est PAS officiel = SPAM + BLOQUER

    Returns:
        Tuple (is_fake, brand_name)
    """
    sender_lower = sender_email.lower() if sender_email else ''
    subject_lower = subject.lower() if subject else ''
    name_lower = sender_name.lower() if sender_name else ''
    body_lower = body.lower() if body else ''
    # Vérifie dans sujet, nom ET body
    full_text = f"{subject_lower} {name_lower} {body_lower}"

    # Liste des marques à vérifier
    # ATTENTION: Seuls les mots-clés SPÉCIFIQUES à la marque, pas génériques comme "your store"
    brand_keywords = {
        'shopify': ['shopify', 'shop.app'],
        'meta': ['meta business', 'meta ads', 'meta support', 'meta platform'],
        'facebook': ['facebook', 'fb ads', 'fb business', 'facebook page', 'facebook ads'],
        'instagram': ['instagram', 'ig business', 'instagram account'],
        'tiktok': ['tiktok', 'tik tok', 'tiktok shop'],
        'google': ['google ads', 'google business', 'google merchant'],
        'paypal': ['paypal'],
        'stripe': ['stripe'],
    }

    for brand, keywords in brand_keywords.items():
        # Vérifie si le sujet ou le nom mentionne la marque
        brand_mentioned = False
        for keyword in keywords:
            if keyword in full_text:
                brand_mentioned = True
                break

        if brand_mentioned:
            # Vérifie si le domaine est officiel
            official_domains = OFFICIAL_DOMAINS.get(brand, [])
            is_official = any(domain in sender_lower for domain in official_domains)

            if not is_official:
                logger.warning(f"FAUX EMAIL {brand.upper()} détecté: {sender_email} (sujet/nom mentionne {brand} mais domaine non officiel)")
                return True, brand

    return False, ""


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


def is_real_client(subject: str, body: str) -> Tuple[bool, str]:
    """
    Vérifie si l'email provient d'un vrai client qui parle de SA commande.

    LOGIQUE IMPORTANTE:
    - Si quelqu'un pose des questions sur SA commande = vrai client
    - Si quelqu'un propose d'apporter des commandes/ventes = démarcheur/spam

    Returns:
        Tuple (is_client, reason)
    """
    subject_lower = subject.lower() if subject else ''
    body_lower = body.lower() if body else ''
    full_text = f"{subject_lower} {body_lower}"

    # Vérifie si l'email contient des patterns de vrai client
    for pattern in CLIENT_PATTERNS:
        if re.search(pattern, full_text, re.IGNORECASE):
            return True, f"client_pattern:{pattern[:25]}"

    return False, "no_client_pattern"


def detect_spam(sender_email: str, sender_name: str, subject: str, body: str) -> Tuple[bool, float, str]:
    """
    Détecte si un email est du spam

    LOGIQUE IMPORTANTE:
    - Si quelqu'un pose des questions sur SA commande = vrai client (jamais spam)
    - Si quelqu'un propose d'apporter des commandes/ventes = démarcheur/spam
    - Si l'email prétend être Shopify/Meta/Facebook mais domaine non officiel = SPAM CRITIQUE

    Returns:
        Tuple (is_spam, confidence, reason)
    """
    # D'abord vérifier la whitelist
    if is_whitelisted(sender_email, subject):
        return False, 0.0, "whitelisted"

    # === DÉTECTION FAUX EMAILS DE MARQUES (priorité haute) ===
    # Un email qui se fait passer pour Shopify/Meta/Facebook = TOUJOURS SPAM
    # Vérifie dans le sujet, le nom ET le body de l'email
    is_fake, fake_brand = is_fake_brand_email(sender_email, subject, sender_name, body)
    if is_fake:
        logger.warning(f"FAUX {fake_brand.upper()} BLOQUÉ: {sender_email} - {subject[:50]}...")
        return True, 1.0, f"fake_brand:{fake_brand}"

    # === VÉRIFICATION VRAI CLIENT ===
    # Si l'email parle de SA propre commande, c'est un vrai client = jamais spam
    is_client, client_reason = is_real_client(subject, body)
    if is_client:
        logger.info(f"VRAI CLIENT détecté: {sender_email} - {subject[:50]}... | Raison: {client_reason}")
        return False, 0.0, f"real_client:{client_reason}"

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
        'solutions', 'services', 'digital', 'media', 'studio', 'labs',
        # Noms suspects additionnels
        'xpert', 'radex', 'boost', 'promo', 'offer', 'deal', 'sales'
    ]
    for word in suspicious_names:
        if word in sender_name_lower and not is_whitelisted(sender_email, subject):
            # Vérifie que ce n'est pas un vrai email officiel
            if not any(legit in sender_lower for legit in ['@facebook.com', '@meta.com', '@tiktok.com', '@instagram.com']):
                spam_score += 0.35  # Augmenté de 0.15 à 0.35 pour mieux détecter
                reasons.append(f"suspicious_name:{word}")
                break

    # === DÉTECTION GMAIL GÉNÉRIQUE NON-PROFESSIONNEL ===
    # Les vrais clients utilisent rarement des adresses Gmail avec des patterns suspects
    if '@gmail.com' in sender_lower:
        # Vérifie si c'est un pattern de nom africain/démarcheur typique
        gmail_name = sender_lower.split('@')[0]
        # Pattern: prénom + chiffres ou prénom + mot + chiffres
        if re.search(r'^[a-z]+\d{2,}$', gmail_name) or re.search(r'^[a-z]+[a-z]+\d+$', gmail_name):
            spam_score += 0.3
            reasons.append("gmail_suspect_pattern")

    # Cap le score à 1.0
    spam_score = min(spam_score, 1.0)

    # Seuil de détection: 0.35 (abaissé de 0.5 pour être plus agressif)
    is_spam = spam_score >= 0.35

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
