#test
import hashlib
import hmac
import html
import ipaddress
import json
import logging
import math
import os
import re
import secrets
import smtplib
import string
import socket
import ssl
import threading
import time
import unicodedata
import urllib.request
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from logging.handlers import RotatingFileHandler
from urllib.parse import urlencode, urlparse

os.umask(0o077)

from flask import (Flask, abort, g, make_response, redirect, render_template,
                   request, session, url_for)
from i18n import SUPPORTED_LANGS, get_lang, set_default_language, t

LOGO_URL = ""  # défini par _apply_settings (réglage « logo_url », vide = pas de logo)
ACCENT_DEFAULT = "#b10008"
ACCENT_COLOR = ACCENT_DEFAULT  # réglage « accent_color » (couleur des boutons, liens, focus)
BUTTON_BORDER_DEFAULT = "#2e2e2e"
BUTTON_BORDER_COLOR = BUTTON_BORDER_DEFAULT  # réglage « button_border_color » (contours au repos)
HEX_COLOR_RE = re.compile(r"#[0-9a-fA-F]{6}")
MAIL_TEMPLATES: dict = {}  # textes personnalisés des courriels (vide = texte par défaut)
MAIL_SUBJECT_MAX = 150
MAIL_BODY_MAX = 2000
from flask.sessions import SecureCookieSessionInterface
from flask_limiter import Limiter
from ldap3 import Server, Connection
from ldap3.utils.conv import escape_filter_chars
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)


@app.context_processor
def _inject_ui():
    """Variables communes à tous les gabarits : langue active, traduction, logo."""
    return {"_": t, "lang": get_lang(), "logo_url": LOGO_URL}


_proxy_fix = ProxyFix(app.wsgi_app, x_for=0, x_proto=1, x_host=1)


class _TrustedProxyFix:
    def __init__(self, inner, fixed):
        self._inner = inner
        self._fixed = fixed

    def __call__(self, environ, start_response):
        remote = (environ.get("REMOTE_ADDR") or "").strip()
        try:
            addr = ipaddress.ip_address(remote)
        except ValueError:
            addr = None
        if addr is not None and any(addr in net for net in TRUSTED_PROXY_NETS):
            return self._fixed(environ, start_response)
        return self._inner(environ, start_response)


app.wsgi_app = _TrustedProxyFix(app.wsgi_app, _proxy_fix)

app.config.update(
    MAX_CONTENT_LENGTH=16 * 1024,
    RATELIMIT_HEADERS_ENABLED=True,
    SESSION_COOKIE_SECURE=False,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Strict",
    PERMANENT_SESSION_LIFETIME=3600,
    SESSION_REFRESH_EACH_REQUEST=False,
)


class _RequestAwareSessionInterface(SecureCookieSessionInterface):
    """Cookie de session « Secure » selon la requête réellement reçue.

    Un réglage global ne convient pas : avec une URL publique en https, un
    accès local en HTTP (http://IP:port) recevait un cookie Secure que le
    navigateur refuse. La connexion réussissait côté serveur, mais la session
    n'était jamais conservée et la page de connexion revenait sans message.
    """

    def get_cookie_secure(self, app):
        if request.is_secure:
            return True
        return (_APP_SCHEME == "https" and bool(_APP_NETLOC)
                and (request.host or "").strip().lower() == _APP_NETLOC.lower())


app.session_interface = _RequestAwareSessionInterface()


DATA_DIR = (os.environ.get("DATA_DIR") or "/app/data").rstrip("/") or "/app/data"
SETTINGS_PATH = os.environ.get("SETTINGS_PATH") or os.path.join(DATA_DIR, "settings.json")


def _data_dir_hint() -> str:
    """Explication actionnable quand le dossier de données n'est pas inscriptible."""
    uid = os.environ.get("APP_UID", "1000")
    gid = os.environ.get("APP_GID", "1000")
    return (
        f"Impossible d'enregistrer dans le dossier de données ({DATA_DIR}). "
        "Le conteneur n'a pas les droits d'écriture. Sur l'hôte, exécute "
        f"« sudo chown -R {uid}:{gid} ./data » puis redémarre le conteneur "
        "(ou ajuste APP_UID/APP_GID et la ligne « user: » du compose)."
    )


def _data_dir_writable() -> bool:
    """Test d'écriture réel : sert au diagnostic et à /healthz."""
    probe = os.path.join(DATA_DIR, ".write-test")
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(probe, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(probe)
        return True
    except OSError:
        return False


def _load_secret_key() -> str:
    """Clé de signature des sessions.

    SECRET_KEY si fournie, sinon une clé aléatoire créée au premier démarrage
    et conservée dans le dossier de données (fichier 0600) : les sessions
    survivent aux redémarrages sans variable d'environnement.
    """
    env = (os.environ.get("SECRET_KEY") or "").strip()
    if env:
        return env
    path = os.path.join(DATA_DIR, ".secret_key")
    try:
        with open(path, encoding="utf-8") as f:
            key = f.read().strip()
        if key:
            return key
    except OSError:
        pass
    key = secrets.token_hex(32)
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(key)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except OSError as e:
        logging.getLogger("app").warning("session key not persisted: %s", e)
    return key


app.secret_key = _load_secret_key()


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or "").strip() or default


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


ENV_DEFAULTS = {
    "app_name": _env("APP_NAME", "LLDAP Portal"),
    "default_lang": _env("DEFAULT_LANG", "en").lower(),
    "logo_url": _env("APP_LOGO_URL"),
    "accent_color": _env("APP_ACCENT_COLOR", "#b10008"),
    "button_border_color": _env("APP_BUTTON_BORDER_COLOR", "#2e2e2e"),
    # Couleurs des courriels. Vide pour l'accent = même couleur que le site.
    "mail_accent_color": "",
    "mail_background_color": "#141416",
    "mail_outer_color": "#121212",
    "mail_text_color": "#ffffff",
    # Contenu des courriels. Vide = texte par défaut. Variables : {app}, {name}, {code}, {url}.
    "mail_code_subject": "",
    "mail_code_body": "",
    "mail_reset_subject": "",
    "mail_reset_body": "",
    "app_url": _env("APP_URL"),
    "invites_path": _env("INVITES_PATH", os.path.join(DATA_DIR, "invites.json")),
    "audit_log_path": _env("AUDIT_LOG_PATH", os.path.join(DATA_DIR, "audit.log")),
    "smtp_host": _env("SMTP_HOST"),
    "smtp_port": _env_int("SMTP_PORT", 587),
    "smtp_security": _env("SMTP_SECURITY",
                          "ssl" if _env_int("SMTP_PORT", 587) == 465 else "starttls"),
    "smtp_user": _env("SMTP_USER"),
    "smtp_pass": _env("SMTP_PASS"),
    "smtp_from": _env("SMTP_FROM"),
    "smtp_timeout": _env_int("SMTP_TIMEOUT", 10),
    "trusted_proxies": _env("TRUSTED_PROXIES"),
    "admin_username": _env("ADMIN_USERNAME", "admin").lower(),
    "admin_password_hash": _env("ADMIN_PASSWORD_HASH"),
    "lldap_url": _env("LLDAP_URL"),
    "lldap_base_dn": _env("LLDAP_BASE_DN"),
    "lldap_admin_username": _env("LLDAP_ADMIN_USERNAME", "admin"),
    "lldap_admin_password": _env("LLDAP_ADMIN_PASSWORD"),
    "lldap_http_url": _env("LLDAP_HTTP_URL"),
    "ldap_timeout": _env_int("LDAP_TIMEOUT", 5),
    # Optionnels : sans valeur, aucun rôle historique n'est créé (voir legacy_roles).
    "group_jellyfin": _env_int("LLDAP_GROUP_ID_JELLYFIN", 0),
    "group_silo": _env_int("LLDAP_GROUP_ID_SILO", 0),
    "roles": "",
    "reset_bind_user": _env("RESET_BIND_USER"),
    "reset_bind_password": _env("RESET_BIND_PASSWORD"),
    "reset_allowed_groups": _env("RESET_ALLOWED_GROUPS"),
    "reset_cooldown": _env_int("RESET_COOLDOWN_SECONDS", 600),
    "login_url": _env("LOGIN_URL"),
    "turnstile_site_key": _env("TURNSTILE_SITE_KEY"),
    "turnstile_secret_key": _env("TURNSTILE_SECRET_KEY"),
}

SECRET_KEYS = frozenset({"smtp_pass", "lldap_admin_password", "reset_bind_password",
                         "turnstile_secret_key"})

SMTP_DEFAULT_PORTS = {"starttls": 587, "ssl": 465, "none": 25}

SMTP_SECURITY_CHOICES = (
    ("starttls", "STARTTLS (port 587)"),
    ("ssl", "SSL/TLS direct (port 465)"),
    ("none", "None (local network only)"),
)

LANG_CHOICES = (("en", "English"), ("fr", "Français"))

_settings_lock = threading.Lock()
_settings: dict = dict(ENV_DEFAULTS)


APP_NAME = ""
APP_URL = ""
_APP_NETLOC = ""
_APP_SCHEME = ""
INVITES_PATH = ""
AUDIT_LOG_PATH = ""
SMTP_HOST = ""
SMTP_PORT = 587
SMTP_SECURITY = "starttls"
SMTP_USER = ""
SMTP_PASS = ""
SMTP_FROM = ""
SMTP_TIMEOUT = 10
TRUSTED_PROXY_NETS: list = []
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD_HASH = ""
LDAP_USE_SSL = False
LDAP_HOST = None
LDAP_PORT = 389
LDAP_BASE_DN = ""
LDAP_TIMEOUT = 5
LLDAP_HTTP_URL = ""
LLDAP_ADMIN_USERNAME = ""
LDAP_BIND_DN = ""
LDAP_BIND_PASSWORD = ""
APP_GROUPS: dict = {}
APP_ROLES: list = []
RESET_BIND_USER = ""
RESET_BIND_DN = ""
RESET_BIND_PASSWORD = ""
RESET_ALLOWED_GROUPS: list = []
RESET_COOLDOWN = 600
LOGIN_URL = ""
TURNSTILE_SITE_KEY = ""
TURNSTILE_SECRET_KEY = ""

_GROUP_CACHE: dict = {"at": 0.0, "map": {}}
_GROUP_CACHE_LOCK = threading.Lock()
_GROUP_CACHE_TTL = 300


def _cookie_secure() -> bool:
    """Cookies "Secure" seulement si l'accès public est en HTTPS.

    En HTTP local (http://IP:port, http://localhost:port) un cookie Secure
    n'est jamais renvoyé par le navigateur : la session admin ne tiendrait pas
    et la validation du code échouerait.
    """
    return _APP_SCHEME == "https"


def _coerce(key: str, value):
    """Ramène une valeur lue du fichier au bon type."""
    default = ENV_DEFAULTS[key]
    if key == "roles":
        if value is None or (isinstance(value, str) and not value.strip()):
            return ""
        return roles_value(parse_roles(value))
    if isinstance(default, int):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default
    if not isinstance(value, str):
        return default
    return value.strip()


def _parse_networks(value: str) -> list:
    """Réseaux de proxys de confiance. Les entrées invalides sont ignorées."""
    nets = []
    for part in (value or "").replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            nets.append(ipaddress.ip_network(part, strict=False))
        except ValueError:
            logging.getLogger("app").warning("proxy ignored (invalid format): %s", part)
    return nets


ADMIN_ALLOWED_NETS = _parse_networks(_env(
    "ADMIN_ALLOWED_NETS",
    "127.0.0.0/8,::1/128,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,fc00::/7"))

SERVICE_ACCOUNT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")

MAX_ROLES = 20
ROLE_LABEL_MAX = 40
ROLE_GROUP_MAX = 64
ROLE_KEY_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,31}")


