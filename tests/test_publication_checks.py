from io import BytesIO
import hashlib,json
from pathlib import Path
from types import SimpleNamespace
import pytest
from PIL import Image
from conecta_video_ai.exceptions import GenerationError
from conecta_video_ai.publication_checks import validate_caption, validate_draft_content, verify_public_video, caption_digest
from conecta_video_ai.campaign_queue import run_campaign_slot
from test_campaign_queue import make_service,NOW

GOOD='ConectaProIA: busca contactos para tu hogar. Buscar contactos es gratis. El servicio contratado lo cobra cada profesional. WhatsApp: https://wa.me/56983434503'

@pytest.mark.parametrize('caption,reason',[
 ('','caption_length'),
 (GOOD.replace('56983434503','56900000000'),'wrong_whatsapp'),
 (GOOD+' {{service}}','placeholder'),
 (GOOD+' None','placeholder'),
 (GOOD+' atenci\ufffdn','encoding'),
 (GOOD+' profesi\u00c3\u00b3n','encoding'),
 (GOOD+' servi?ios','encoding'),
 (GOOD+' Todos los servicios son gratis','free_or_guaranteed'),
 (GOOD.replace('El servicio contratado lo cobra cada profesional.',''),'service_terms'),
])
def test_bad_copy_is_blocked(caption,reason):
    with pytest.raises(GenerationError,match=reason):validate_caption(caption,whatsapp_url='https://wa.me/56983434503')


def test_valid_copy_and_category_aliases_pass():
    report=validate_draft_content({'caption':GOOD,'category_id':'legal','asset_category_id':'abogado'},whatsapp_url='https://api.whatsapp.com/send?phone=56983434503')
    assert report['passed']
    with pytest.raises(GenerationError,match='mismatch'):
        validate_draft_content({'caption':GOOD,'category_id':'electricidad','asset_category_id':'gasfiteria'},whatsapp_url='https://wa.me/56983434503')


def test_changed_campaign_caption_is_not_implicitly_approved(tmp_path):
    service,root,calls=make_service(tmp_path)
    m=json.loads((root/'manifest.json').read_text());m['entries'][0]['caption']+=' Changed after review.';(root/'manifest.json').write_text(json.dumps(m))
    with pytest.raises(RuntimeError,match='caption checksum'):run_campaign_slot(service,now=NOW)
    assert calls==[]


@pytest.mark.parametrize('data,expected,content_type',[(b'video',b'video','video/mp4'),(b'wrong',b'video','video/mp4'),(b'video',b'video','text/html')])
def test_public_bytes_are_verified_before_meta_upload(monkeypatch,data,expected,content_type):
    class Response(BytesIO):
        status=200
        headers={'Content-Type':content_type}
    monkeypatch.setattr('conecta_video_ai.publication_checks.urlopen',lambda *args,**kw:Response(data))
    if data==expected and content_type=='video/mp4':
        assert verify_public_video('https://conectaproia.cl/test.mp4',sha256=hashlib.sha256(expected).hexdigest(),size_bytes=len(expected))['passed']
    else:
        with pytest.raises(GenerationError):verify_public_video('https://conectaproia.cl/test.mp4',sha256=hashlib.sha256(expected).hexdigest(),size_bytes=len(expected))


def test_carousel_never_fills_missing_services_from_other_themes(tmp_path):
    import scripts.run_instagram_carousel_once as c
    selected=c.choose_services({'categories':['electricidad','gasfiteria']},{'electricidad':[tmp_path/'e.png'],'gasfiteria':[tmp_path/'g.png'],'medico_veterinario':[tmp_path/'v.png']})
    assert [s.category_id for s in selected]==['electricidad','gasfiteria']


def carousel_fixture(tmp_path,monkeypatch,*,fail_facebook=False):
    import scripts.run_instagram_carousel_once as c
    paths=[]
    for i in range(5):
        p=tmp_path/f'slide_{i}.png';Image.new('RGB',(1080,1350),'white').save(p);paths.append(p)
    categories=['electricidad','gasfiteria','fletes_mudanzas']
    services=[{'category_id':name,'image_path':str(paths[i+1])} for i,name in enumerate(categories)]
    manifest={'run_id':'test','slides':[str(p) for p in paths],'caption':GOOD,'assets_root':str(tmp_path),'theme':{'id':'hogar','categories':categories},'services':services}
    calls=[]
    class Publisher:
        ig_user_id='ig'
        def __init__(self,s):pass
        def inspect_page_identity(self):return {'linked_instagram_user_id':'ig'}
        def stage_local_image_for_public_url(self,**kw):calls.append('stage');return 'https://example.test/image.jpg'
        def publish_carousel_post(self,**kw):calls.append('ig');return {'post_id':'ig-published'}
        def publish_facebook_multi_photo(self,**kw):
            calls.append('fb')
            if fail_facebook:raise RuntimeError('network timeout')
            return {'post_id':'fb-published'}
    monkeypatch.setattr(c,'InstagramGraphPublisher',Publisher)
    monkeypatch.setattr(c,'load_settings',lambda:SimpleNamespace(instagram_whatsapp_client_url='https://wa.me/56983434503',instagram_crosspost_facebook=True))
    monkeypatch.setattr(c,'STATE_PATH',tmp_path/'state.json')
    monkeypatch.setattr(c,'load_assets',lambda _: {name:[paths[i+1]] for i,name in enumerate(categories)})
    return c,manifest,calls


