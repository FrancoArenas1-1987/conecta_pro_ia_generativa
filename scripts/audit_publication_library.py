"""Offline publication audit. No provider calls, generation or live state writes."""
from pathlib import Path
import argparse,json,sys,tempfile
import yaml
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'src'))
from conecta_video_ai.settings import load_settings
from conecta_video_ai.instagram_content_engine import InstagramContentEngine
from conecta_video_ai.context_loader import load_brand_context
from conecta_video_ai.service_images import read_registry,approved_paths,canonical
from conecta_video_ai.publication_checks import validate_caption,caption_digest,validate_images
import scripts.run_instagram_carousel_once as carousel


def audit(settings, campaign_manifest):
    root=Path(settings.output_root)
    assets=Path(settings.instagram_publish_assets_root)
    if not assets.is_absolute():assets=ROOT/assets
    registry=read_registry(root/'instagram/catalog/service_images.json')
    paths=approved_paths(registry,assets)
    if not paths:raise RuntimeError('No approved images available for auditing')
    config=yaml.safe_load((ROOT/'config/instagram_publication_categories.yaml').read_text(encoding='utf-8'))
    engine=InstagramContentEngine.__new__(InstagramContentEngine)
    engine.settings=settings;engine.context=load_brand_context(settings.context_path);engine.defaults=config['defaults']
    categories={canonical(c['id']):c for c in config['categories']}
    texts=[];images=[];carousels=[];campaigns=[]
    with tempfile.TemporaryDirectory() as temp:
        temp=Path(temp)
        for code,path in paths.items():
            cat=categories.get(code,{'id':code,'label':registry['services'][code].get('name',code),'variants':[]})
            for index,variant in enumerate(cat.get('variants') or [{}]):
                for objective in ['captar_clientes','captar_proveedores']:
                    copy=engine._build_copy(category=cat,variant=variant,service=cat.get('label',code),locale='Chile',format_type='feed',objective=objective,catalog={})
                    url=settings.instagram_whatsapp_provider_url if objective=='captar_proveedores' else settings.instagram_whatsapp_client_url
                    try:qc=validate_caption(copy['caption'],whatsapp_url=url)
                    except Exception as exc:qc={'passed':False,'error':str(exc)}
                    texts.append({'service':code,'variant':index,'objective':objective,'caption':copy['caption'],'qc':qc})
            for fmt,size in [('feed',(1080,1350)),('story',(1080,1920))]:
                target=temp/code/(fmt+'.jpg')
                engine._render_publish_image_variant(source_path=path,output_path=target,target_size=size)
                qc=engine._validate_ig_image(image_path=target,image_source='asset_library',format_type=fmt)
                qc['passed']=bool(qc['passed'] and qc['score']>=settings.instagram_publish_quality_min_score)
                images.append({'service':code,'format':fmt,'qc':qc})
        grouped=carousel.load_assets(assets)
        themes=[c['id'] for c in carousel.THEMES]+[carousel.RECENT_SERVICES_THEME_ID]
        for theme_id in themes:
            try:theme=carousel.choose_theme(grouped,force_theme=theme_id)
            except RuntimeError:continue
            services=carousel.choose_services(theme,grouped)
            if len(services)!=3:continue
            caption=carousel.build_caption(theme,services,whatsapp_url=settings.instagram_whatsapp_client_url)
            qc=validate_caption(caption,whatsapp_url=settings.instagram_whatsapp_client_url)
            folder=temp/'carousels'/theme_id;folder.mkdir(parents=True)
            slides=[folder/f'{i}.jpg' for i in range(5)]
            carousel.render_cover(theme,services,slides[0])
            for i,service in enumerate(services,1):carousel.render_service(service,i,slides[i])
            carousel.render_cta(theme,services,slides[-1]);validate_images(slides,size=(1080,1350))
            carousels.append({'theme':theme_id,'caption':caption,'qc':qc})
    m=json.loads(Path(campaign_manifest).read_text(encoding='utf-8-sig'))
    for item in m['entries']:
        qc=validate_caption(item['caption'],whatsapp_url=settings.instagram_whatsapp_client_url)
        if caption_digest(item['caption'])!=item.get('caption_sha256'):raise RuntimeError('Campaign caption approval hash mismatch')
        campaigns.append({'campaign':item['campaign_id'],'qc':qc})
    failed=[r for r in texts+images+carousels+campaigns if not r['qc']['passed']]
    summary={'approved_images':len(paths),'caption_variants_checked':len(texts),'image_variants_checked':len(images),'carousel_themes_checked':len(carousels),'campaign_captions_checked':len(campaigns),'failures':len(failed),'quality_gate_enabled':settings.instagram_publish_quality_gate_enabled}
    return {'summary':summary,'failures':failed,'captions':texts,'image_checks':images,'carousels':carousels,'campaigns':campaigns,'editorial_limit':'Checks cover explicit rules and media structure, not complete visual or semantic correctness.'}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--campaign-manifest',type=Path)
    parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args();s=load_settings()
    result=audit(s,args.campaign_manifest or Path(s.output_root)/'instagram/campaigns/manifest.json')
    args.report.parent.mkdir(parents=True,exist_ok=True);args.report.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result['summary']));raise SystemExit(1 if result['summary']['failures'] else 0)