def _role_key(label: str, taken: set) -> str:
    """Clé interne stable, dérivée du nom visuel (jamais montrée au visiteur).

    Elle sert de référence dans invites.json : renommer un rôle ne casse donc
    jamais les invitations déjà créées.
    """
    text = unicodedata.normalize("NFKD", label or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    base = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "role"
    base = base[:32]
    key, n = base, 2
    while key in taken:
        suffix = f"-{n}"
        key = base[:32 - len(suffix)] + suffix
        n += 1
    return key


def parse_roles(raw) -> list:
    """Rôles valides lus depuis settings.json (chaîne JSON ou liste).

    Entrée = liste de {key, label, group} : label = nom affiché, group = nom du
    groupe dans LLDAP (un nombre y est accepté et utilisé tel quel).
    """
    if isinstance(raw, str):
        try:
            raw = json.loads(raw) if raw.strip() else []
        except ValueError:
            return []
    if not isinstance(raw, list):
        return []
    out, keys, labels = [], set(), set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip()[:ROLE_LABEL_MAX]
        group = str(item.get("group") or "").strip()[:ROLE_GROUP_MAX]
        if not label or not group or label.lower() in labels:
            continue
        key = str(item.get("key") or "").strip()
        if not ROLE_KEY_RE.fullmatch(key) or key in keys:
            key = _role_key(label, keys)
        keys.add(key)
        labels.add(label.lower())
        out.append({"key": key, "label": label, "group": group})
    return out[:MAX_ROLES]


def roles_value(roles: list) -> str:
    """Sérialisation des rôles pour settings.json."""
    return json.dumps(roles, ensure_ascii=False)


def legacy_roles(cfg: dict) -> list:
    """Rôles historiques, repris de group_jellyfin / group_silo.

    Sert d'amorçage : une installation existante retrouve ses deux accès
    (modifiables et supprimables comme les autres) sans rien reconfigurer.
    """
    # Rôles d'amorçage pour les installations qui utilisaient les anciennes
    # variables LLDAP_GROUP_ID_JELLYFIN / LLDAP_GROUP_ID_SILO. Sans ces
    # variables, aucun rôle n'est créé : c'est à l'administrateur de les définir.
    out = []
    if cfg.get("group_jellyfin"):
        out.append({"key": "jellyfin", "label": "Jellyfin",
                    "group": str(cfg["group_jellyfin"])})
    if cfg.get("group_silo"):
        out.append({"key": "silo", "label": "Silo", "group": str(cfg["group_silo"])})
    return out


def resolve_roles(cfg: dict) -> list:
    """Rôles effectifs : ceux enregistrés, sinon les deux rôles historiques.

    Une liste enregistrée (même vide, si l'admin a tout supprimé) fait foi ;
    seule une configuration jamais touchée reprend Jellyfin et Silo.
    """
    raw = cfg.get("roles")
    if isinstance(raw, str):
        if not raw.strip():
            return legacy_roles(cfg)
        try:
            json.loads(raw)
        except ValueError:
            return legacy_roles(cfg)
    elif not isinstance(raw, list) or not raw:
        return legacy_roles(cfg)
    return parse_roles(raw)


def role_apps(roles: list) -> dict:
    """Table {clé: {label, group}} utilisée partout par l'application."""
    return {r["key"]: {"label": r["label"], "group": r["group"]}
            for r in roles}


def load_settings() -> dict:
    """Charge settings.json ; les clés absentes reprennent l'environnement."""
    cfg = dict(ENV_DEFAULTS)
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            stored = json.load(f)
    except FileNotFoundError:
        stored = None
    except (OSError, ValueError) as e:
        logging.getLogger("app").error("settings file unreadable (%s): %s",
                                       SETTINGS_PATH, e)
        stored = None
    if isinstance(stored, dict):
        for key in ENV_DEFAULTS:
            if key in stored:
                cfg[key] = _coerce(key, stored[key])
    return cfg


class DataDirError(RuntimeError):
    """Dossier de données absent ou non inscriptible (problème de droits)."""


def save_settings(cfg: dict):
    """Écrit le fichier de configuration (droits 0600 : il contient des secrets)."""
    tmp = SETTINGS_PATH + ".tmp"
    try:
        os.makedirs(os.path.dirname(SETTINGS_PATH) or ".", exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, SETTINGS_PATH)
    except OSError as e:
        raise DataDirError(t("{hint} [detail: {error}]", hint=_data_dir_hint(), error=e)) from e


def get_settings() -> dict:
    with _settings_lock:
        return dict(_settings)


def update_settings(new_values: dict) -> dict:
    """Fusionne, applique et enregistre la configuration."""
    with _settings_lock:
        cfg = dict(_settings)
        cfg.update(new_values)
        old_audit = AUDIT_LOG_PATH
        save_settings(cfg)
        _apply_settings(cfg)
        _settings.clear()
        _settings.update(cfg)
    if AUDIT_LOG_PATH != old_audit:
        _audit_set_file(AUDIT_LOG_PATH)
    return cfg


def _apply_settings(cfg: dict):
    """Recalcule les variables globales utilisées par l'application."""
    global APP_NAME, APP_URL, _APP_NETLOC, _APP_SCHEME, INVITES_PATH, AUDIT_LOG_PATH
    global SMTP_HOST, SMTP_PORT, SMTP_SECURITY, SMTP_USER, SMTP_PASS
    global SMTP_FROM, SMTP_TIMEOUT, LOGO_URL, ACCENT_COLOR, BUTTON_BORDER_COLOR, MAIL_TEMPLATES
    global MAIL_COLORS
    global TRUSTED_PROXY_NETS, ADMIN_USERNAME, ADMIN_PASSWORD_HASH
    global LDAP_USE_SSL, LDAP_HOST, LDAP_PORT, LDAP_BASE_DN, LDAP_TIMEOUT
    global LLDAP_HTTP_URL, LLDAP_ADMIN_USERNAME, LDAP_BIND_DN, LDAP_BIND_PASSWORD
    global APP_GROUPS, APP_ROLES
    global RESET_BIND_USER, RESET_BIND_DN, RESET_BIND_PASSWORD
    global RESET_ALLOWED_GROUPS, RESET_COOLDOWN, LOGIN_URL
    global TURNSTILE_SITE_KEY, TURNSTILE_SECRET_KEY

    APP_NAME = cfg["app_name"] or "LLDAP Portal"
    LOGO_URL = (cfg["logo_url"] or "").strip()
    ACCENT_COLOR = cfg["accent_color"] if HEX_COLOR_RE.fullmatch(cfg["accent_color"] or "") else ACCENT_DEFAULT
    BUTTON_BORDER_COLOR = (cfg["button_border_color"]
                           if HEX_COLOR_RE.fullmatch(cfg["button_border_color"] or "")
                           else BUTTON_BORDER_DEFAULT)
    _mail_bg = (cfg["mail_background_color"]
                if HEX_COLOR_RE.fullmatch(cfg["mail_background_color"] or "") else "#141416")
    MAIL_COLORS = {
        "accent": (cfg["mail_accent_color"] if HEX_COLOR_RE.fullmatch(cfg["mail_accent_color"] or "")
                   else ACCENT_COLOR),
        "background": _mail_bg,
        # Fond extérieur (autour de la carte), réglage indépendant.
        "outer": (cfg["mail_outer_color"]
                  if HEX_COLOR_RE.fullmatch(cfg["mail_outer_color"] or "") else "#121212"),
        "text": (cfg["mail_text_color"]
                 if HEX_COLOR_RE.fullmatch(cfg["mail_text_color"] or "") else "#ffffff"),
    }
    MAIL_TEMPLATES = {
        "code_subject": cfg["mail_code_subject"] or "",
        "code_body": cfg["mail_code_body"] or "",
        "reset_subject": cfg["mail_reset_subject"] or "",
        "reset_body": cfg["mail_reset_body"] or "",
    }
    set_default_language(cfg["default_lang"])
    APP_URL = (cfg["app_url"] or "").rstrip("/")
    _APP_NETLOC = urlparse(APP_URL).netloc
    _APP_SCHEME = urlparse(APP_URL).scheme
    app.config["SESSION_COOKIE_SECURE"] = _cookie_secure()
    INVITES_PATH = cfg["invites_path"] or os.path.join(DATA_DIR, "invites.json")
    AUDIT_LOG_PATH = cfg["audit_log_path"] or os.path.join(DATA_DIR, "audit.log")

    SMTP_HOST = cfg["smtp_host"]
    SMTP_PORT = cfg["smtp_port"]
    SMTP_SECURITY = cfg["smtp_security"]
    SMTP_USER = cfg["smtp_user"]
    SMTP_PASS = cfg["smtp_pass"]
    SMTP_FROM = cfg["smtp_from"]
    SMTP_TIMEOUT = cfg["smtp_timeout"]

    TRUSTED_PROXY_NETS = _parse_networks(cfg["trusted_proxies"])
    ADMIN_USERNAME = (cfg["admin_username"] or "admin").lower()
    ADMIN_PASSWORD_HASH = cfg["admin_password_hash"]

    url = urlparse(cfg["lldap_url"] or "")
    if cfg["lldap_url"] and url.scheme in ("ldap", "ldaps") and url.hostname:
        LDAP_USE_SSL = url.scheme == "ldaps"
        LDAP_HOST = url.hostname
        LDAP_PORT = url.port or (636 if LDAP_USE_SSL else 389)
    else:
        LDAP_USE_SSL, LDAP_HOST, LDAP_PORT = False, None, 389
    LDAP_BASE_DN = cfg["lldap_base_dn"]
    LDAP_TIMEOUT = cfg["ldap_timeout"]

    LLDAP_HTTP_URL = (cfg["lldap_http_url"] or "").rstrip("/")
    LLDAP_ADMIN_USERNAME = cfg["lldap_admin_username"]
    LDAP_BIND_DN = (f"uid={LLDAP_ADMIN_USERNAME},{LDAP_BASE_DN}"
                    if LLDAP_ADMIN_USERNAME and LDAP_BASE_DN else "")
    LDAP_BIND_PASSWORD = cfg["lldap_admin_password"]

    RESET_BIND_USER = (cfg["reset_bind_user"] or "").strip()
    RESET_BIND_DN = (f"uid={RESET_BIND_USER},{LDAP_BASE_DN}"
                     if RESET_BIND_USER and LDAP_BASE_DN else "")
    RESET_BIND_PASSWORD = cfg["reset_bind_password"]
    RESET_ALLOWED_GROUPS = [g.strip().lower()
                            for g in (cfg["reset_allowed_groups"] or "").split(",")
                            if g.strip()]
    RESET_COOLDOWN = cfg["reset_cooldown"]
    LOGIN_URL = (cfg["login_url"] or "").strip()
    TURNSTILE_SITE_KEY = (cfg["turnstile_site_key"] or "").strip()
    TURNSTILE_SECRET_KEY = (cfg["turnstile_secret_key"] or "").strip()

    APP_ROLES = resolve_roles(cfg)
    APP_GROUPS = role_apps(APP_ROLES)
    with _GROUP_CACHE_LOCK:
        _GROUP_CACHE["at"] = 0.0
        _GROUP_CACHE["map"] = {}


def config_status(cfg: dict = None) -> list:
    """État de la configuration : liste de (libellé, booléen)."""
    cfg = cfg or get_settings()
    return [
        ("Public URL", bool(cfg["app_url"])),
        ("Email sending (SMTP)",
         bool(cfg["smtp_host"] and cfg["smtp_from"])),
        ("LDAP directory",
         bool(cfg["lldap_url"] and cfg["lldap_base_dn"])),
        ("LLDAP API (GraphQL)",
         bool(cfg["lldap_http_url"] and cfg["lldap_admin_username"]
              and cfg["lldap_admin_password"])),
        ("Administrator password", bool(cfg["admin_password_hash"])),
        ("Invitation roles", bool(resolve_roles(cfg))),
        ("Password reset",
         bool(cfg["reset_bind_user"] and cfg["reset_bind_password"]
              and cfg["app_url"] and cfg["lldap_url"] and cfg["lldap_base_dn"])),
    ]


def roles_status(cfg: dict = None) -> list:
    """Rôles configurés (libellé, groupe LLDAP) pour la page de configuration."""
    cfg = cfg or get_settings()
    return [(r["label"], r["group"]) for r in resolve_roles(cfg)]


def data_files_status() -> list:
    """Fichiers du dossier de données : liste de (libellé, chemin, présent).

    Sert au diagnostic « je ne vois que invites.json » : le dossier de données
    contient en réalité plusieurs fichiers, et ceux dont le nom commence par un
    point (.secret_key) sont masqués par un « ls » ordinaire.
    """
    return [
        ("settings.json", SETTINGS_PATH, os.path.exists(SETTINGS_PATH)),
        ("invites.json", INVITES_PATH, os.path.exists(INVITES_PATH)),
        ("audit.log", AUDIT_LOG_PATH, os.path.exists(AUDIT_LOG_PATH)),
        (".secret_key", os.path.join(DATA_DIR, ".secret_key"),
         os.path.exists(os.path.join(DATA_DIR, ".secret_key"))),
    ]


USERNAME_RE = re.compile(r"[a-z0-9][a-z0-9._-]{2,31}")
DISPLAY_NAME_RE = re.compile(r"[^\x00-\x1f\x7f]{1,80}")
EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
INVITE_CODE_LEN = 10
INVITE_CODE_ALPHABET = string.ascii_letters + string.digits
INVITE_CODE_RE = re.compile(r"[A-Za-z0-9]{%d}" % INVITE_CODE_LEN)
SIGNUP_TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{20,128}")
INVITE_ID_RE = re.compile(r"[0-9a-f]{12}")
CODE_RE = re.compile(r"[0-9]{6}")
CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]")

SIGNUP_COOKIE = "invite_signup"
SIGNUP_TTL = 30 * 60
CODE_TTL = 10 * 60
CODE_RESEND_SECONDS = 60
CODE_MAX_ATTEMPTS = 5
MAX_CODES_PER_INVITE = 20
MAX_CODES_PER_ADDRESS_HOUR = 3
CONFLICT_MSG = "This username or email cannot be used."
MIN_PASSWORD_LEN = 10
MAX_PASSWORD_LEN = 256


def _csp(turnstile: bool) -> str:
    """Politique de contenu. Le logo n'est autorisé que depuis son origine configurée
    (réglage logo_url), calculée à chaque requête car les réglages peuvent changer."""
    img = "'self'"
    if LOGO_URL:
        parsed = urlparse(LOGO_URL)
        if parsed.scheme in ("http", "https") and parsed.netloc:
            img += f" {parsed.scheme}://{parsed.netloc}"
    extra = ("script-src https://challenges.cloudflare.com; "
             "frame-src https://challenges.cloudflare.com; ") if turnstile else ""
    return ("default-src 'none'; " + extra +
            "style-src 'self'; "
            "font-src 'self'; "
            f"img-src {img}; "
            "form-action 'self'; frame-ancestors 'none'; base-uri 'none'")


TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
TURNSTILE_SITE_KEY_RE = re.compile(r"[0-9A-Za-z_-]{8,100}")
TURNSTILE_TOKEN_MAX = 2048
TURNSTILE_ERROR = "Anti-bot check failed. Reload the page and try again."


_initial_settings = load_settings()
_apply_settings(_initial_settings)
_settings.clear()
_settings.update(_initial_settings)