def test_carousel_partial_publish_requires_review_without_reposting(tmp_path,monkeypatch):
    c,m,calls=carousel_fixture(tmp_path,monkeypatch,fail_facebook=True)
    with pytest.raises(RuntimeError,match='timeout'):c.publish_carousel(m)
    journal=json.loads((tmp_path/'carousel_pending.json').read_text())
    assert journal['deliveries']['instagram']['receipt']['post_id']=='ig-published'
    assert journal['deliveries']['facebook']['status']=='sending'
    assert c.should_skip(48,force=True)[0]
    with pytest.raises(RuntimeError,match='unresolved'):c.publish_carousel(m)
    assert calls.count('ig')==1


def test_carousel_bad_caption_does_not_upload_anything(tmp_path,monkeypatch):
    c,m,calls=carousel_fixture(tmp_path,monkeypatch);m['caption']=''
    with pytest.raises(GenerationError):c.publish_carousel(m)
    assert calls==[]


def test_carousel_success_saves_state_and_clears_pending(tmp_path,monkeypatch):
    c,m,calls=carousel_fixture(tmp_path,monkeypatch)
    assert c.publish_carousel(m)['ok']
    assert not (tmp_path/'carousel_pending.json').exists()
    assert json.loads((tmp_path/'state.json').read_text())['last_run_id']=='test'

def test_known_template_spelling_is_corrected_without_rewriting_meaning():
    from conecta_video_ai.publication_checks import editorial_copy
    assert editorial_copy('Necesitas revision rapida?') == '\u00bfNecesitas revisi\u00f3n r\u00e1pida?'
    assert editorial_copy('ConectaProIA') == 'ConectaProIA'

def test_whatsapp_query_string_is_not_broken_spanish():
    caption=GOOD.replace('https://wa.me/56983434503','https://api.whatsapp.com/send?phone=56983434503')
    assert validate_caption(caption,whatsapp_url='https://wa.me/56983434503')['passed']


def test_templates_do_not_invent_verification_or_delivery_times():
    from conecta_video_ai.publication_checks import reviewed_template_copy
    assert 'verificados' not in reviewed_template_copy('Profesionales verificados y respuesta rapida','proof')
    assert 'minutos' not in reviewed_template_copy('Consigue apoyo en minutos','cta')

def test_normal_publisher_blocks_bad_copy_before_loading_any_destination(tmp_path):
    from conecta_video_ai.pipelines import StudioService
    service=StudioService.__new__(StudioService)
    service.settings=SimpleNamespace(instagram_whatsapp_client_url='https://wa.me/56983434503')
    service.instagram_engine=SimpleNamespace(get_draft=lambda _:{'caption':'TODO','objective':'captar_clientes'})
    with pytest.raises(GenerationError,match='content blocked'):
        service.publish_instagram_draft(draft_id='bad-copy',simulate=False)

def test_spanish_todo_is_not_a_template_placeholder():
    assert validate_caption(GOOD+' Todo el proceso es por WhatsApp.',whatsapp_url='https://wa.me/56983434503')['passed']

def test_todo_chile_in_uppercase_is_valid_copy():
    assert validate_caption(GOOD+' Contactos en TODO CHILE.',whatsapp_url='https://wa.me/56983434503')['passed']


@pytest.mark.parametrize('content_type,data,valid',[
    ('image/jpeg',b'approved',True),
    ('image/jpeg',b'changed',False),
    ('text/html',b'approved',False),
])
def test_public_campaign_image_bytes_and_mime_are_verified(monkeypatch,content_type,data,valid):
    from conecta_video_ai.publication_checks import verify_public_image
    class Response(BytesIO):
        status=200
        headers={'Content-Type':content_type}
    monkeypatch.setattr('conecta_video_ai.publication_checks.urlopen',lambda *a,**kw:Response(data))
    kwargs={'sha256':hashlib.sha256(b'approved').hexdigest(),'size_bytes':len(b'approved')}
    if valid:assert verify_public_image('https://example.test/image.jpg',**kwargs)['passed']
    else:
        with pytest.raises(GenerationError):verify_public_image('https://example.test/image.jpg',**kwargs)
