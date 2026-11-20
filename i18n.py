"""Interface bilingue : anglais (par défaut) et français.

La langue est choisie par l'administrateur (réglage « default_lang ») et
s'applique à toutes les pages et à tous les courriels. Les visiteurs ne
peuvent pas la changer.

Le texte source est l'anglais. FR_STRINGS associe chaque texte anglais à sa
traduction française ; un texte absent du dictionnaire reste en anglais.
"""

SUPPORTED_LANGS = ("en", "fr")

_default_lang = "en"


def set_default_language(code: str):
    """Appelé à chaque changement de configuration."""
    global _default_lang
    _default_lang = code if code in SUPPORTED_LANGS else "en"


def get_lang() -> str:
    """Langue d'affichage : toujours celle choisie par l'administrateur."""
    return _default_lang


def t(text: str, lang: str = None, **kwargs) -> str:
    """Texte traduit. kwargs remplacent les champs {nom} du texte."""
    lang = lang if lang in SUPPORTED_LANGS else get_lang()
    if lang == "fr":
        text = FR_STRINGS.get(text, text)
    return text.format(**kwargs) if kwargs else text


from i18n_fr import FR_EXTRA as _FR_EXTRA  # noqa: E402  (chargé après FR_STRINGS)

FR_STRINGS = {
    # ---- Généralités et navigation ----
    "LLDAP Portal": "Portail LLDAP",
    "Language": "Langue",
    "Invitations": "Invitations",
    "Configuration": "Configuration",
    "Log out": "Se déconnecter",
    "Log in": "Se connecter",
    "Save": "Enregistrer",
    "Back to sign-in": "Retour à la connexion",
    "Username": "Nom d'utilisateur",
    "Password": "Mot de passe",
    "Confirm password": "Confirmer le mot de passe",
    "Email address": "Adresse courriel",
    "Email or username": "Courriel ou nom d'utilisateur",
    "you@example.com or username": "toi@exemple.com ou nom d'utilisateur",
    "Yes": "Oui",
    "No": "Non",
    "(empty)": "(vide)",
    "None": "Aucun",
    "configured": "configuré",
    "to complete": "à compléter",
    "active": "active",
    "disabled": "désactivée",
    "present": "présent",
    "absent": "absent",
    "writable": "inscriptible",
    "not writable": "non inscriptible",
    "Active": "active",
    "Revoked": "révoquée",
    "Expired": "expirée",
    "Used up": "épuisée",

    # ---- Inscription (invite.html) ----
    "Create your account": "Crée ton compte",
    "Check your email": "Vérifie ton courriel",
    "Welcome": "Bienvenue",
    "Invitation": "Invitation",
    "Invalid invitation": "Invitation invalide",
    "Create my account": "Créer mon compte",
    "Confirm the password": "Confirme le mot de passe",
    "Username: 3 to 32 characters": "Nom d'utilisateur : 3 à 32 caractères",
    "Password: at least <strong>10 characters</strong>": "Mot de passe : au moins <strong>10 caractères</strong>",
    "A confirmation code will be sent to the address you enter.": "Un code de confirmation sera envoyé à l'adresse saisie.",
    "A 6-digit code was sent to <strong>{email}</strong>. It expires in 10 minutes.": "Un code à 6 chiffres a été envoyé à <strong>{email}</strong>. Il expire dans 10 minutes.",
    "Verification code": "Code de vérification",
    "Verify": "Vérifier",
    "Resend code": "Renvoyer le code",
    "Enter the 6-digit code.": "Entre le code à 6 chiffres.",
    "Incorrect code.": "Code incorrect.",
    "This code has expired. Request a new one.": "Ce code a expiré. Demande-en un nouveau.",
    "This code is already being verified.": "Ce code est déjà en cours de validation.",
    "Too many attempts. Try again later.": "Trop d'essais. Réessaie plus tard.",
    "Too many attempts. Try again later": "Trop d'essais. Réessaie plus tard",
    "Too many code requests. Try again later.": "Trop de demandes de code. Réessaie plus tard.",
    "Too many code requests for this address. Try again later.": "Trop de demandes de code pour cette adresse. Réessaie plus tard.",
    "Wait {n} more second(s) before requesting a new code.": "Attends encore {n} seconde(s) avant de demander un nouveau code.",
    "A new code has been sent.": "Un nouveau code a été envoyé.",
    "You're all set": "C'est fait",
    "Your account <strong>{username}</strong> has been created. You can now sign in with your username and password.": "Ton compte <strong>{username}</strong> est créé. Tu peux maintenant te connecter avec ton nom d'utilisateur et ton mot de passe.",
    "This invitation is no longer valid": "Cette invitation n'est plus valide",
    "It has expired, was revoked, has used all its uses, or the process has ended. Ask for a new invitation.": "Elle a expiré, a été révoquée, a épuisé ses utilisations, ou la démarche a pris fin. Demande une nouvelle invitation.",
    "Settings not saved": "Réglages non enregistrés",
    "Service unavailable": "Service indisponible",
    "Service temporarily unavailable. Try again later.": "Service temporairement indisponible. Réessaie plus tard.",
    "Service temporarily unavailable. Try again in a few moments.": "Service temporairement indisponible. Réessaie dans quelques instants.",
    "Check that the folder <code>./data</code> exists and belongs to the right user:": "Vérifie que le dossier <code>./data</code> existe et appartient au bon utilisateur :",
    "Anti-bot check failed. Reload the page and try again.": "Vérification anti-robot échouée. Recharge la page et réessaie.",
    "This username or email cannot be used.": "Ce nom d'utilisateur ou ce courriel ne peut pas être utilisé.",
    "Could not send the email. Try again in a few moments.": "Impossible d'envoyer le courriel. Réessaie dans quelques instants.",
    "Could not send the email. Try again later.": "Impossible d'envoyer le courriel. Réessaie plus tard.",
    "Could not create the account. Try again in a few moments.": "Impossible de créer le compte. Réessaie dans quelques instants.",
    "Username: invalid. 3 to 32 characters, lowercase letters, digits, dot, dash or underscore.": "Nom d'utilisateur invalide : 3 à 32 caractères, lettres minuscules, chiffres, point, tiret ou tiret bas.",
    "Invalid username: 3 to 32 characters, lowercase letters, digits, dot, dash or underscore.": "Nom d'utilisateur invalide : 3 à 32 caractères, lettres minuscules, chiffres, point, tiret ou tiret bas.",
    "Invalid display name: 1 to 80 characters.": "Nom affiché invalide : 1 à 80 caractères.",
    "Invalid email address.": "Adresse courriel invalide.",
    "Invalid email address": "Adresse courriel invalide",
    "Origin not allowed.": "Origine non autorisée.",
    "Password required.": "Mot de passe requis.",
    "The two passwords do not match.": "Les deux mots de passe ne correspondent pas.",
    "Password must be at least {n} characters.": "Le mot de passe doit contenir au moins {n} caractères.",
    "Password must contain at least one uppercase letter.": "Le mot de passe doit contenir au moins une majuscule.",
    "Password must contain at least one digit.": "Le mot de passe doit contenir au moins un chiffre.",
    "Password must contain at least one special character (e.g. ! ? # -).": "Le mot de passe doit contenir au moins un caractère spécial (ex. ! ? # -).",
    "Invalid password.": "Mot de passe invalide.",
    "Could not update the password. Try again in a few moments.": "Impossible de mettre à jour le mot de passe. Réessaie dans quelques instants.",
    "Too many requests. Try again later.": "Trop de demandes. Réessaie plus tard.",
    "Too many attempts. Try again later.": "Trop de tentatives. Réessaie plus tard.",

    # ---- Mot de passe oublié (forgot / forgot_sent / reset) ----
    "Forgot your password?": "Mot de passe oublié ?",
    "Enter your email address or username and we will send you a link to reset your {app} password.": "Entre ton adresse courriel ou ton nom d'utilisateur et on t'enverra un lien pour réinitialiser ton mot de passe {app}.",
    "Send reset link": "Envoyer le lien de réinitialisation",
    "Email or username is required.": "Courriel ou nom d'utilisateur requis.",
    "Email or username is invalid.": "Courriel ou nom d'utilisateur invalide.",
    "The password reset service is temporarily unavailable.": "Le service de réinitialisation est temporairement indisponible.",
    "Check your emails": "Vérifie tes courriels",
    "If an account is linked to": "Si un compte est associé à",
    "you will receive a reset link shortly.": "tu recevras un lien de réinitialisation sous peu.",
    "The link is valid for <strong>24 hours</strong> and can only be used once.": "Le lien est valide <strong>24 heures</strong> et ne peut être utilisé qu'une seule fois.",
    "Also check your <strong>spam</strong> folder.": "Vérifie aussi ton dossier <strong>spam</strong>.",
    "Make another request": "Faire une autre demande",
    "Email sent": "Courriel envoyé",
    "New password": "Nouveau mot de passe",
    "Password changed": "Mot de passe modifié",
    "This link is no longer valid": "Ce lien n'est plus valide",
    "Confirm the password (again)": "Confirme le mot de passe",
    "Change my password": "Changer mon mot de passe",
    "At least <strong>10 characters</strong>, with an uppercase letter, a digit and a special character.": "Au moins <strong>10 caractères</strong>, avec une majuscule, un chiffre et un caractère spécial.",
    "Your password has been updated. You can now sign in with your new password.": "Ton mot de passe a été mis à jour. Tu peux maintenant te connecter avec ton nouveau mot de passe.",
    "It has expired, has already been used, or is not valid.": "Il a expiré, a déjà été utilisé ou n'est pas valide.",
    "Make a new request": "Faire une nouvelle demande",
    "Secure password reset": "Réinitialisation sécurisée",
    "Powered by {app}": "Propulsé par {app}",
    "Secure password reset powered by {app}": "Réinitialisation sécurisée propulsée par {app}",
    "Invitation powered by {app}": "Invitation propulsée par {app}",
    "Administration": "Administration",
    "Administration de {app}": "Administration de {app}",

    # ---- Courriels ----
    "[{app}] Verification code": "[{app}] Code de vérification",
    "Hello <strong style=\"color:#ffffff;\">{name}</strong>, here is your verification code for <span style=\"color:#ffffff;\">{app}</span>:": "Bonjour <strong style=\"color:#ffffff;\">{name}</strong>, voici ton code de vérification pour <span style=\"color:#ffffff;\">{app}</span> :",
    "This code is valid for <strong>10 minutes</strong>. If you did not request this account, you can ignore this email.": "Ce code est valide <strong>10 minutes</strong>. Si tu n'as pas demandé la création de ce compte, ignore ce courriel.",
    "Hello {name},\n\nYour {app} verification code is: {code}\n\nIt is valid for 10 minutes.\n\nIf you did not request an account, you can ignore this email.": "Salut {name},\n\nTon code de vérification {app} est : {code}\n\nIl est valide 10 minutes.\n\nSi tu n'as pas demandé de compte, ignore ce courriel.",
    "[{app}] Reset your password": "[{app}] Réinitialisation de ton mot de passe",
    "Password reset": "Réinitialisation de mot de passe",
    "Hello <strong style=\"color:#ffffff;\">{name}</strong>, you asked to reset your {app} password. Click the button below:": "Salut <strong style=\"color:#ffffff;\">{name}</strong>, tu as demandé à réinitialiser ton mot de passe {app}. Clique sur le bouton ci-dessous :",
    "Reset my password": "Réinitialiser mon mot de passe",
    "This link is valid for <strong>24 hours</strong> and can only be used once. If you did not make this request, you can ignore this email.": "Ce lien est valide <strong>24 heures</strong> et ne peut être utilisé qu'une seule fois. Si tu n'as pas fait cette demande, ignore ce courriel.",
    "If the button does not work, copy this link:": "Si le bouton ne fonctionne pas, copie ce lien :",
    "Hello {name},\n\nReset your {app} password by clicking this link:\n{url}\n\nThis link is valid for 24 hours and can only be used once.\n\nIf you did not make this request, you can ignore this email.": "Salut {name},\n\nRéinitialise ton mot de passe {app} en cliquant sur ce lien :\n{url}\n\nCe lien est valide 24 heures et ne peut être utilisé qu'une seule fois.\n\nSi tu n'as pas fait cette demande, ignore ce courriel.",
    "[{app}] Reset your password (email)": "[{app}] Réinitialisation de ton mot de passe",
    "[{app}] SMTP configuration test": "[{app}] Test de configuration SMTP",
    "This is a test email sent from the configuration page of {app}.\n\nIf you receive this message, the SMTP settings are correct.": "Ceci est un courriel de test envoyé depuis la page de configuration de {app}.\n\nSi tu reçois ce message, les réglages SMTP sont bons.",

    # ---- Diagnostic SMTP ----
    "SMTP is not configured (see Configuration).": "SMTP non configuré (voir la configuration).",
    "Authentication refused without encryption: choose STARTTLS or SSL.": "Authentification refusée sans chiffrement : choisis STARTTLS ou SSL.",
    "Temporary authentication failure on the server side: try again, and check that the account is not locked.": "Échec d'authentification temporaire côté serveur : réessaie, et vérifie que le compte n'est pas verrouillé.",
    "The server requires authentication before sending: fill in the SMTP user and password.": "Le serveur exige une authentification avant l'envoi : renseigne l'utilisateur et le mot de passe SMTP.",
    "The server refuses the authentication method offered: it requires an app password (or a stronger mechanism).": "Le serveur refuse la méthode d'authentification proposée : il exige un mot de passe d'application (ou un mécanisme plus fort).",
    "Credentials refused: the SMTP user or password is incorrect. Gmail, Outlook and Yahoo usually require an app password (16 characters, copied without spaces), not the account password.": "Identifiants refusés : l'utilisateur ou le mot de passe SMTP est incorrect. Gmail, Outlook et Yahoo demandent en général un mot de passe d'application (16 caractères, à recopier sans espaces) et non le mot de passe du compte.",
    "The server refused the encrypted credentials: enable STARTTLS (port 587) or SSL (port 465).": "Le serveur a refusé les identifiants chiffrés : active STARTTLS (port 587) ou SSL (port 465).",
    "The server refuses the sender address: it must belong to the domain of the SMTP account.": "Le serveur refuse l'adresse d'expédition : elle doit appartenir au domaine du compte SMTP.",
    "Encrypted connection refused: check the chosen security (STARTTLS on port 587, SSL on 465). Choosing SSL on a plain port causes exactly this message.": "Connexion chiffrée refusée : vérifie la sécurité choisie (STARTTLS sur le port 587, SSL sur 465). Choisir SSL sur un port en clair provoque exactement ce message.",
    "The server does not offer STARTTLS: switch security to SSL (port 465), or to none if it is a local relay.": "Le serveur ne propose pas STARTTLS : passe la sécurité à SSL (port 465), ou à aucune si c'est un relais local.",
    "The server does not advertise authentication (AUTH): leave the SMTP user empty, or check that the security matches the port (STARTTLS 587, SSL 465).": "Le serveur n'annonce pas l'authentification (AUTH) : laisse l'utilisateur SMTP vide, ou vérifie que la sécurité choisie correspond au port (STARTTLS 587, SSL 465).",
    "The server does not support the requested feature: check the chosen security (STARTTLS 587, SSL 465).": "Le serveur ne propose pas la fonctionnalité demandée : vérifie la sécurité choisie (STARTTLS 587, SSL 465).",
    "The server closed the connection: the port or security (STARTTLS/SSL) probably does not match.": "Le serveur a coupé la connexion : le port ou la sécurité (STARTTLS/SSL) ne correspond probablement pas.",
    "Connection refused: check the SMTP host and port, and the firewall.": "Connexion refusée : vérifie l'hôte et le port SMTP, ainsi que le pare-feu.",
    "The server refuses the sender address: use an address from the domain of the SMTP account.": "Le serveur refuse l'adresse d'expédition : utilise une adresse du domaine du compte SMTP.",
    "The server refuses the recipient address.": "Le serveur refuse l'adresse du destinataire.",
    "The server rejected the EHLO greeting: check the SMTP host.": "Le serveur a refusé la salutation EHLO : vérifie l'hôte SMTP.",
    "The server rejected the message content.": "Le serveur a rejeté le contenu du message.",
    "SMTP failure: check the host, port, security and credentials.": "Échec SMTP : vérifie l'hôte, le port, la sécurité et les identifiants.",
    "The server certificate could not be verified: the host name does not match the certificate presented.": "Le certificat du serveur n'a pas pu être vérifié : le nom d'hôte ne correspond pas au certificat présenté.",
    "SMTP host name not found: check the SMTP host (DNS name as seen from the container).": "Nom d'hôte SMTP introuvable : vérifie l'hôte SMTP (nom DNS vu depuis le conteneur).",
    "Connection refused: nothing is listening on this host and port.": "Connexion refusée : personne n'écoute sur cet hôte et ce port.",
    "Timeout: the SMTP host may not resolve from the container, or the port is filtered by a firewall.": "Délai d'attente dépassé : le nom d'hôte SMTP n'est peut-être pas résolvable depuis le conteneur, ou le port est filtré par un pare-feu.",
    "Network error: check the host, port and firewall.": "Erreur réseau : vérifie l'hôte, le port et le pare-feu.",
    "server response (code {code}): \"{msg}\"": "réponse du serveur (code {code}) : « {msg} »",
    "server response: \"{msg}\"": "réponse du serveur : « {msg} »",
    "server code: {code}": "code du serveur : {code}",
    "Also check that the password has no extra space or line break (copy and paste).": "Vérifie aussi que le mot de passe ne contient pas d'espace ni de saut de ligne en trop (copier-coller).",
    "STARTTLS (port 587)": "STARTTLS (port 587)",
    "SSL/TLS direct (port 465)": "SSL/TLS direct (port 465)",
    "None (local network only)": "Aucune (réseau local seulement)",
    "Host": "Hôte",
    "Security": "Sécurité",
    "User": "Utilisateur",
    "Sender": "Expéditeur",
    "(empty — no authentication attempted)": "(vide — aucune authentification tentée)",
    "(empty — the user is used as sender)": "(vide — l'utilisateur sert d'expéditeur)",
    "set": "défini",
    "Send failed ({type}). {detail}": "Envoi impossible ({type}). {detail}",
    "Test email sent to {to}.": "Courriel de test envoyé à {to}.",
    "SMTP settings used for this test (the ones actually applied, not necessarily the form above):": "Réglages SMTP utilisés pour ce test (ce sont ceux qui ont été appliqués, pas forcément ceux du formulaire ci-dessous) :",
    "The full settings (host, port, security, user, password) are in the container logs; no secret is written there.": "Le détail complet des réglages (hôte, port, sécurité, utilisateur, mot de passe) est repris dans les journaux du conteneur ; aucun secret n'y est écrit.",

    # ---- Réglages : validation ----
    "Invalid numeric value: {field}.": "Valeur numérique invalide : {field}.",
    "Value out of range: {field}.": "Valeur hors limites : {field}.",
    "Invalid account name: {field}.": "Identifiant de compte invalide : {field}.",
    "Invalid Turnstile site key (letters, digits, - and _).": "Clé de site Turnstile invalide (lettres, chiffres, - et _).",
    "Invalid Turnstile secret key.": "Clé secrète Turnstile invalide.",
    "Invalid admin username: 3 to 32 characters.": "Nom d'utilisateur admin invalide : 3 à 32 caractères.",
    "Invalid public URL: e.g. https://auth.example.com": "URL publique invalide : ex. https://auth.example.com",
    "Invalid LDAP URL: e.g. ldap://lldap:3890": "URL LDAP invalide : ex. ldap://lldap:3890",
    "Invalid GraphQL URL: e.g. http://lldap:17170": "URL GraphQL invalide : ex. http://lldap:17170",
    "Invalid sign-in page: e.g. https://auth.example.com": "Page de connexion invalide : ex. https://auth.example.com",
    "Invalid proxy network: {part}": "Réseau de proxy invalide : {part}",
    "Invalid language: {lang}": "Langue invalide : {lang}",
    "Roles: a role needs a display name and an LLDAP group.": "Un rôle doit avoir un nom visuel et un groupe LLDAP.",
    "A role needs a display name and an LLDAP group.": "Un rôle doit avoir un nom visuel et un groupe LLDAP.",
    "Display name invalid: 1 to {n} characters.": "Nom visuel invalide : 1 à {n} caractères.",
    "LLDAP group name invalid: 1 to {n} characters.": "Nom de groupe LLDAP invalide : 1 à {n} caractères.",
    "{n} roles maximum.": "{n} rôles au maximum.",
    "This LLDAP group is reserved for directory administration: choose another group.": "Ce groupe LLDAP est réservé à l'administration de l'annuaire : choisis un autre groupe.",
    "This display name is already used by another role.": "Ce nom visuel est déjà utilisé par un autre rôle.",
    "Choose at least one role.": "Choisis au moins un rôle.",
    "Uses: 1 to 100. Duration: 1 to 365 days.": "Utilisations : 1 à 100. Durée : 1 à 365 jours.",
    "Invalid values.": "Valeurs invalides.",
    "Choose a language.": "Choisis une langue.",
    "Language saved.": "Langue enregistrée.",

    # ---- Journal / diagnostic données ----
    "Cannot write to the data folder ({path}). The container does not have write permission. On the host, run “sudo chown -R {uid}:{gid} ./data”, then restart the container (or adjust APP_UID/APP_GID and the “user:” line in the compose file).": "Impossible d'enregistrer dans le dossier de données ({path}). Le conteneur n'a pas les droits d'écriture. Sur l'hôte, exécute « sudo chown -R {uid}:{gid} ./data » puis redémarre le conteneur (ou ajuste APP_UID/APP_GID et la ligne « user: » du compose).",
    "{hint} [detail: {error}]": "{hint} [détail : {error}]",
}


# Fusion des traductions supplémentaires (i18n_fr.py). Les clés de FR_STRINGS priment.
for _k, _v in _FR_EXTRA.items():
    FR_STRINGS.setdefault(_k, _v)