audit_logger = logging.getLogger("audit")
audit_logger.setLevel(logging.INFO)
audit_logger.propagate = False

_audit_fmt = logging.Formatter("%(asctime)s [AUDIT] [%(levelname)s] %(message)s")
_audit_stream = logging.StreamHandler()
_audit_stream.setFormatter(_audit_fmt)
audit_logger.addHandler(_audit_stream)

_audit_file_handler = None


def _audit_set_file(path: str):
    """(Re)crée le gestionnaire de fichier du journal d'audit."""
    global _audit_file_handler
    old = _audit_file_handler
    handler = None
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        handler = RotatingFileHandler(
            path, maxBytes=5 * 1024 * 1024, backupCount=10, encoding="utf-8"
        )
        handler.setFormatter(_audit_fmt)
    except OSError as e:
        logging.getLogger("app").error("audit log unavailable (%s): %s", path, e)
    _audit_file_handler = handler
    if handler is not None:
        audit_logger.addHandler(handler)
    if old is not None:
        audit_logger.removeHandler(old)
        old.close()


_audit_set_file(AUDIT_LOG_PATH)


def _log_data_dir_state():
    """Trace l'état du dossier de données au démarrage (diagnostic).

    Répond directement à la question « pourquoi je ne vois que invites.json ? » :
    chaque fichier attendu est listé avec son chemin et sa présence.
    """
    logger = logging.getLogger("app")
    if _data_dir_writable():
        logger.info("data folder writable: %s", DATA_DIR)
    else:
        logger.error("data folder NOT writable: %s — %s",
                     DATA_DIR, _data_dir_hint())
    logger.info("files present in %s: %s", DATA_DIR,
                ", ".join(label for label, _p, ok in data_files_status() if ok)
                or "none")
    logger.info("expected files still missing: %s",
                ", ".join(label for label, _p, ok in data_files_status() if not ok)
                or "none")


WARNING_RESULTS = {
    "origin_rejected", "invalid_invite", "wrong_code", "locked", "failed",
    "ip_denied", "address_limited",
    "taken", "cooldown", "rate_limited", "invite_exhausted",
    "not_configured", "not_in_group", "no_valid_email", "invalid_format",
    "invalid_token", "invalid_password", "empty_input", "invalid_input",
}
ERROR_RESULTS = {"ldap_failed", "mail_failed", "rollback_failed", "error"}


def _audit_pair(key: str, value) -> str:
    """k=v. Une valeur contenant des espaces (ex. nom d'invitation) est mise entre
    guillemets, pour que la ligne reste lisible et sans ambiguïté."""
    text = CONTROL_CHARS_RE.sub("?", str(value))[:120].replace('"', "'")
    return f'{key}="{text}"' if " " in text else f"{key}={text}"


def audit(event: str, result: str, ip: str, **fields):
    """Écrit une ligne d'audit. Ne jamais y passer de secret."""
    if result in ERROR_RESULTS:
        level = logging.ERROR
    elif result in WARNING_RESULTS:
        level = logging.WARNING
    else:
        level = logging.INFO
    extra = " ".join(_audit_pair(k, v) for k, v in fields.items() if v is not None)
    audit_logger.log(level, f"{event} result={result} ip={ip} {extra}".rstrip())


def _hash(value: str) -> str:
    """SHA-256 : pour les codes d'invitation, jetons et identifiants de clés."""
    return hashlib.sha256(value.encode()).hexdigest()


def _code_hash(code: str) -> str:
    """HMAC avec la clé du serveur : un code à 6 chiffres ne peut pas être retrouvé
    par force brute si le dossier de données fuit (la clé n'y est pas copiée)."""
    return hmac.new(app.secret_key.encode(), code.encode(), hashlib.sha256).hexdigest()


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

for _p in (SETTINGS_PATH, INVITES_PATH, AUDIT_LOG_PATH):
    if os.path.exists(_p):
        try:
            os.chmod(_p, 0o600)
        except OSError:
            pass

_log_data_dir_state()


def _is_trusted_hop(addr: str) -> bool:
    """Vrai si l'adresse appartient à un proxy déclaré de confiance."""
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    return any(ip in net for net in TRUSTED_PROXY_NETS)


def get_client_ip() -> str:
    """IP réelle du client.

    Seuls les proxys de confiance (« Proxys de confiance » dans la configuration)
    peuvent annoncer l'IP du visiteur. X-Forwarded-For est lu de droite à gauche
    en sautant les proxys de confiance : le premier hôte inconnu est le client.
    """
    remote = request.remote_addr or "0.0.0.0"
    if not _is_trusted_hop(remote):
        return remote
    try:
        return str(ipaddress.ip_address((request.headers.get("CF-Connecting-IP") or "").strip()))
    except ValueError:
        pass
    hops = [h.strip() for h in (request.headers.get("X-Forwarded-For") or "").split(",")
            if h.strip()]
    for hop in reversed(hops):
        try:
            ip = ipaddress.ip_address(hop)
        except ValueError:
            break
        if not _is_trusted_hop(hop):
            return str(ip)
    return remote


limiter = Limiter(
    get_client_ip,
    app=app,
    default_limits=[],
    storage_uri="memory://",
)


def _request_hosts() -> set:
    """Hôtes légitimes pour la requête : hôte réel + URL publique."""
    hosts = set()
    host = (request.host or "").strip().lower()
    if host:
        hosts.add(host)
    if _APP_NETLOC:
        hosts.add(_APP_NETLOC.strip().lower())
    return hosts


def _is_same_origin(source: str) -> bool:
    """Origine autorisée : même hôte que la requête ou que l'URL publique.

    Le schéma n'est pas comparé : l'accès local en HTTP (http://192.168.1.10:8080
    ou http://localhost:8080) doit fonctionner comme l'accès HTTPS derrière un
    reverse proxy. Seul l'hôte compte, ce qui suffit contre le CSRF.
    """
    try:
        parsed = urlparse(source)
    except ValueError:
        return False
    netloc = (parsed.netloc or "").strip().lower()
    return bool(netloc) and netloc in _request_hosts()


def _origin_ok() -> bool:
    """Protection CSRF : si un Origin (ou Referer) est fourni, il doit
    correspondre à l'hôte de la requête. Aucun domaine n'est imposé : l'absence
    des deux en-têtes est acceptée (accès direct, clients sans Origin)."""
    source = (request.headers.get("Origin")
              or request.headers.get("Referer") or "").strip()
    if not source:
        return True
    return _is_same_origin(source)


def _admin_ip_ok() -> bool:
    """/admin seulement depuis ADMIN_ALLOWED_NETS, avec l'IP réelle du client.

    Une requête qui passe par un proxy non déclaré de confiance (en-têtes de
    transfert présents, hôte de confiance absent) n'a pas d'IP réelle fiable : refusée.
    """
    forwarded = request.headers.get("X-Forwarded-For") or request.headers.get("CF-Connecting-IP")
    if forwarded and not _is_trusted_hop(request.remote_addr or ""):
        return False
    try:
        ip = ipaddress.ip_address(get_client_ip())
    except ValueError:
        return False
    return any(ip in net for net in ADMIN_ALLOWED_NETS)


def _pw_fingerprint() -> str:
    """Empreinte du hash admin : un changement de mot de passe ferme les sessions ouvertes."""
    return _hash(ADMIN_PASSWORD_HASH or "")[:24]


def _is_admin() -> bool:
    return bool(session.get("admin")) and session.get("pw") == _pw_fingerprint()


def _open_admin_session(username: str):
    session.clear()
    session.permanent = True
    session["admin"] = True
    session["admin_user"] = username
    session["pw"] = _pw_fingerprint()


@app.before_request
def _restrict_admin():
    """Hors du réseau autorisé, /admin répond 404 : la page n'existe pas pour l'extérieur."""
    if request.path == "/admin" or request.path.startswith("/admin/"):
        if not _admin_ip_ok():
            audit("admin_access", "ip_denied", get_client_ip(), path=request.path)
            abort(404)


_invites_lock = threading.Lock()


