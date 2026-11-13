"""Deterministic publication checks. They do not replace editorial review."""
from __future__ import annotations
import hashlib
import re
import unicodedata
from urllib.parse import urlparse, parse_qs
from urllib.request import urlopen, Request
from pathlib import Path
from PIL import Image
from .exceptions import GenerationError
from .service_images import canonical

DISCLAIMER = 'La disponibilidad y el valor del servicio se confirman con cada profesional.'
FREE_SEARCH = 'Buscar contactos es gratis. El servicio contratado lo cobra cada profesional.'


def normalized(text):
    return ''.join(c for c in unicodedata.normalize('NFD', str(text)).lower() if unicodedata.category(c) != 'Mn')



def editorial_copy(text):
    """Correct known template spelling without guessing facts or rewriting URLs."""
    words = {"rapido":"rápido", "rapida":"rápida", "rapidos":"rápidos", "rapidas":"rápidas",
             "orientacion":"orientación", "coordinacion":"coordinación", "solucion":"solución",
             "friccion":"fricción", "revision":"revisión", "instalacion":"instalación",
             "mantencion":"mantención", "reparacion":"reparación", "climatizacion":"climatización",
             "calefaccion":"calefacción", "informacion":"información", "cuentanos":"cuéntanos",
             "escribenos":"escríbenos", "atencion":"atención", "gasfiteria":"gasfitería",
             "kinesiologia":"kinesiología", "psicologia":"psicología", "peluqueria":"peluquería",
             "asesoria":"asesoría", "traduccion":"traducción", "ingles":"inglés", "espanol":"español",
             "facil":"fácil", "tecnicos":"técnicos", "tecnico":"técnico",
             "rehabilitacion":"rehabilitación", "kinesiologos":"kinesiólogos", "segun":"según",
             "prestacion":"prestación", "guia":"guía", "turistico":"turístico", "dia":"día",
             "lavanderia":"lavandería", "tintoreria":"tintorería", "medico":"médico"}
    def fix(match):
        word=match.group(); corrected=words[word.lower()]
        return corrected.capitalize() if word[0].isupper() else corrected
    result=re.sub(r'\b(?:'+'|'.join(words)+r')\b',fix,str(text),flags=re.I)
    result=result.replace('a quien llamar', 'a quién llamar').replace('Se corto la luz', 'Se cortó la luz').replace('no enfria', 'no enfría')
    if result.endswith('?') and not result.startswith('¿'):result='¿'+result
    return result



def reviewed_template_copy(text, role):
    risky=r'confiables|verificados|certificados|en minutos|respuesta (?:rapida|inmediata|garantizada)|reduce el riesgo|agenda.*hoy'
    if re.search(risky,normalized(text)):
        return {'value':'ConectaProIA te ayuda a encontrar contactos de profesionales y servicios.',
                'proof':'Consulta las opciones disponibles según tu comuna y necesidad.',
                'cta':'Cuéntanos qué necesitas por WhatsApp.'}[role]
    return text


def phone_from_url(url):
    p=urlparse(str(url));host=(p.hostname or '').lower()
    if host=='wa.me':return re.sub(r'\D','',p.path)
    if host=='api.whatsapp.com':return re.sub(r'\D','',parse_qs(p.query).get('phone',[''])[0])
    return ''


def caption_digest(caption):
    return hashlib.sha256(caption.encode('utf-8')).hexdigest()


def validate_caption(caption, *, whatsapp_url):
    errors=[]
    if not isinstance(caption,str):raise GenerationError('Caption must be text')
    if not 40<=len(caption.strip())<=2200:errors.append('caption_length')
    prose = re.sub(r'https?://\S+', '', caption)
    if re.search(r'\ufffd|\u00c3[\u0080-\u00bf]|\u00c2[\u0080-\u00bf]|\u00e2\u0080|[A-Za-z]\?[A-Za-z]',prose):errors.append('broken_text_encoding')
    if re.search(r'\{\{.*?\}\}|\{(?:service|servicio|locale|cta|phone|whatsapp|category)\}|\b(?:TBD|undefined|None)\b|lorem ipsum',caption,re.I) or re.search(r'(?m)^\s*TODO(?:\s*:.*)?\s*$',caption):errors.append('unresolved_placeholder')
    flat=normalized(caption)
    if 'conectaproia' not in flat:errors.append('missing_brand')
    expected=phone_from_url(whatsapp_url)
    if not re.fullmatch(r'\d{8,15}',expected):errors.append('invalid_configured_whatsapp')
    urls=[u.rstrip('.,);]') for u in re.findall(r'https?://[^\s]+',caption)]
    contacts=[u for u in urls if (urlparse(u).hostname or '').lower() in {'wa.me','api.whatsapp.com'}]
    if not contacts or any(phone_from_url(u)!=expected or urlparse(u).scheme!='https' for u in contacts):errors.append('missing_or_wrong_whatsapp_link')
    if re.search(r'\b(?:todos los servicios|servicios profesionales|servicio contratado) (?:son |es )?gratis\b|100\s*%\s*garantizad|respuesta garantizada|profesionales verificados|apoyo en minutos',flat):errors.append('unsupported_free_or_guaranteed_service_claim')
    if not ('cada profesional' in flat or 'cada proveedor' in flat):errors.append('missing_service_terms')
    if errors:raise GenerationError('Publication content blocked: '+', '.join(errors))
    return {'passed':True,'characters':len(caption),'whatsapp_phone':expected}


def validate_draft_content(draft, *, whatsapp_url):
    report=validate_caption(draft.get('caption'),whatsapp_url=whatsapp_url)
    category=str(draft.get('category_id') or '').replace('-','_')
    asset=str(draft.get('asset_category_id') or '').replace('-','_')
    if category and asset and 'general' not in {category,asset} and canonical(category)!=canonical(asset):
        raise GenerationError('Publication content blocked: image_caption_category_mismatch')
    return report


def validate_images(paths, *, size=None):
    if not paths:raise GenerationError('Publication media blocked: no images')
    for name in paths:
        p=Path(name)
        if not p.is_file():raise GenerationError('Publication media blocked: image missing')
        with Image.open(p) as im:
            actual=im.size;im.verify()
        if min(actual)<540 or (size and actual!=size):raise GenerationError('Publication media blocked: invalid image dimensions')
    return {'passed':True,'images':len(paths)}


def verify_public_asset(url, *, sha256, size_bytes, content_type):
    if not url.startswith('https://'):raise GenerationError('Public asset must use HTTPS')
    digest=hashlib.sha256();total=0
    with urlopen(Request(url,headers={'Accept-Encoding':'identity'}),timeout=45) as response:
        if response.status!=200:raise GenerationError('Public asset did not return HTTP 200')
        if not response.headers.get('Content-Type','').lower().startswith(content_type):
            raise GenerationError('Public URL returned an unexpected media type')
        while chunk:=response.read(1024*1024):
            total+=len(chunk)
            if total>size_bytes:raise GenerationError('Public asset size mismatch')
            digest.update(chunk)
    if total!=size_bytes or digest.hexdigest()!=sha256:
        raise GenerationError('Public asset checksum mismatch')
    return {'passed':True,'bytes':total,'sha256':sha256}


def verify_public_video(url, *, sha256, size_bytes):
    return verify_public_asset(url, sha256=sha256, size_bytes=size_bytes, content_type='video/')


def verify_public_image(url, *, sha256, size_bytes):
    return verify_public_asset(url, sha256=sha256, size_bytes=size_bytes, content_type='image/jpeg')