def _read_invites() -> list:
    try:
        with open(INVITES_PATH, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return []


def _write_invites(items: list):
    tmp = INVITES_PATH + ".tmp"
    try:
        os.makedirs(os.path.dirname(INVITES_PATH) or ".", exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, INVITES_PATH)
    except OSError as e:
        raise DataDirError(t("{hint} [detail: {error}]", hint=_data_dir_hint(), error=e)) from e


def _invite_usable(inv: dict) -> bool:
    return (not inv["revoked"]
            and inv["uses_left"] > 0
            and inv["expires_at"] > time.time())


def find_invite_by_code(code: str):
    """Retourne l'invitation si le code est valide, sinon None."""
    h = _hash(code)
    with _invites_lock:
        for inv in _read_invites():
            if hmac.compare_digest(inv["code_hash"], h) and _invite_usable(inv):
                return dict(inv)
    return None


INVITE_NAME_MAX = 80


def clean_invite_name(raw) -> str:
    """Nom libre d'une invitation (aide-mémoire dans le journal). Sans guillemets
    ni caractères de contrôle, pour rester lisible dans audit.log."""
    text = CONTROL_CHARS_RE.sub(" ", str(raw or "")).replace('"', "'")
    return " ".join(text.split())[:INVITE_NAME_MAX]


def create_invite(apps: list, uses: int, days: int, name: str = ""):
    """Crée une invitation. Retourne (id, code). Le code n'est affiché qu'une fois."""
    code = "".join(secrets.choice(INVITE_CODE_ALPHABET) for _ in range(INVITE_CODE_LEN))
    inv = {
        "id": secrets.token_hex(6),
        "name": clean_invite_name(name),
        "code_hash": _hash(code),
        "apps": apps,
        "uses_total": uses,
        "uses_left": uses,
        "expires_at": time.time() + days * 86400,
        "created_at": time.time(),
        "revoked": False,
    }
    with _invites_lock:
        items = _read_invites()
        items.append(inv)
        _write_invites(items)
    return inv["id"], code


def list_invites() -> list:
    now = time.time()
    with _invites_lock:
        items = _read_invites()
    out = []
    for inv in sorted(items, key=lambda i: i["created_at"], reverse=True):
        if inv["revoked"]:
            status = "Revoked"
        elif inv["expires_at"] <= now:
            status = "Expired"
        elif inv["uses_left"] <= 0:
            status = "Used up"
        else:
            status = "Active"
        out.append({
            "id": inv["id"],
            "name": inv.get("name", ""),
            "apps": ", ".join(APP_GROUPS.get(a, {}).get("label", a) for a in inv["apps"]),
            "uses_left": inv["uses_left"],
            "uses_total": inv["uses_total"],
            "expires": time.strftime("%Y-%m-%d %H:%M", time.localtime(inv["expires_at"])),
            "status": status,
            "active": status == "active",
        })
    return out


def revoke_invite(invite_id: str) -> bool:
    with _invites_lock:
        items = _read_invites()
        for inv in items:
            if inv["id"] == invite_id:
                inv["revoked"] = True
                _write_invites(items)
                return True
    return False


def purge_inactive_invites() -> int:
    """Retire les invitations révoquées, expirées ou épuisées (les liens encore
    actifs sont conservés). Retourne le nombre d'entrées supprimées."""
    with _invites_lock:
        items = _read_invites()
        keep = [inv for inv in items if _invite_usable(inv)]
        removed = len(items) - len(keep)
        if removed:
            _write_invites(keep)
    return removed


def reserve_invite(invite_id: str) -> bool:
    """Décrémente une utilisation de façon atomique. False si plus utilisable."""
    with _invites_lock:
        items = _read_invites()
        for inv in items:
            if inv["id"] == invite_id:
                if not _invite_usable(inv):
                    return False
                inv["uses_left"] -= 1
                _write_invites(items)
                return True
    return False


def reserve_code_send(invite_id: str) -> bool:
    """Compte un envoi de code pour cette invitation. False si son plafond est atteint.

    Empêche un détenteur d'invitation d'utiliser le formulaire comme relais de courriels.
    """
    with _invites_lock:
        items = _read_invites()
        for inv in items:
            if inv["id"] == invite_id:
                if inv.get("codes_sent", 0) >= MAX_CODES_PER_INVITE:
                    return False
                inv["codes_sent"] = inv.get("codes_sent", 0) + 1
                _write_invites(items)
                return True
    return False


def release_invite(invite_id: str):
    """Rend une utilisation réservée si la création du compte a échoué."""
    with _invites_lock:
        items = _read_invites()
        for inv in items:
            if inv["id"] == invite_id:
                inv["uses_left"] += 1
                _write_invites(items)
                return


_signups: dict[str, dict] = {}
_signups_lock = threading.Lock()


def _prune_signups(now: float):
    for k in [k for k, s in _signups.items() if s["expires"] <= now]:
        del _signups[k]


_addr_lock = threading.Lock()
_addr_sends: dict[str, list] = {}
_addr_fails: dict[str, dict] = {}


def address_send_allowed(email: str) -> bool:
    """Plafond d'envois de code par adresse et par heure (indépendant de l'IP et de l'invitation)."""
    key = _hash(email.lower())
    now = time.time()
    with _addr_lock:
        times = [t for t in _addr_sends.get(key, []) if now - t < 3600]
        allowed = len(times) < MAX_CODES_PER_ADDRESS_HOUR
        if allowed:
            times.append(now)
        _addr_sends[key] = times
        return allowed


def address_locked(email: str) -> bool:
    """Vrai si cette adresse a trop échoué à la vérification du code."""
    with _addr_lock:
        rec = _addr_fails.get(_hash(email.lower()))
        return bool(rec and rec["until"] > time.time())


def record_address_failure(email: str):
    """Compte les mauvais codes par adresse : relancer une inscription ne remet pas le compteur à zéro."""
    key = _hash(email.lower())
    now = time.time()
    with _addr_lock:
        rec = _addr_fails.setdefault(key, {"fails": 0, "until": 0.0})
        if 0 < rec["until"] <= now:
            rec["fails"], rec["until"] = 0, 0.0
        rec["fails"] += 1
        if rec["fails"] >= CODE_MAX_ATTEMPTS:
            rec["fails"], rec["until"] = 0, now + CODE_TTL


def start_signup(invite: dict, username: str, display_name: str, email: str,
                 password: str, code: str) -> str:
    """Enregistre une inscription en cours.

    Le mot de passe est conservé en mémoire seulement (jamais écrit sur disque,
    jamais journalisé) : il n'est utilisé qu'après la validation du code courriel,
    pour créer le compte. L'inscription disparaît après 30 minutes.
    """
    token = secrets.token_urlsafe(32)
    now = time.time()
    with _signups_lock:
        _prune_signups(now)
        _signups[_hash(token)] = {
            "invite_id": invite["id"],
            "invite_name": invite.get("name", ""),
            "apps": list(invite["apps"]),
            "username": username,
            "display_name": display_name,
            "email": email,
            "password": password,
            "code_hash": _code_hash(code),
            "code_expires": now + CODE_TTL,
            "last_sent": now,
            "attempts": 0,
            "busy": False,
            "expires": now + SIGNUP_TTL,
        }
    return token


def get_signup(token: str):
    if not SIGNUP_TOKEN_RE.fullmatch(token or ""):
        return None
    with _signups_lock:
        s = _signups.get(_hash(token))
        if s is None or s["expires"] <= time.time():
            return None
        return dict(s)


def check_code(token: str, code: str) -> str:
    """Retourne ok, wrong, expired, locked, busy ou missing.

    "busy" signifie qu'une autre requête crée déjà le compte pour ce code :
    le compte ne doit pas être créé deux fois si l'utilisateur double-clique.
    """
    now = time.time()
    key = _hash(token)
    with _signups_lock:
        s = _signups.get(key)
        if s is None or s["expires"] <= now:
            return "missing"
        if s["busy"]:
            return "busy"
        if s["code_expires"] <= now:
            return "expired"
        s["attempts"] += 1
        if hmac.compare_digest(s["code_hash"], _code_hash(code)):
            s["busy"] = True
            return "ok"
        if s["attempts"] >= CODE_MAX_ATTEMPTS:
            del _signups[key]
            return "locked"
        return "wrong"


def set_new_code(token: str, code: str) -> int:
    """Retourne -1 si inscription absente, N > 0 si trop tôt (secondes), 0 si remplacé."""
    now = time.time()
    with _signups_lock:
        s = _signups.get(_hash(token))
        if s is None or s["expires"] <= now:
            return -1
        wait = CODE_RESEND_SECONDS - (now - s["last_sent"])
        if wait > 0:
            return math.ceil(wait)
        s["code_hash"] = _code_hash(code)
        s["code_expires"] = now + CODE_TTL
        s["last_sent"] = now
        return 0


def create_account_from_signup(s: dict, ip: str = "-") -> str:
    """Crée le compte LLDAP, définit le mot de passe et ajoute les groupes.

    Retourne "ok", "exhausted" (invitation déjà consommée) ou "failed"
    (erreur LLDAP ; le compte partiellement créé est alors supprimé et
    l'invitation recréditée).
    """
    username = s["username"]
    display_name = s.get("display_name") or username
    invite_id = s["invite_id"]

    if not reserve_invite(invite_id):
        return "exhausted"

    created = False
    try:
        _graphql(CREATE_USER, {"user": {"id": username, "email": s["email"],
                                        "displayName": display_name}})
        created = True
        set_ldap_password(f"uid={username},{LDAP_BASE_DN}", s["password"])
        for app_key in s["apps"]:
            role = APP_GROUPS.get(app_key)
            if role is None:
                audit("signup", "role_absent", ip=ip, username=username,
                      role=app_key)
                continue
            gid = group_id_for(role["group"])
            if gid in RESERVED_GROUP_IDS:
                raise LookupError("group reserved for LLDAP administration")
            _graphql(ADD_TO_GROUP, {"u": username, "g": gid})
    except Exception as e:
        if created:
            try:
                _graphql(DELETE_USER, {"u": username})
            except Exception:
                audit("signup", "rollback_failed", ip=ip, username=username)
        release_invite(invite_id)
        audit("signup", "ldap_failed", ip=ip, username=username,
              error=type(e).__name__, detail=str(e))
        return "failed"
    return "ok"


def finish_signup(token: str, success: bool):
    """Succès : l'inscription est supprimée. Échec : elle reste utilisable."""
    key = _hash(token or "")
    with _signups_lock:
        if success:
            _signups.pop(key, None)
        elif key in _signups:
            _signups[key]["busy"] = False


def _ldap_connect(bind_dn: str = None, bind_password: str = None) -> Connection:
    """Connexion liée. Par défaut : compte technique (inscriptions). La
    réinitialisation fournit son propre compte de service."""
    dn = LDAP_BIND_DN if bind_dn is None else bind_dn
    password = LDAP_BIND_PASSWORD if bind_password is None else bind_password
    if not LDAP_HOST or not LDAP_BASE_DN or not dn or not password:
        raise RuntimeError("LDAP directory not configured")
    server = Server(LDAP_HOST, port=LDAP_PORT, use_ssl=LDAP_USE_SSL,
                    connect_timeout=LDAP_TIMEOUT)
    conn = Connection(server, user=dn, password=password,
                      receive_timeout=LDAP_TIMEOUT)
    if not conn.bind():
        conn.unbind()
        raise RuntimeError("LDAP bind refused")
    return conn


def ldap_user_exists(value: str) -> bool:
    """Vrai si un compte a ce uid ou ce courriel."""
    q = escape_filter_chars(value)
    conn = _ldap_connect()
    try:
        conn.search(LDAP_BASE_DN, f"(&(objectClass=person)(|(uid={q})(mail={q})))",
                    attributes=["uid"])
        if conn.result.get("result") != 0:
            raise RuntimeError("LDAP search refused")
        return len(conn.entries) > 0
    finally:
        conn.unbind()


def set_ldap_password(user_dn: str, new_password: str,
                      bind_dn: str = None, bind_password: str = None):
    """Définit le mot de passe (opération étendue LDAP, RFC 3062)."""
    conn = _ldap_connect(bind_dn, bind_password)
    try:
        conn.extend.standard.modify_password(user_dn, None, new_password)
        if conn.result.get("result") != 0:
            raise RuntimeError(
                f"LDAP {conn.result.get('result')}: {conn.result.get('description')}"
            )
    finally:
        conn.unbind()


CREATE_USER = "mutation($user: CreateUserInput!) { createUser(user: $user) { __typename } }"
ADD_TO_GROUP = ("mutation($u: String!, $g: Int!) "
                "{ addUserToGroup(userId: $u, groupId: $g) { __typename } }")
DELETE_USER = "mutation($u: String!) { deleteUser(userId: $u) { __typename } }"
GROUPS_QUERY = "query { groups { id displayName } }"


def lldap_group_map() -> dict:
    """Groupes de l'annuaire : {nom en minuscules: identifiant}. Cache 5 min.

    Permet de désigner un rôle par le *nom* du groupe LLDAP plutôt que par un
    identifiant numérique, que personne ne connaît de tête.
    """
    now = time.time()
    with _GROUP_CACHE_LOCK:
        if _GROUP_CACHE["map"] and now - _GROUP_CACHE["at"] < _GROUP_CACHE_TTL:
            return dict(_GROUP_CACHE["map"])
    groups = (_graphql(GROUPS_QUERY, {}) or {}).get("groups") or []
    mapping = {}
    for g in groups:
        try:
            gid = int(g["id"])
        except (KeyError, TypeError, ValueError):
            continue
        name = str(g.get("displayName") or "").strip()
        if name:
            mapping[name.lower()] = gid
    with _GROUP_CACHE_LOCK:
        _GROUP_CACHE["at"] = time.time()
        _GROUP_CACHE["map"] = dict(mapping)
    return mapping


def group_id_for(reference: str):
    """Identifiant numérique du groupe LLDAP désigné par son nom (ou son id).

    Accepte aussi un identifiant numérique tapé directement. Lève LookupError
    avec un message clair si le groupe n'existe pas dans l'annuaire.
    """
    ref = (reference or "").strip()
    if not ref:
        raise LookupError("no LLDAP group is set for this role")
    if ref.isdigit():
        return int(ref)
    try:
        mapping = lldap_group_map()
    except Exception as e:
        raise LookupError(
            f"impossible de lire les groupes de l'annuaire ({type(e).__name__}) : "
            "the group must be given by its numeric ID") from e
    found = mapping.get(ref.lower())
    if found is None:
        raise LookupError(f"group \"{ref}\" does not exist in LLDAP")
    return found


def _lldap_token() -> str:
    body = json.dumps({"username": LLDAP_ADMIN_USERNAME,
                       "password": LDAP_BIND_PASSWORD}).encode()
    req = urllib.request.Request(
        f"{LLDAP_HTTP_URL}/auth/simple/login", data=body,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=LDAP_TIMEOUT) as r:
        token = json.loads(r.read().decode()).get("token")
    if not token:
        raise RuntimeError("LLDAP login refused")
    return token


def _graphql(query: str, variables: dict) -> dict:
    token = _lldap_token()
    body = json.dumps({"query": query, "variables": variables}).encode()
    req = urllib.request.Request(
        f"{LLDAP_HTTP_URL}/api/graphql", data=body,
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=LDAP_TIMEOUT) as r:
        data = json.loads(r.read().decode())
    if data.get("errors"):
        raise RuntimeError("GraphQL: " + str(data["errors"][0].get("message", "erreur")))
    return data["data"]


_SMTP_CODE_HINTS = {
    454: "Temporary authentication failure on the server side: try again, and check that the account is not locked.",
    530: "The server requires authentication before sending: fill in the SMTP user and password.",
    534: "The server refuses the authentication method offered: it requires an app password (or a stronger mechanism).",
    535: "Credentials refused: the SMTP user or password is incorrect. Gmail, Outlook and Yahoo usually require an app password (16 characters, copied without spaces), not the account password.",
    538: "The server refused the encrypted credentials: enable STARTTLS (port 587) or SSL (port 465).",
    550: "The server refuses the sender address: it must belong to the domain of the SMTP account.",
}

_SMTP_TLS_HINT = (
    "Encrypted connection refused: check the chosen security (STARTTLS on port 587, SSL on 465). Choosing SSL on a plain port causes exactly this message."
)


def _smtp_error_hint(exc: BaseException, code, lang: str = None) -> str:
    """Piste concrète à afficher pour un échec SMTP donné (ou chaîne vide)."""
    if code in _SMTP_CODE_HINTS:
        return t(_SMTP_CODE_HINTS[code], lang=lang)
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return t(_SMTP_CODE_HINTS[535], lang=lang)
    if isinstance(exc, smtplib.SMTPNotSupportedError):
        text = str(exc).lower()
        if "starttls" in text:
            return t("The server does not offer STARTTLS: switch security to SSL (port 465), or to none if it is a local relay.", lang=lang)
        if "auth" in text:
            return t("The server does not advertise authentication (AUTH): leave the SMTP user empty, or check that the security matches the port (STARTTLS 587, SSL 465).", lang=lang)
        return t("The server does not support the requested feature: check the chosen security (STARTTLS 587, SSL 465).", lang=lang)
    if isinstance(exc, smtplib.SMTPServerDisconnected):
        return t("The server closed the connection: the port or security (STARTTLS/SSL) probably does not match.", lang=lang)
    if isinstance(exc, smtplib.SMTPConnectError):
        return t("Connection refused: check the SMTP host and port, and the firewall.", lang=lang)
    if isinstance(exc, smtplib.SMTPSenderRefused):
        return t("The server refuses the sender address: use an address from the domain of the SMTP account.", lang=lang)
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        return t("The server refuses the recipient address.", lang=lang)
    if isinstance(exc, smtplib.SMTPHeloError):
        return t("The server rejected the EHLO greeting: check the SMTP host.", lang=lang)
    if isinstance(exc, smtplib.SMTPDataError):
        return t("The server rejected the message content.", lang=lang)
    if isinstance(exc, smtplib.SMTPException):
        return t("SMTP failure: check the host, port, security and credentials.", lang=lang)
    if isinstance(exc, ssl.SSLCertVerificationError):
        return t("The server certificate could not be verified: the host name does not match the certificate presented.", lang=lang)
    if isinstance(exc, ssl.SSLError):
        return t(_SMTP_TLS_HINT, lang=lang)
    if isinstance(exc, socket.gaierror):
        return t("SMTP host name not found: check the SMTP host (DNS name as seen from the container).", lang=lang)
    if isinstance(exc, ConnectionRefusedError):
        return t("Connection refused: nothing is listening on this host and port.", lang=lang)
    if isinstance(exc, TimeoutError):
        return t("Timeout: the SMTP host may not resolve from the container, or the port is filtered by a firewall.", lang=lang)
    if isinstance(exc, OSError):
        return t("Network error: check the host, port and firewall.", lang=lang)
    return ""


def _smtp_error_detail(exc: BaseException, lang: str = None) -> str:
    """Explique un échec SMTP en clair (interface Configuration et journaux).

    smtplib ne conserve que la réponse brute du serveur dans ``smtp_code`` /
    ``smtp_error`` : c'est cette réponse qu'il faut remonter. ``lang`` choisit la
    langue du texte (les journaux d'audit passent "en").
    """
    raw = getattr(exc, "smtp_error", None)
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", "replace")
    server_msg = " ".join(str(raw).split()) if raw else ""
    code = getattr(exc, "smtp_code", None)

    parts = []
    if server_msg and code:
        parts.append(t('server response (code {code}): "{msg}"', lang=lang, code=code, msg=server_msg))
    elif server_msg:
        parts.append(t('server response: "{msg}"', lang=lang, msg=server_msg))
    elif code:
        parts.append(t("server code: {code}", lang=lang, code=code))
    hint = _smtp_error_hint(exc, code, lang=lang)
    if hint:
        parts.append(hint)
        if code in (534, 535) or isinstance(exc, smtplib.SMTPAuthenticationError):
            parts.append(t("Also check that the password has no extra space or line break (copy and paste).", lang=lang))
    if not parts:
        text = " ".join(str(exc).split())
        parts.append(text or type(exc).__name__)
    return " ".join(parts)


def _smtp_send(to_email: str, msg_str: str):
    """Envoie un message. Sécurité choisie dans la configuration :
    starttls (587), ssl (465) ou none (relais local)."""
    ctx = ssl.create_default_context()
    if not SMTP_HOST:
        raise RuntimeError("SMTP not configured (see /admin/settings)")
    security = SMTP_SECURITY if SMTP_SECURITY in ("starttls", "ssl", "none") else "starttls"
    if SMTP_USER and security == "none":
        raise RuntimeError("authentication refused without encryption: choose STARTTLS or SSL")
    if security == "ssl":
        server = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=SMTP_TIMEOUT, context=ctx)
    else:
        server = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=SMTP_TIMEOUT)
    try:
        if security == "starttls":
            server.ehlo()
            server.starttls(context=ctx)
            server.ehlo()
        if SMTP_USER:
            server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(SMTP_FROM or SMTP_USER, to_email, msg_str)
    finally:
        try:
            server.quit()
        except Exception:
            server.close()


def _logo_block(safe_app: str) -> str:
    """Logo du courriel : seulement si une URL de logo est configurée."""
    if not LOGO_URL:
        return ""
    return (f'<tr><td align="center" style="padding:30px 40px 20px 40px;">'
            f'<img src="{html.escape(LOGO_URL, quote=True)}" alt="{safe_app}" width="180" '
            f'style="display:block;max-width:180px;height:auto;"></td></tr>')


def _mail_fill(template: str, **values) -> str:
    """Remplace {nom} par sa valeur. Substitution simple : une accolade inconnue reste telle quelle."""
    out = template
    for key, value in values.items():
        out = out.replace("{" + key + "}", str(value))
    return out


def _mail_html_text(template: str, **values) -> str:
    """Texte personnalisé pour le HTML : valeurs et texte échappés, retours à la ligne en <br>."""
    escaped = {k: html.escape(str(v), quote=True) for k, v in values.items()}
    body = html.escape(template, quote=False)
    for key, value in escaped.items():
        body = body.replace("{" + key + "}", value)
    return body.replace("\n", "<br>")


def send_code_email(to_email: str, display_name: str, code: str, lang: str = None):
    to_email = to_email.strip()
    if not EMAIL_RE.fullmatch(to_email) or CONTROL_CHARS_RE.search(to_email):
        raise ValueError(t("Invalid email address.", lang=lang))

    doc_lang = lang if lang in SUPPORTED_LANGS else get_lang()
    safe_name = html.escape(display_name)
    safe_app = html.escape(APP_NAME)
    safe_code = html.escape(code)
    custom_body = MAIL_TEMPLATES.get("code_body", "")
    custom_subject = MAIL_TEMPLATES.get("code_subject", "")
    title = t("Verification code", lang=doc_lang)
    if custom_body:
        greeting = _mail_html_text(custom_body, name=display_name, app=APP_NAME, code=code)
    else:
        greeting = t('Hello <strong style="color:{tcolor};">{name}</strong>, here is your verification code for <span style="color:{tcolor};">{app}</span>:',
                     lang=doc_lang, name=safe_name, app=safe_app, tcolor=MAIL_COLORS["text"])
    validity = t("This code is valid for <strong>10 minutes</strong>. If you did not request this account, you can ignore this email.", lang=doc_lang)
    c = MAIL_COLORS

    html_body = f"""<!DOCTYPE html>
<html lang="{doc_lang}">
<head><meta charset="UTF-8"><title>{title}</title></head>
<body style="margin:0;padding:0;background-color:{c['outer']};font-family:'Segoe UI',Arial,sans-serif;color:{c['text']};">
<table border="0" cellpadding="0" cellspacing="0" width="100%" style="background-color:{c['outer']};padding:40px 0;">
<tr><td align="center">
<table border="0" cellpadding="0" cellspacing="0" width="500" style="background-color:{c['background']};border:1px solid {c['accent']};border-radius:12px;">
{_logo_block(safe_app)}
<tr><td style="padding:10px 40px 30px 40px;">
<h2 style="color:{c['text']};font-size:20px;font-weight:bold;margin:0 0 15px 0;text-transform:uppercase;letter-spacing:1px;">{title}</h2>
<p style="color:{c['text']};font-size:15px;line-height:1.5;margin:0 0 20px 0;">{greeting}</p>
<p style="text-align:center;margin:0 0 20px 0;"><span style="background-color:{c['accent']};border:1px solid {c['accent']};border-radius:6px;color:{c['text']};display:inline-block;font-family:monospace,Arial,sans-serif;font-size:24px;font-weight:bold;letter-spacing:4px;padding:12px 28px;">{safe_code}</span></p>
<p style="color:#888888;font-size:13px;line-height:1.5;margin:0 0 15px 0;">{validity}</p>
</td></tr>
</table>
</td></tr>
</table>
</body>
</html>
"""
    if custom_body:
        text_body = _mail_fill(custom_body, name=display_name, app=APP_NAME, code=code)
    else:
        text_body = t("Hello {name},\n\nYour {app} verification code is: {code}\n\nIt is valid for 10 minutes.\n\nIf you did not request an account, you can ignore this email.",
                      lang=doc_lang, name=display_name, app=APP_NAME, code=code)

    msg = MIMEMultipart("alternative")
    if custom_subject:
        msg["Subject"] = _mail_fill(custom_subject, app=APP_NAME, name=display_name, code=code)
    else:
        msg["Subject"] = t("[{app}] Verification code", lang=doc_lang, app=APP_NAME)
    msg["From"] = f"{APP_NAME} <{SMTP_FROM}>"
    msg["To"] = to_email
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    _smtp_send(to_email, msg.as_string())


def send_test_email(to_email: str):
    """Courriel de test envoyé depuis la page de configuration."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = t("[{app}] SMTP configuration test", app=APP_NAME)
    msg["From"] = f"{APP_NAME} <{SMTP_FROM or SMTP_USER}>"
    msg["To"] = to_email
    msg.attach(MIMEText(
        t("This is a test email sent from the configuration page of {app}.\n\nIf you receive this message, the SMTP settings are correct.", app=APP_NAME),
        "plain", "utf-8"))
    _smtp_send(to_email, msg.as_string())


def _identity_problem(username: str, display_name: str, email: str):
    if not USERNAME_RE.fullmatch(username):
        return ("Invalid username: 3 to 32 characters, "
                "lettres minuscules, chiffres, point, tiret ou tiret bas.")
    if not DISPLAY_NAME_RE.fullmatch(display_name):
        return "Invalid display name: 1 to 80 characters."
    if (len(email) > 254 or CONTROL_CHARS_RE.search(email)
            or not EMAIL_RE.fullmatch(email)):
        return "Invalid email address."
    return None


def password_policy_problem(password: str):
    """Politique : longueur minimale, une majuscule, un chiffre et un caractère spécial."""
    if len(password) < MIN_PASSWORD_LEN:
        return f"Password must be at least {MIN_PASSWORD_LEN} characters."
    if not any(c.isupper() for c in password):
        return "Le mot de passe doit contenir au moins une majuscule."
    if not any(c.isdigit() for c in password):
        return "Le mot de passe doit contenir au moins un chiffre."
    if not any(not c.isalnum() for c in password):
        return "Password must contain at least one special character (e.g. ! ? # -)."
    return None


def _password_problem(password: str, confirm: str):
    if not password:
        return "Mot de passe requis."
    if password != confirm:
        return "Les deux mots de passe ne correspondent pas."
    policy = password_policy_problem(password)
    if policy:
        return policy
    if len(password) > MAX_PASSWORD_LEN or CONTROL_CHARS_RE.search(password):
        return "Mot de passe invalide."
    return None


def _new_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def _labels(apps: list) -> list:
    return [APP_GROUPS[a]["label"] for a in apps if a in APP_GROUPS]


def _set_signup_cookie(resp, token: str):
    resp.set_cookie(SIGNUP_COOKIE, token, max_age=SIGNUP_TTL,
                    secure=_cookie_secure(),
                    httponly=True, samesite="Strict", path="/")


def _invite_page(state: str, status: int = 200, **ctx):
    return make_response(render_template("invite.html", app_name=APP_NAME,
                                         state=state, login_url=LOGIN_URL, **ctx),
                         status)


def _invalid_signup_page(status: int = 410):
    resp = _invite_page("invalid", status)
    resp.delete_cookie(SIGNUP_COOKIE, path="/")
    return resp


def _form_page(code: str, labels: list, error=None, username="", email="",
               status=200):
    """Formulaire unique : nom d'utilisateur, mot de passe et courriel.

    Le nom affiché n'est plus demandé : il reprend exactement le nom
    d'utilisateur (c'est le même identifiant partout dans l'annuaire).
    """
    return _invite_page("form", status, action=url_for("invite_flow", code=code),
                        apps=labels, error=error, username=username, email=email,
                        **turnstile_context())


def _verify_page(s: dict, error=None, info=None, status=200):
    return _invite_page("verify", status, email=s["email"], error=error, info=info)


def turnstile_enabled() -> bool:
    return bool(TURNSTILE_SITE_KEY and TURNSTILE_SECRET_KEY)


def turnstile_context() -> dict:
    """Variables de gabarit du widget ; vide si Turnstile n'est pas configuré.

    Marque aussi la réponse pour que la CSP laisse passer Cloudflare."""
    if not turnstile_enabled():
        return {}
    g.turnstile = True
    return {"turnstile_site_key": TURNSTILE_SITE_KEY}


def turnstile_ok(ip: str) -> bool:
    """Vérifie le jeton du widget auprès de Cloudflare (siteverify).

    Retourne True si Turnstile n'est pas configuré. Si Cloudflare est
    injoignable, la vérification échoue (on refuse plutôt que de laisser passer).
    """
    if not turnstile_enabled():
        return True
    token = request.form.get("cf-turnstile-response", "")
    if not token or len(token) > TURNSTILE_TOKEN_MAX:
        audit("turnstile", "missing_token", ip)
        return False
    fields = {"secret": TURNSTILE_SECRET_KEY, "response": token}
    try:
        ipaddress.ip_address(ip)
        fields["remoteip"] = ip
    except ValueError:
        pass
    req = urllib.request.Request(
        TURNSTILE_VERIFY_URL, data=urlencode(fields).encode(), method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            result = json.loads(r.read(65536).decode("utf-8"))
    except Exception as e:
        audit("turnstile", "unreachable", ip, error=type(e).__name__)
        return False
    if result.get("success") is True:
        return True
    codes = ",".join(str(c) for c in (result.get("error-codes") or [])[:5])
    audit("turnstile", "rejected", ip, codes=codes)
    return False


MAX_IDENTIFIER_LEN = 254
RESET_TOKEN_RE = re.compile(r"[a-zA-Z0-9_-]{8,128}")
RESET_TTL_SECONDS = 24 * 3600
RESET_PUBLIC_ERROR = "The password reset service is temporarily unavailable."

_reset_cooldowns: dict[str, float] = {}
_reset_cooldowns_lock = threading.Lock()


def reserve_reset_slot(identifier: str) -> int:
    """0 si la demande est permise (et enregistrée), sinon le nombre de secondes à attendre."""
    now = time.monotonic()
    key = _hash(identifier)
    with _reset_cooldowns_lock:
        for k in [k for k, t in _reset_cooldowns.items() if now - t >= RESET_COOLDOWN]:
            del _reset_cooldowns[k]
        last = _reset_cooldowns.get(key)
        if last is not None:
            return max(1, math.ceil(RESET_COOLDOWN - (now - last)))
        _reset_cooldowns[key] = now
        return 0


def _ref(value: str) -> str:
    """Référence courte et non réversible pour un identifiant ou un courriel (journal)."""
    return _hash(value)[:10]


def _token_ref(token: str) -> str:
    """Référence courte et non réversible : relie les lignes d'un même lien sans
    jamais écrire le jeton dans le journal."""
    return _hash(token)[:10]


def reset_problem():
    """Raison technique pour laquelle la réinitialisation ne peut pas servir, ou None."""
    if not RESET_BIND_DN or not RESET_BIND_PASSWORD:
        return "reset service account missing"
    if not LDAP_HOST or not LDAP_BASE_DN:
        return "LDAP directory incomplete"
    if not APP_URL:
        return "public URL missing (required for reset links)"
    return None


def _first(entry, name: str) -> str:
    """Première valeur d'un attribut LDAP, ou chaîne vide."""
    try:
        value = entry[name].value
    except Exception:
        return ""
    if isinstance(value, (list, tuple)):
        value = value[0] if value else ""
    return str(value or "").strip()


def _all(entry, name: str) -> list:
    """Toutes les valeurs d'un attribut LDAP (liste vide si absent)."""
    try:
        return [str(v) for v in entry[name].values]
    except Exception:
        return []


def _cn(dn: str) -> str:
    """Nom court d'un groupe : cn=silo-users,ou=... -> silo-users."""
    return dn.split(",")[0].split("=", 1)[-1]


def find_user(query: str):
    """Compte LLDAP dont l'uid ou le courriel correspond exactement, sinon None
    (aucun compte, ou plusieurs). Lève une exception si LLDAP est injoignable."""
    q = escape_filter_chars(query)
    conn = _ldap_connect(RESET_BIND_DN, RESET_BIND_PASSWORD)
    try:
        conn.search(LDAP_BASE_DN, f"(&(objectClass=person)(|(uid={q})(mail={q})))",
                    attributes=["uid", "mail", "memberOf"])
        if conn.result.get("result") != 0:
            raise RuntimeError("LDAP search refused")
        if len(conn.entries) != 1:
            return None
        entry = conn.entries[0]
        uid = _first(entry, "uid")
        if not uid:
            return None
        return {
            "dn": entry.entry_dn,
            "uid": uid,
            "mail": _first(entry, "mail").lower(),
            "groups": [g.lower() for g in _all(entry, "memberOf")],
        }
    finally:
        conn.unbind()


def _reset_group_allowed(groups: list) -> bool:
    """Vrai si le compte est membre d'au moins un groupe autorisé (ou si aucune restriction)."""
    if not RESET_ALLOWED_GROUPS:
        return True
    names = {_cn(g).lower() for g in groups}
    return bool(names.intersection(RESET_ALLOWED_GROUPS))


_resets: dict[str, dict] = {}
_resets_lock = threading.Lock()


def create_reset_token(user_dn: str, uid: str) -> str:
    token = secrets.token_urlsafe(32)
    now = time.monotonic()
    with _resets_lock:
        for k in [k for k, v in _resets.items() if v["expires"] <= now]:
            del _resets[k]
        _resets[_hash(token)] = {"dn": user_dn, "uid": uid,
                                 "expires": now + RESET_TTL_SECONDS, "busy": False}
    return token


def is_reset_token_valid(token: str) -> bool:
    with _resets_lock:
        entry = _resets.get(_hash(token))
        return bool(entry and not entry["busy"]
                    and entry["expires"] > time.monotonic())


def begin_reset(token: str):
    """Réserve le jeton pour une modification. None si invalide, expiré ou en cours."""
    with _resets_lock:
        entry = _resets.get(_hash(token))
        if not entry or entry["busy"] or entry["expires"] <= time.monotonic():
            return None
        entry["busy"] = True
        return {"dn": entry["dn"], "uid": entry["uid"]}


def finish_reset(token: str, success: bool):
    """Succès : le jeton disparaît. Échec : il reste utilisable jusqu'à son expiration."""
    key = _hash(token)
    with _resets_lock:
        if success:
            _resets.pop(key, None)
        elif key in _resets:
            _resets[key]["busy"] = False


def send_reset_email(to_email: str, username: str, reset_url: str, lang: str = None):
    """Courriel de réinitialisation, dans le même style que le courriel de code."""
    to_email = to_email.strip()
    if not EMAIL_RE.fullmatch(to_email) or CONTROL_CHARS_RE.search(to_email):
        raise ValueError(t("Invalid email address.", lang=lang))

    doc_lang = lang if lang in SUPPORTED_LANGS else get_lang()
    safe_name = html.escape(username)
    safe_app = html.escape(APP_NAME)
    safe_url = html.escape(reset_url, quote=True)
    custom_body = MAIL_TEMPLATES.get("reset_body", "")
    custom_subject = MAIL_TEMPLATES.get("reset_subject", "")
    title = t("Password reset", lang=doc_lang)
    if custom_body:
        intro = _mail_html_text(custom_body, name=username, app=APP_NAME, url=reset_url)
    else:
        intro = t('Hello <strong style="color:{tcolor};">{name}</strong>, you asked to reset your {app} password. Click the button below:',
                  lang=doc_lang, name=safe_name, app=safe_app, tcolor=MAIL_COLORS["text"])
    button = t("Reset my password", lang=doc_lang)
    validity = t("This link is valid for <strong>24 hours</strong> and can only be used once. If you did not make this request, you can ignore this email.", lang=doc_lang)
    fallback = t("If the button does not work, copy this link:", lang=doc_lang)
    c = MAIL_COLORS

    html_body = f"""<!DOCTYPE html>
<html lang="{doc_lang}">
<head><meta charset="UTF-8"><title>{title}</title></head>
<body style="margin:0;padding:0;background-color:{c['outer']};font-family:'Segoe UI',Arial,sans-serif;color:{c['text']};">
<table border="0" cellpadding="0" cellspacing="0" width="100%" style="background-color:{c['outer']};padding:40px 0;">
<tr><td align="center">
<table border="0" cellpadding="0" cellspacing="0" width="500" style="background-color:{c['background']};border:1px solid {c['accent']};border-radius:12px;">
{_logo_block(safe_app)}
<tr><td style="padding:10px 40px 30px 40px;">
<h2 style="color:{c['text']};font-size:20px;font-weight:bold;margin:0 0 15px 0;text-transform:uppercase;letter-spacing:1px;">{title}</h2>
<p style="color:{c['text']};font-size:15px;line-height:1.5;margin:0 0 20px 0;">{intro}</p>
<p style="text-align:center;margin:0 0 20px 0;"><a href="{safe_url}" target="_blank" style="background-color:{c['accent']};border:1px solid {c['accent']};border-radius:6px;color:{c['text']};display:inline-block;font-family:Arial,sans-serif;font-size:15px;font-weight:bold;padding:12px 28px;text-decoration:none;">{button}</a></p>
<p style="color:#888888;font-size:13px;line-height:1.5;margin:0 0 15px 0;">{validity}</p>
<p style="color:#555555;font-size:11px;margin:0;word-break:break-all;">{fallback} <a href="{safe_url}" style="color:{c['accent']};">{safe_url}</a></p>
</td></tr>
</table>
</td></tr>
</table>
</body>
</html>
"""
    if custom_body:
        text_body = _mail_fill(custom_body, name=username, app=APP_NAME, url=reset_url)
    else:
        text_body = t("Hello {name},\n\nReset your {app} password by clicking this link:\n{url}\n\nThis link is valid for 24 hours and can only be used once.\n\nIf you did not make this request, you can ignore this email.",
                      lang=doc_lang, name=username, app=APP_NAME, url=reset_url)
    msg = MIMEMultipart("alternative")
    if custom_subject:
        msg["Subject"] = _mail_fill(custom_subject, app=APP_NAME, name=username)
    else:
        msg["Subject"] = t("[{app}] Reset your password", lang=doc_lang, app=APP_NAME)
    msg["From"] = f"{APP_NAME} <{SMTP_FROM or SMTP_USER}>"
    msg["To"] = to_email
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    _smtp_send(to_email, msg.as_string())


def _process_reset(query_input: str, ip: str):
    """Traitement en arrière-plan : la réponse HTTP ne révèle jamais si le compte existe."""
    try:
        user = find_user(query_input)
        if not user:
            audit("reset_request", "user_not_found", ip, identifier=_ref(query_input))
            return
        uid, email = user["uid"], user["mail"]
        if not _reset_group_allowed(user["groups"]):
            audit("reset_request", "not_in_group", ip, identifier=_ref(query_input),
                  username=uid,
                  groups=", ".join(_cn(g) for g in user["groups"]) or "aucun")
            return
        if not email or not EMAIL_RE.fullmatch(email):
            audit("reset_request", "no_valid_email", ip, identifier=_ref(query_input),
                  username=uid)
            return
        wait = reserve_reset_slot(uid)
        if wait:
            audit("reset_request", "cooldown", ip, identifier=_ref(query_input),
                  username=uid, retry_after=wait)
            return
        token = create_reset_token(user["dn"], uid)
        send_reset_email(email, uid, f"{APP_URL}/reset/{token}")
        audit("reset_request", "email_sent", ip, identifier=_ref(query_input),
              username=uid, email=_ref(email), token=_token_ref(token))
    except Exception as e:
        audit("reset_request", "error", ip, identifier=_ref(query_input),
              error=type(e).__name__)


def _forgot_page(error=None, status=200):
    return make_response(render_template(
        "forgot.html", app_name=APP_NAME, error=error, login_url=LOGIN_URL,
        **turnstile_context()), status)


def _reset_page(state: str, status: int = 200, **ctx):
    return make_response(render_template(
        "reset.html", app_name=APP_NAME, state=state, login_url=LOGIN_URL, **ctx), status)


@app.route("/password-reset", methods=["GET"])
def forgot_password():
    return _forgot_page()


@app.route("/password-reset", methods=["POST"])
@limiter.limit("5 per minute; 10 per hour; 20 per day")
def forgot_password_submit():
    ip = get_client_ip()
    if not _origin_ok():
        audit("reset_request", "origin_rejected", ip)
        return t("Origin not allowed."), 403

    if not turnstile_ok(ip):
        return _forgot_page(error=t(TURNSTILE_ERROR), status=400)

    problem = reset_problem()
    if problem:
        audit("reset_request", "not_configured", ip, detail=problem)
        return _forgot_page(error=t(RESET_PUBLIC_ERROR), status=503)

    query_input = (request.form.get("email") or "").strip().lower()
    if not query_input:
        audit("reset_request", "empty_input", ip)
        return _forgot_page(error=t("Email or username is required."), status=400)
    if len(query_input) > MAX_IDENTIFIER_LEN or CONTROL_CHARS_RE.search(query_input):
        audit("reset_request", "invalid_input", ip)
        return _forgot_page(error=t("Email or username is invalid."), status=400)

    threading.Thread(target=_process_reset, args=(query_input, ip), daemon=True).start()
    return make_response(render_template(
        "forgot_sent.html", app_name=APP_NAME, email=query_input, login_url=LOGIN_URL,
        cooldown_minutes=max(1, math.ceil(RESET_COOLDOWN / 60))))


@app.route("/reset/<token>", methods=["GET", "POST"])
@limiter.limit("20 per minute; 60 per hour")
def reset_password(token):
    ip = get_client_ip()

    if not RESET_TOKEN_RE.fullmatch(token):
        audit("reset_link", "invalid_format", ip)
        return _reset_page("invalid", 400)

    ref = _token_ref(token)

    if request.method == "GET":
        if not is_reset_token_valid(token):
            audit("reset_link", "invalid_token", ip, token=ref)
            return _reset_page("invalid", 410)
        audit("reset_link", "opened", ip, token=ref)
        return _reset_page("form", token=token)

    if not _origin_ok():
        audit("password_change", "origin_rejected", ip, token=ref)
        return t("Origin not allowed."), 403

    password = request.form.get("password", "")
    confirm = request.form.get("confirm", "")
    problem = _password_problem(password, confirm)
    if problem:
        audit("password_change", "invalid_password", ip, token=ref)
        return _reset_page("form", 400, token=token, error=problem)

    entry = begin_reset(token)
    if entry is None:
        audit("password_change", "invalid_token", ip, token=ref)
        return _reset_page("invalid", 410)

    success = False
    try:
        set_ldap_password(entry["dn"], password, RESET_BIND_DN, RESET_BIND_PASSWORD)
        success = True
        audit("password_change", "password_set", ip, token=ref, username=entry["uid"])
        return _reset_page("done")
    except Exception as e:
        audit("password_change", "ldap_failed", ip, token=ref,
              username=entry["uid"], error=type(e).__name__)
        return _reset_page(
            "form", 502, token=token,
            error=t("Could not update the password. Try again in a few moments."))
    finally:
        finish_reset(token, success)


@app.route("/invite/<code>", methods=["GET", "POST"])
@limiter.limit("30 per minute; 200 per hour")
def invite_flow(code):
    ip = get_client_ip()

    if not INVITE_CODE_RE.fullmatch(code):
        audit("invite", "invalid_invite", ip, reason="format")
        return _invite_page("invalid", 400)

    if request.method == "POST" and not _origin_ok():
        audit("invite", "origin_rejected", ip)
        return t("Origin not allowed."), 403

    inv = find_invite_by_code(code)
    if inv is None:
        audit("invite", "invalid_invite", ip)
        return _invite_page("invalid", 410)

    labels = _labels(inv["apps"])

    if request.method == "GET":
        audit("invite", "opened", ip, invite=inv["id"], name=inv.get("name") or None)
        return _form_page(code, labels)

    username = (request.form.get("username") or "").strip().lower()
    email = (request.form.get("email") or "").strip().lower()
    password = request.form.get("password", "")
    confirm = request.form.get("confirm", "")
    display_name = username

    if not turnstile_ok(ip):
        return _form_page(code, labels, error=t(TURNSTILE_ERROR), username=username,
                          email=email, status=400)

    problem = (_identity_problem(username, display_name, email)
               or _password_problem(password, confirm))
    if problem is None:
        try:
            if ldap_user_exists(username):
                problem = t(CONFLICT_MSG)
            elif ldap_user_exists(email):
                problem = t(CONFLICT_MSG)
        except Exception as e:
            audit("signup", "ldap_failed", ip, error=type(e).__name__)
            problem = t("Service temporarily unavailable. Try again in a few moments.")
    if problem is not None:
        return _form_page(code, labels, error=problem, username=username,
                          email=email, status=400)

    if (address_locked(email) or not address_send_allowed(email)
            or not reserve_code_send(inv["id"])):
        audit("signup", "address_limited", ip, invite=inv["id"])
        return _form_page(code, labels,
                          error=t("Too many code requests. Try again later."),
                          username=username, email=email, status=429)

    code_digits = _new_code()
    try:
        send_code_email(email, display_name, code_digits)
    except Exception as e:
        audit("signup", "mail_failed", ip, error=type(e).__name__,
              detail=_smtp_error_detail(e, lang="en"))
        return _form_page(code, labels,
                          error=t("Could not send the email. Try again in a few moments."),
                          username=username, email=email, status=502)

    token = start_signup(inv, username, display_name, email, password, code_digits)
    audit("signup", "code_sent", ip, username=username, invite=inv["id"],
          name=inv.get("name") or None)
    resp = _invite_page("verify", email=email)
    _set_signup_cookie(resp, token)
    return resp


@app.route("/verify", methods=["POST"])
@limiter.limit("30 per minute; 120 per hour")
def verify_code():
    ip = get_client_ip()
    if not _origin_ok():
        audit("signup", "origin_rejected", ip)
        return t("Origin not allowed."), 403

    token = request.cookies.get(SIGNUP_COOKIE, "")
    s = get_signup(token)
    if s is None:
        return _invalid_signup_page()

    digits = (request.form.get("code") or "").strip()
    if not CODE_RE.fullmatch(digits):
        return _verify_page(s, error=t("Enter the 6-digit code."), status=400)

    if address_locked(s["email"]):
        return _verify_page(s, error=t("Too many attempts. Try again later."), status=429)

    result = check_code(token, digits)
    if result == "ok":
        audit("signup", "code_ok", ip, username=s["username"])
        outcome = create_account_from_signup(s, ip)
        if outcome == "exhausted":
            finish_signup(token, True)
            audit("signup", "invite_exhausted", ip, username=s["username"],
                  invite=s["invite_id"])
            return _invalid_signup_page()
        if outcome == "failed":
            finish_signup(token, False)
            return _verify_page(
                s, status=502,
                error=t("Could not create the account. Try again in a few moments."),
            )
        finish_signup(token, True)
        audit("signup", "account_created", ip, username=s["username"],
              apps=",".join(s["apps"]), invite=s["invite_id"],
              name=s.get("invite_name") or None)
        resp = _invite_page("done", username=s["username"])
        resp.delete_cookie(SIGNUP_COOKIE, path="/")
        return resp
    if result == "busy":
        return _verify_page(s, error=t("This code is already being verified."),
                            status=409)
    if result == "wrong":
        record_address_failure(s["email"])
        audit("signup", "wrong_code", ip, username=s["username"])
        return _verify_page(s, error=t("Incorrect code."), status=400)
    if result == "expired":
        return _verify_page(s, error=t("This code has expired. Request a new one."), status=400)
    if result == "locked":
        record_address_failure(s["email"])
        audit("signup", "locked", ip, username=s["username"])
        return _invalid_signup_page()
    return _invalid_signup_page()


@app.route("/verify/resend", methods=["POST"])
@limiter.limit("10 per minute; 30 per hour")
def resend_code():
    ip = get_client_ip()
    if not _origin_ok():
        audit("signup", "origin_rejected", ip)
        return t("Origin not allowed."), 403

    token = request.cookies.get(SIGNUP_COOKIE, "")
    s = get_signup(token)
    if s is None:
        return _invalid_signup_page()

    if address_locked(s["email"]) or not address_send_allowed(s["email"]):
        return _verify_page(s, status=429,
                            error=t("Too many code requests for this address. Try again later."))
    new_code = _new_code()
    wait = set_new_code(token, new_code)
    if wait < 0:
        return _invalid_signup_page()
    if wait > 0:
        return _verify_page(
            s, status=429,
            error=f"Attends encore {wait} seconde{'s' if wait > 1 else ''} "
                  f"avant de demander un nouveau code.",
        )

    try:
        send_code_email(s["email"], s.get("display_name") or s["username"], new_code)
    except Exception as e:
        audit("signup", "mail_failed", ip, username=s["username"],
              error=type(e).__name__, detail=_smtp_error_detail(e, lang="en"))
        return _verify_page(s, status=502,
                            error=t("Could not send the email. Try again later."))
    audit("signup", "code_resent", ip, username=s["username"])
    return _verify_page(s, info=t("A new code has been sent."))


MAIL_BODY_FIELDS = ("mail_code_body", "mail_reset_body")
MAIL_SUBJECT_FIELDS = ("mail_code_subject", "mail_reset_subject")
# Textes des courriels : les retours à la ligne sont conservés, les autres caractères de contrôle non.
CONTROL_NO_NL_RE = re.compile(r"[\x00-\x09\x0b-\x1f\x7f]")

SETTINGS_TEXT_FIELDS = (
    "app_name", "app_url", "logo_url", "default_lang", "trusted_proxies", "accent_color",
    "button_border_color", "mail_accent_color", "mail_background_color", "mail_outer_color",
    "mail_text_color",
    "mail_code_subject", "mail_reset_subject",
    "smtp_host", "smtp_user", "smtp_from",
    "lldap_url", "lldap_base_dn", "lldap_admin_username", "lldap_http_url",
    "reset_bind_user", "reset_allowed_groups", "login_url",
    "turnstile_site_key",
)
SETTINGS_INT_FIELDS = {
    "smtp_port": (1, 65535), "smtp_timeout": (1, 120), "ldap_timeout": (1, 120),
    "reset_cooldown": (30, 86400),
}

ROLE_ERROR_EMPTY = "A role needs a display name and an LLDAP group."
ROLE_ERROR_LABEL = "Display name invalid: 1 to {n} characters."
ROLE_ERROR_GROUP = "LLDAP group name invalid: 1 to {n} characters."
ROLE_ERROR_TOO_MANY = "{n} roles maximum."
ROLE_ERROR_RESERVED = ("This LLDAP group is reserved for directory administration: "
                       "choose another group.")
RESERVED_GROUP_NAMES = {"1", "2", "3", "lldap_admin", "lldap_password_manager",
                        "lldap_strict_readonly"}
RESERVED_GROUP_IDS = {1, 2, 3}
ROLE_ERROR_DUPLICATE = "This display name is already used by another role."


ROLE_FIELD_LABEL = "role_label"
ROLE_FIELD_GROUP = "role_group"
ROLE_FIELD_KEY = "role_key"


def _roles_from_form(form) -> tuple:
    """Rôles saisis dans la page de configuration (retourne liste, erreur).

    Chaque ligne du formulaire fournit trois valeurs parallèles : le nom visuel,
    le nom du groupe dans LLDAP, et la clé interne (cachée) qui permet de
    renommer un rôle sans casser les invitations déjà créées.
    """
    labels = form.getlist(ROLE_FIELD_LABEL)
    groups = form.getlist(ROLE_FIELD_GROUP)
    keys = form.getlist(ROLE_FIELD_KEY)
    roles, used_keys, seen = [], set(), set()
    for i, raw_label in enumerate(labels):
        label = (raw_label or "").strip()[:ROLE_LABEL_MAX]
        group = ((groups[i] if i < len(groups) else "") or "").strip()[:ROLE_GROUP_MAX]
        key = ((keys[i] if i < len(keys) else "") or "").strip()
        if not label and not group:
            continue
        if not label or not group:
            return None, t(ROLE_ERROR_EMPTY)
        if len((raw_label or "").strip()) > ROLE_LABEL_MAX:
            return None, t(ROLE_ERROR_LABEL, n=ROLE_LABEL_MAX)
        if len(((groups[i] if i < len(groups) else "") or "").strip()) > ROLE_GROUP_MAX:
            return None, t(ROLE_ERROR_GROUP, n=ROLE_GROUP_MAX)
        if group.lower() in RESERVED_GROUP_NAMES:
            return None, t(ROLE_ERROR_RESERVED)
        if label.lower() in seen:
            return None, t(ROLE_ERROR_DUPLICATE)
        seen.add(label.lower())
        if len(roles) >= MAX_ROLES:
            return None, t(ROLE_ERROR_TOO_MANY, n=MAX_ROLES)
        if not ROLE_KEY_RE.fullmatch(key) or key in used_keys:
            key = _role_key(label, used_keys)
        used_keys.add(key)
        roles.append({"key": key, "label": label, "group": group})
    return roles, None


def _admin_dashboard(error=None, new_link=None, status=200):
    return make_response(render_template(
        "admin.html", app_name=APP_NAME, state="dashboard",
        invites=list_invites(),
        apps=[(k, v["label"]) for k, v in APP_GROUPS.items()],
        roles=list(APP_ROLES),
        error=error, new_link=new_link,
        status_items=config_status(), config_ok=all(ok for _, ok in config_status()),
        settings_saved=os.path.exists(SETTINGS_PATH),
        settings_path=SETTINGS_PATH,
    ), status)


def _admin_login_page(error=None, username="", status=200):
    return make_response(render_template(
        "admin.html", app_name=APP_NAME, state="login",
        admin_username=ADMIN_USERNAME, username=username, error=error), status)


def _admin_setup_page(error=None, username="", status=200):
    return make_response(render_template(
        "admin.html", app_name=APP_NAME, state="setup",
        username=username, error=error), status)


def _smtp_summary() -> list:
    """Réglages SMTP réellement utilisés (sans les secrets), en (libellé, valeur).

    Affiché avec le diagnostic d'échec : « mes informations sont bonnes »
    signifie souvent que la sécurité choisie ne correspond pas au port, ou que
    l'utilisateur est vide alors que le serveur exige une authentification.
    """
    labels = {"starttls": "STARTTLS", "ssl": "SSL", "none": "aucune"}
    return [
        ("Host", SMTP_HOST or "(empty)"),
        ("Port", str(SMTP_PORT)),
        ("Security", labels.get(SMTP_SECURITY, SMTP_SECURITY)),
        ("User", SMTP_USER or "(empty — no authentication attempted)"),
        ("Password", "set" if SMTP_PASS else "(empty)"),
        ("Sender", SMTP_FROM or "(empty — the user is used as sender)"),
    ]


TAB_KEYS = ("general", "smtp", "ldap", "reset", "turnstile", "roles", "admin", "diag")


def _requested_tab() -> str:
    """Onglet de la configuration à réafficher (formulaire ou lien ?tab=)."""
    tab = request.form.get("settings_tab") or request.args.get("tab") or ""
    return tab if tab in TAB_KEYS else "general"


def _admin_settings_page(cfg=None, error=None, info=None, status=200,
                         smtp_diagnostic=None):
    cfg = cfg or get_settings()
    shown = {k: ("" if k in SECRET_KEYS else v) for k, v in cfg.items()}
    return make_response(render_template(
        "admin.html", app_name=APP_NAME, state="settings",
        values=shown,
        has_secret={k: bool(cfg[k]) for k in SECRET_KEYS},
        smtp_choices=SMTP_SECURITY_CHOICES,
        status_items=config_status(cfg),
        settings_path=SETTINGS_PATH,
        data_dir=DATA_DIR,
        data_dir_writable=_data_dir_writable(),
        data_files=data_files_status(),
        smtp_diagnostic=smtp_diagnostic,
        smtp_summary=_smtp_summary() if smtp_diagnostic else None,
        roles=resolve_roles(cfg),
        max_roles=MAX_ROLES,
        turnstile_active=bool(cfg["turnstile_site_key"] and cfg["turnstile_secret_key"]),
        tab=_requested_tab(),
        error=error, info=info,
    ), status)


@app.route("/admin", methods=["GET"])
def admin_home():
    if not _is_admin():
        if not ADMIN_PASSWORD_HASH:
            return _admin_setup_page()
        return _admin_login_page()
    return _admin_dashboard()


@app.route("/admin/setup", methods=["POST"])
@limiter.limit("5 per minute; 20 per hour")
def admin_setup():
    """Premier démarrage : choix du nom d'utilisateur et du mot de passe admin."""
    ip = get_client_ip()
    if ADMIN_PASSWORD_HASH:
        return redirect(url_for("admin_home"))
    if not _origin_ok():
        audit("admin_setup", "origin_rejected", ip)
        return t("Origin not allowed."), 403

    username = (request.form.get("username") or "").strip().lower()
    password = request.form.get("password", "")
    confirm = request.form.get("confirm", "")

    problem = None
    if not USERNAME_RE.fullmatch(username):
        problem = ("Invalid username: 3 to 32 characters, "
                   "lettres minuscules, chiffres, point, tiret ou tiret bas.")
    elif password != confirm:
        problem = "Les deux mots de passe ne correspondent pas."
    elif password_policy_problem(password) is not None:
        problem = password_policy_problem(password)
    elif len(password) > MAX_PASSWORD_LEN or CONTROL_CHARS_RE.search(password):
        problem = "Mot de passe invalide."
    if problem:
        return _admin_setup_page(error=problem, username=username, status=400)

    update_settings({
        "admin_username": username,
        "admin_password_hash": generate_password_hash(password),
    })
    _open_admin_session(username)
    audit("admin_setup", "ok", ip, username=username)
    return redirect(url_for("admin_home"))


@app.route("/admin/login", methods=["POST"])
@limiter.limit("5 per minute; 20 per hour")
def admin_login():
    ip = get_client_ip()
    if not ADMIN_PASSWORD_HASH:
        return redirect(url_for("admin_home"))
    if not _origin_ok():
        audit("admin_login", "origin_rejected", ip)
        return t("Origin not allowed."), 403

    username = (request.form.get("username") or "").strip().lower()
    password = request.form.get("password", "")
    if len(password) > MAX_PASSWORD_LEN:
        audit("admin_login", "failed", ip, username=username, reason="too_long")
        return _admin_login_page(
            error="Invalid username or password.",
            username=username, status=401)
    user_ok = hmac.compare_digest(username.encode(), ADMIN_USERNAME.encode())
    try:
        pass_ok = check_password_hash(ADMIN_PASSWORD_HASH, password)
    except ValueError:
        pass_ok = False
    if not (user_ok and pass_ok):
        audit("admin_login", "failed", ip, username=username)
        return _admin_login_page(
            error="Invalid username or password.",
            username=username, status=401)
    _open_admin_session(ADMIN_USERNAME)
    audit("admin_login", "ok", ip, username=username)
    return redirect(url_for("admin_home"))


@app.route("/admin/logout", methods=["POST"])
def admin_logout():
    if not _origin_ok():
        return t("Origin not allowed."), 403
    session.clear()
    return redirect(url_for("admin_home"))


@app.route("/admin/settings", methods=["GET"])
def admin_settings():
    if not _is_admin():
        return redirect(url_for("admin_home"))
    return _admin_settings_page(info=request.args.get("info"))


@app.route("/admin/settings", methods=["POST"])
@limiter.limit("20 per hour")
def admin_save_settings():
    ip = get_client_ip()
    if not _is_admin():
        return redirect(url_for("admin_home"))
    if not _origin_ok():
        audit("settings", "origin_rejected", ip)
        return t("Origin not allowed."), 403

    cfg = get_settings()
    form = request.form

    old_security = cfg["smtp_security"]

    for key in SETTINGS_TEXT_FIELDS:
        if key in form:
            cfg[key] = CONTROL_CHARS_RE.sub(" ", form.get(key) or "").strip()

    for key, (lo, hi) in SETTINGS_INT_FIELDS.items():
        raw = (form.get(key) or "").strip()
        if raw == "":
            continue
        try:
            value = int(raw)
        except ValueError:
            return _admin_settings_page(cfg, error=t("Invalid numeric value: {field}.", field=key),
                                        status=400)
        if not lo <= value <= hi:
            return _admin_settings_page(cfg, error=t("Value out of range: {field}.", field=key),
                                        status=400)
        cfg[key] = value

    for key, default in (("accent_color", ACCENT_DEFAULT),
                         ("button_border_color", BUTTON_BORDER_DEFAULT),
                         ("mail_background_color", "#141416"),
                         ("mail_outer_color", "#121212"),
                         ("mail_text_color", "#ffffff")):
        if not cfg[key]:
            cfg[key] = default
        elif not HEX_COLOR_RE.fullmatch(cfg[key]):
            return _admin_settings_page(cfg, error=t("Invalid colour: use the form #rrggbb."),
                                        status=400)
    # Couleur d'accent des courriels : vide = même couleur que le site.
    if cfg["mail_accent_color"] and not HEX_COLOR_RE.fullmatch(cfg["mail_accent_color"]):
        return _admin_settings_page(cfg, error=t("Invalid colour: use the form #rrggbb."),
                                    status=400)

    for key in MAIL_BODY_FIELDS:
        if key in form:
            text = (form.get(key) or "").replace("\r\n", "\n").replace("\r", "\n")
            cfg[key] = CONTROL_NO_NL_RE.sub(" ", text).strip()
    for key in MAIL_SUBJECT_FIELDS:
        if len(cfg[key] or "") > MAIL_SUBJECT_MAX:
            return _admin_settings_page(cfg, error=t("Email subject too long (max {n} characters)."
                                                     , n=MAIL_SUBJECT_MAX), status=400)
    for key in MAIL_BODY_FIELDS:
        if len(cfg[key] or "") > MAIL_BODY_MAX:
            return _admin_settings_page(cfg, error=t("Email text too long (max {n} characters)."
                                                     , n=MAIL_BODY_MAX), status=400)

    security = (form.get("smtp_security") or "").strip()
    if security in {k for k, _ in SMTP_SECURITY_CHOICES}:
        cfg["smtp_security"] = security

    if "smtp_port" in form:
        raw_port = (form.get("smtp_port") or "").strip()
        if raw_port == "" or (cfg["smtp_security"] != old_security
                              and int(raw_port) == SMTP_DEFAULT_PORTS.get(old_security)):
            cfg["smtp_port"] = SMTP_DEFAULT_PORTS.get(cfg["smtp_security"], 587)

    for key in SECRET_KEYS:
        new_value = (form.get(key) or "").strip()
        if new_value:
            cfg[key] = new_value

    for key in ("reset_bind_user", "lldap_admin_username"):
        if cfg.get(key) and not SERVICE_ACCOUNT_RE.fullmatch(cfg[key]):
            return _admin_settings_page(
                cfg, error=f"Identifiant de compte invalide : {key}.", status=400)

    if cfg["turnstile_site_key"] and not TURNSTILE_SITE_KEY_RE.fullmatch(cfg["turnstile_site_key"]):
        return _admin_settings_page(
            cfg, error=t("Invalid Turnstile site key (letters, digits, - and _)."),
            status=400)
    if len(cfg["turnstile_secret_key"]) > 256:
        return _admin_settings_page(cfg, error=t("Invalid Turnstile secret key."), status=400)

    admin_user = (form.get("admin_username") or "").strip().lower()
    if admin_user:
        if not USERNAME_RE.fullmatch(admin_user):
            return _admin_settings_page(
                cfg, error=t("Invalid admin username: 3 to 32 characters."), status=400)
        cfg["admin_username"] = admin_user

    new_pass = form.get("admin_new_password", "")
    if new_pass:
        if new_pass != form.get("admin_confirm_password", ""):
            return _admin_settings_page(
                cfg, error="Les deux mots de passe ne correspondent pas.", status=400)
        policy = password_policy_problem(new_pass)
        if policy:
            return _admin_settings_page(cfg, error=policy, status=400)
        if len(new_pass) > MAX_PASSWORD_LEN or CONTROL_CHARS_RE.search(new_pass):
            return _admin_settings_page(cfg, error="Mot de passe invalide.", status=400)
        cfg["admin_password_hash"] = generate_password_hash(new_pass)

    if ROLE_FIELD_LABEL in form:
        roles, role_error = _roles_from_form(form)
        if role_error:
            return _admin_settings_page(cfg, error=role_error, status=400)
        cfg["roles"] = roles_value(roles)

    if cfg["app_url"]:
        parsed = urlparse(cfg["app_url"])
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return _admin_settings_page(
                cfg, error=t("Invalid public URL: e.g. https://auth.example.com"), status=400)
    if cfg["lldap_url"]:
        parsed = urlparse(cfg["lldap_url"])
        if parsed.scheme not in ("ldap", "ldaps") or not parsed.hostname:
            return _admin_settings_page(
                cfg, error="URL LDAP invalide : ex. ldap://lldap:3890", status=400)
    if cfg["lldap_http_url"]:
        parsed = urlparse(cfg["lldap_http_url"])
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return _admin_settings_page(
                cfg, error="URL GraphQL invalide : ex. http://lldap:17170", status=400)
    if cfg["login_url"]:
        parsed = urlparse(cfg["login_url"])
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return _admin_settings_page(
                cfg, error=t("Invalid sign-in page: e.g. https://auth.example.com"), status=400)
    for part in (cfg["trusted_proxies"] or "").replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            ipaddress.ip_network(part, strict=False)
        except ValueError:
            return _admin_settings_page(
                cfg, error=t("Invalid proxy network: {part}", part=part), status=400)

    update_settings(cfg)
    audit("settings", "saved", ip, admin=session.get("admin_user"))
    return redirect(url_for("admin_settings", info="Settings saved.",
                            tab=_requested_tab()))


@app.route("/theme.css", methods=["GET"])
def theme_css():
    """Couleurs configurables. Servi en fichier externe : la CSP interdit les styles inline."""
    r, g, b = (int(ACCENT_COLOR[i:i + 2], 16) for i in (1, 3, 5))
    hover = "#%02x%02x%02x" % tuple(int(c * 0.7) for c in (r, g, b))
    bright = "#%02x%02x%02x" % tuple(int(c + (255 - c) * 0.3) for c in (r, g, b))
    css = (":root{"
           f"--accent:{ACCENT_COLOR};--accent-hover:{hover};--accent-bright:{bright};"
           f"--accent-soft:rgba({r},{g},{b},.14);--accent-glow:rgba({r},{g},{b},.08);"
           f"--accent-glow-strong:rgba({r},{g},{b},.35);"
           f"--focus-ring:0 0 0 2px {ACCENT_COLOR};"
           f"--button-border:{BUTTON_BORDER_COLOR};"
           "}")
    resp = make_response(css)
    resp.headers["Content-Type"] = "text/css; charset=utf-8"
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.route("/admin/settings/test-email", methods=["POST"])
@limiter.limit("10 per hour")
def admin_test_email():
    ip = get_client_ip()
    if not _is_admin():
        return redirect(url_for("admin_home"))
    if not _origin_ok():
        return t("Origin not allowed."), 403

    to_email = (request.form.get("test_email") or "").strip().lower()
    if not EMAIL_RE.fullmatch(to_email) or CONTROL_CHARS_RE.search(to_email):
        return _admin_settings_page(error="Invalid email address.", status=400)
    try:
        send_test_email(to_email)
    except Exception as e:
        detail = _smtp_error_detail(e)
        audit("settings", "mail_failed", ip, error=type(e).__name__,
              detail=_smtp_error_detail(e, lang="en"))
        return _admin_settings_page(
            error=t("Sending failed ({error}). {detail}", error=type(e).__name__, detail=detail),
            smtp_diagnostic=detail,
            status=502)
    audit("settings", "test_mail_sent", ip)
    return _admin_settings_page(info=t("Test email sent to {to}.", to=to_email))


@app.route("/admin/invites", methods=["POST"])
def admin_create_invite():
    ip = get_client_ip()
    if not _is_admin():
        return redirect(url_for("admin_home"))
    if not _origin_ok():
        return t("Origin not allowed."), 403

    apps = sorted({a for a in request.form.getlist("apps") if a in APP_GROUPS})
    if not apps:
        return _admin_dashboard(error=t("Choose at least one role."), status=400)
    name = clean_invite_name(request.form.get("name"))
    try:
        uses = int(request.form.get("uses", "1"))
        days = int(request.form.get("days", "7"))
    except ValueError:
        return _admin_dashboard(error=t("Invalid values."), status=400)
    if not (1 <= uses <= 100 and 1 <= days <= 365):
        return _admin_dashboard(error=t("Uses: 1 to 100. Duration: 1 to 365 days."),
                                status=400)

    inv_id, code = create_invite(apps, uses, days, name)
    audit("invite_create", "created", ip, invite=inv_id, name=name or None,
          apps=",".join(apps), uses=uses, days=days)
    base = APP_URL or request.host_url.rstrip("/")
    return _admin_dashboard(new_link=f"{base}/invite/{code}")


@app.route("/admin/invites/purge", methods=["POST"])
def admin_purge_invites():
    ip = get_client_ip()
    if not _is_admin():
        return redirect(url_for("admin_home"))
    if not _origin_ok():
        return t("Origin not allowed."), 403
    removed = purge_inactive_invites()
    audit("invite_purge", "purged", ip, removed=removed,
          admin=session.get("admin_user"))
    return redirect(url_for("admin_home"))


@app.route("/admin/invites/<inv_id>/revoke", methods=["POST"])
def admin_revoke_invite(inv_id):
    ip = get_client_ip()
    if not _is_admin():
        return redirect(url_for("admin_home"))
    if not _origin_ok():
        return t("Origin not allowed."), 403
    if not INVITE_ID_RE.fullmatch(inv_id):
        abort(404)
    if revoke_invite(inv_id):
        audit("invite_revoke", "revoked", ip, invite=inv_id)
    return redirect(url_for("admin_home"))


@app.after_request
def security_headers(resp):
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    resp.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if request.is_secure:
        resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
    resp.headers.setdefault(
        "Content-Security-Policy",
        _csp(bool(g.get("turnstile"))))
    if request.path.startswith(("/invite/", "/verify", "/admin", "/reset/",
                                "/password-reset")):
        resp.headers["Cache-Control"] = "no-store"
    return resp


@app.errorhandler(DataDirError)
def data_dir_handler(e):
    """Problème de droits sur le dossier de données : message clair, pas un 500 nu."""
    audit("data_dir", "error", get_client_ip(), path=request.path)
    logging.getLogger("app").error("data folder: %s", e)
    admin_ctx = request.path.startswith("/admin")
    body = render_template(
        "invite.html", app_name=APP_NAME, state="invalid",
        error=str(e) if admin_ctx else t("Service temporarily unavailable. Try again later."),
        title=t("Settings not saved") if admin_ctx else t("Service unavailable"),
        show_config_hint=admin_ctx,
        uid=os.environ.get("APP_UID", "1000"), gid=os.environ.get("APP_GID", "1000"))
    resp = make_response(body, 500)
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.errorhandler(429)
def ratelimit_handler(e):
    audit("rate_limited", "rate_limited", get_client_ip(), path=request.path)
    return t("Too many attempts. Try again later."), 429


@app.route("/")
def index():
    """Compatibilité : l'ancienne application de réinitialisation servait son
    formulaire à la racine. On y redirige vers la page actuelle."""
    return redirect(url_for("forgot_password"))


@app.route("/healthz")
def healthz():
    """Sonde de santé : signale un dossier de données non inscriptible."""
    if not _data_dir_writable():
        return {"status": "error"}, 503
    return {"status": "ok"}


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000)