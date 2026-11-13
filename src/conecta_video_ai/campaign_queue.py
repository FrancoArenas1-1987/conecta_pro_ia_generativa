"""Approved, pre-rendered campaigns for the existing guarded publishing runner.

Each external delivery is journaled before sending. Unknown or partial outcomes
are quarantined rather than retried automatically. No image generation here.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import uuid

from PIL import Image
from .publication_checks import validate_caption, caption_digest, verify_public_video, verify_public_image, validate_images


def utc_now():
    return datetime.now(timezone.utc)


def iso(dt):
    return dt.astimezone(timezone.utc).isoformat()


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def safe_error(exc):
    value = re.sub(r'https?://\S+', '[url]', str(exc))
    value = re.sub(r'(?i)(access_token|api_key|authorization)[\s=:]+[^\s,}]+', r'\1=[redacted]', value)
    return value[:1200]


def campaign_root(settings):
    return Path(settings.output_root) / 'instagram' / 'campaigns'


def inside(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError('Campaign asset missing or outside approved directory')
    return path


class CampaignSelectionError(RuntimeError):
    """Invalid queue configuration; ordinary image publishing may continue."""


class CampaignQueue:
    def __init__(self, root):
        self.root = Path(root)
        self.path = self.root / 'queue.sqlite3'
        self.root.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS attempts (id TEXT PRIMARY KEY, campaign TEXT, draft_id TEXT, started_at TEXT, status TEXT, finished_at TEXT, error TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS deliveries (attempt TEXT, target TEXT, channel TEXT, status TEXT, receipt TEXT, PRIMARY KEY (attempt,target,channel))')
            db.execute('CREATE TABLE IF NOT EXISTS controls (key TEXT PRIMARY KEY, value TEXT)')

    def connect(self):
        return sqlite3.connect(self.path, timeout=15)

    def claim(self, manifest, now=None):
        now = now or utc_now()
        if not manifest.get('enabled'):
            return None
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            last_kind = db.execute("SELECT value FROM controls WHERE key='last_slot_kind'").fetchone()
            if last_kind and last_kind[0] == 'campaign':
                return None
            last = db.execute('SELECT MAX(started_at) FROM attempts').fetchone()[0]
            interval = max(0, float(manifest.get('min_interval_hours', 24)))
            if last and now - datetime.fromisoformat(last) < timedelta(hours=interval):
                return None
            candidates = []
            for index, item in enumerate(manifest.get('entries', [])):
                if not item.get('enabled') or item.get('approval_status') != 'approved':
                    continue
                code = item.get('campaign_id', '')
                if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,100}', code):
                    raise ValueError('Invalid campaign id')
                if item.get('not_before'):
                    after = datetime.fromisoformat(item['not_before'].replace('Z', '+00:00'))
                    if after.tzinfo is None:
                        raise ValueError('Campaign not_before must include a timezone')
                    if now < after:
                        continue
                history = db.execute('SELECT started_at,status FROM attempts WHERE campaign=? ORDER BY started_at DESC LIMIT 1', (code,)).fetchone()
                if history:
                    stamp, status = history
                    if status in {'claimed', 'publishing', 'recovering', 'uncertain', 'partial'}:
                        continue
                    days = max(1, float(item.get('repeat_after_days', manifest.get('repeat_after_days', 7))))
                    if now - datetime.fromisoformat(stamp) < timedelta(days=days):
                        continue
                candidates.append((history[0] if history else '', index, item))
            if not candidates:
                return None
            item = min(candidates, key=lambda row: row[:2])[2]
            key = uuid.uuid4().hex
            draft_id = 'campaign_' + now.strftime('%Y%m%dT%H%M%SZ_') + key[:8]
            db.execute('INSERT INTO attempts VALUES (?,?,?,?,?,?,?)', (key, item['campaign_id'], draft_id, iso(now), 'claimed', None, None))
            db.execute("INSERT OR REPLACE INTO controls VALUES ('last_slot_kind','campaign')")
            return {'id': key, 'campaign': item, 'draft_id': draft_id, 'started_at': iso(now)}

    def delivery_started(self, key, target, channel):
        with self.connect() as db:
            db.execute("INSERT INTO deliveries VALUES (?,?,?,'sending',NULL)", (key, target, channel))
            db.execute("UPDATE attempts SET status='publishing' WHERE id=?", (key,))

    def delivery_progress(self, key, target, channel, progress):
        with self.connect() as db:
            row = db.execute("SELECT receipt FROM deliveries WHERE attempt=? AND target=? AND channel=?",
                             (key, target, channel)).fetchone()
            if row is None:
                raise ValueError("Delivery intent must exist before upload progress")
            receipt = json.loads(row[0]) if row[0] else {}
            receipt.update(progress)
            db.execute("UPDATE deliveries SET receipt=? WHERE attempt=? AND target=? AND channel=?",
                       (json.dumps(receipt), key, target, channel))

    def delivery_finished(self, key, target, channel, receipt):
        with self.connect() as db:
            db.execute("UPDATE deliveries SET status='published',receipt=? WHERE attempt=? AND target=? AND channel=?", (json.dumps(receipt), key, target, channel))

    def finish(self, key, status, error=None):
        with self.connect() as db:
            db.execute('UPDATE attempts SET status=?,finished_at=?,error=? WHERE id=?', (status, iso(utc_now()), error, key))

    def mark_image_slot(self):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO controls VALUES ('last_slot_kind','image')")


def mark_image_slot_completed(settings):
    root = campaign_root(settings)
    if (root / 'queue.sqlite3').exists():
        CampaignQueue(root).mark_image_slot()


def run_campaign_slot(service, *, now=None):
    settings = service.settings
    root = campaign_root(settings)
    manifest_path = root / 'manifest.json'
    if not manifest_path.exists():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding='utf-8-sig'))
        queue = CampaignQueue(root)
        attempt = queue.claim(manifest, now=now)
    except (ValueError, TypeError, KeyError, OSError, sqlite3.Error) as exc:
        raise CampaignSelectionError(safe_error(exc)) from None
    if not attempt:
        return None
    item = attempt['campaign']
    draft_dir = Path(settings.instagram_drafts_root) / attempt['draft_id']
    draft_dir.mkdir(parents=True, exist_ok=False)
    draft_path = draft_dir / 'draft.json'
    draft = {'draft_id': attempt['draft_id'], 'draft_dir': str(draft_dir),
             'created_at': attempt['started_at'], 'campaign_id': item['campaign_id'],
             'category_id': 'campaign', 'category_label': item.get('title', item['campaign_id']),
             'objective': 'branding', 'format_type': 'both', 'status': 'draft',
             'image_source': 'approved_campaign', 'video_source': 'approved_campaign',
             'caption': item.get('caption', ''), 'tracking_code': item.get('tracking_code'), 'multi_account_publications': [],
             'campaign_deliveries': []}
    atomic_json(draft_path, draft)
    sent_any = False
    sending = False
    errors = []
    try:
        media_type = item.get('media_type', 'video')
        if media_type not in {'image', 'video'}:
            raise ValueError('Unsupported campaign media_type')
        if caption_digest(draft['caption']) != item.get('caption_sha256'):
            raise ValueError('Approved campaign caption checksum mismatch')
        draft['content_qc'] = validate_caption(draft['caption'], whatsapp_url=settings.instagram_whatsapp_client_url)
        draft['media_type'] = media_type
        if media_type == 'video':
            video = inside(root, item['video'])
            cover = inside(root, item['cover'])
            assets = [(video, 'sha256'), (cover, 'cover_sha256')]
        else:
            image = inside(root, item['image'])
            story = inside(root, item['story_image']) if item.get('publish_stories', True) else None
            assets = [(image, 'sha256')] + ([(story, 'story_sha256')] if story else [])
        for path, key in assets:
            if not item.get(key) or hashlib.sha256(path.read_bytes()).hexdigest() != item[key]:
                raise ValueError('Approved campaign checksum mismatch: ' + path.name)
        if media_type == 'video':
            with Image.open(cover) as picture:
                picture.verify()
            qc = service.instagram_engine._validate_ig_video(video_path=video, target_seconds=float(item['duration_seconds']), require_audio=True)
            if not qc.get('passed'):
                raise ValueError('Campaign video QC failed: ' + str(qc.get('issues')))
            draft.update(image_path=str(cover), video_path=str(video), video_qc=qc,
                         publish_media_mode_effective='video_only')
        else:
            for path, kind in [(image, 'feed')] + ([(story, 'story')] if story else []):
                validate_images([path])
                with Image.open(path) as picture:
                    ratio = picture.width / picture.height
                    if picture.format != 'JPEG' or path.stat().st_size > 8_000_000:
                        raise ValueError('Campaign images must be JPEG under 8 MB')
                    if (kind == 'feed' and not 0.8 <= ratio <= 1.91) or (kind == 'story' and abs(ratio - 9/16) > .001):
                        raise ValueError('Campaign image aspect ratio is invalid for ' + kind)
            draft.update(image_path=str(image), post_image_path=str(image),
                         story_image_path=str(story) if story else None,
                         image_qc={'passed': True}, video_source=None,
                         publish_media_mode_effective='image_only')
        targets, preflight = service._preflight_publish_targets(service._load_instagram_publish_targets())
        if not targets or not any(t.get('publish_instagram', True) or t.get('crosspost_facebook', False) for t in targets):
            raise ValueError('No valid publishing destinations for campaign')
        draft['targets_preflight'] = preflight
        atomic_json(draft_path, draft)
        primary = service._build_instagram_publisher(targets[0])
        if media_type == 'video':
            source_url = str(item.get('public_video_url') or '').strip()
            if source_url:
                draft['public_video_qc'] = verify_public_video(source_url, sha256=item['sha256'], size_bytes=video.stat().st_size)
            else:
                # Compatibility for previously approved videos without stable hosting.
                source_url = primary.stage_local_video_for_public_url(video_path=video, description=draft['caption'])
        else:
            source_url = str(item.get('public_image_url') or '').strip()
            draft['public_image_qc'] = verify_public_image(source_url, sha256=item['sha256'], size_bytes=image.stat().st_size)
            story_url = str(item.get('public_story_image_url') or '').strip()
            if story:
                draft['public_story_image_qc'] = verify_public_image(story_url, sha256=item['story_sha256'], size_bytes=story.stat().st_size)
        atomic_json(draft_path, draft)
        destinations_sent = set()
        for index, target in enumerate(targets):
            publisher = service._build_instagram_publisher(target)
            identity = '|'.join(str(target.get(k, '')) for k in ['meta_page_id', 'meta_instagram_user_id'])
            target_key = hashlib.sha256(identity.encode()).hexdigest()[:20]
            jobs = []
            if media_type == 'video':
                if target.get('publish_instagram', True):
                    jobs.append(('instagram_reel', lambda p=publisher: p.publish_reel_video(video_url=source_url, caption=draft['caption'])))
                    if item.get('publish_stories', True):
                        jobs.append(('instagram_story', lambda p=publisher: p.publish_story_video(video_url=source_url)))
                if target.get('crosspost_facebook', False):
                    jobs.append(('facebook_video', lambda p=publisher: p.publish_facebook_video(video_url=source_url, description=draft['caption'])))
                    if item.get('publish_stories', True) and target.get('publish_facebook_story', False):
                        jobs.append(('facebook_story', lambda p=publisher: p.publish_facebook_story_video(video_url=source_url, progress=lambda state: queue.delivery_progress(attempt['id'], target_key, 'facebook_story', state))))
            else:
                if target.get('publish_instagram', True):
                    jobs.append(('instagram_post', lambda p=publisher: p.publish_image_post(image_url=source_url, caption=draft['caption'])))
                    if story:
                        jobs.append(('instagram_story', lambda p=publisher: p.publish_story_image(image_url=story_url)))
                if target.get('crosspost_facebook', False):
                    jobs.append(('facebook_photo', lambda p=publisher: p.publish_facebook_photo(image_url=source_url, caption=draft['caption'])))
                    if story and target.get('publish_facebook_story', False):
                        jobs.append(('facebook_story', lambda p=publisher: p.publish_facebook_story_photo(image_url=story_url)))
            for channel, send in jobs:
                destination = (channel, str(target.get('meta_instagram_user_id' if channel.startswith('instagram') else 'meta_page_id', '')))
                if destination in destinations_sent:
                    continue
                destinations_sent.add(destination)
                queue.delivery_started(attempt['id'], target_key, channel)
                sending = True
                draft['status'] = 'publication_uncertain'
                draft['publication_attempted_at'] = iso(utc_now())
                atomic_json(draft_path, draft)
                try:
                    receipt = send()
                    # An API acknowledgement without an id is not a verified post.
                    if not isinstance(receipt, dict) or not (receipt.get('post_id') or receipt.get('story_id') or receipt.get('id')):
                        raise ValueError('Publisher did not return a publication id')
                    queue.delivery_finished(attempt['id'], target_key, channel, receipt)
                    sending = False
                    sent_any = True
                    draft['campaign_deliveries'].append({'target': target.get('name', str(index)), 'channel': channel, 'receipt': receipt})
                    draft['published_at'] = receipt.get('published_at') or iso(utc_now())
                    draft['status'] = 'published_with_errors'
                    if channel in {'instagram_reel', 'instagram_post'} and not draft.get('post_id'):
                        draft.update(post_id=receipt.get('post_id'), post_url=receipt.get('url'), published_channel=receipt.get('channel'))
                    elif channel == 'instagram_story' and not draft.get('story_id'):
                        draft.update(story_id=receipt.get('post_id'), story_url=receipt.get('url'), story_channel=receipt.get('channel'))
                    elif channel in {'facebook_video', 'facebook_photo'}:
                        draft['facebook_publication'] = receipt
                    elif channel == 'facebook_story':
                        draft['facebook_story'] = receipt
                    atomic_json(draft_path, draft)
                except Exception as exc:
                    errors.append(channel + ': ' + safe_error(exc))
                    # Continue independent destinations; never retry this delivery.
                    sending = False
                    draft['publication_errors'] = errors
                    atomic_json(draft_path, draft)
                    compact = errors[-1].replace(' ', '').lower()
                    if any(marker in compact for marker in ['"code":368', 'code=368', '"error_subcode":1390008']):
                        raise RuntimeError(errors[-1]) from None
        if errors:
            raise RuntimeError(' | '.join(errors))
        if not sent_any:
            raise ValueError('No campaign delivery was performed')
        draft['status'] = 'published'
        atomic_json(draft_path, draft)
        queue.finish(attempt['id'], 'published')
        return {'draft': draft, 'campaign_id': item['campaign_id'], 'publication': {'mode': 'real', 'status': 'ok', 'published_at': draft['published_at']}}
    except Exception as exc:
        error = safe_error(exc)
        with queue.connect() as db:
            uncertain = bool(db.execute("SELECT 1 FROM deliveries WHERE attempt=? AND status='sending'", (attempt['id'],)).fetchone())
        status = 'partial' if sent_any else 'uncertain' if uncertain or sending else 'failed'
        queue.finish(attempt['id'], status, error)
        draft['status'] = 'published_with_errors' if sent_any else 'publication_uncertain' if status == 'uncertain' else 'failed'
        draft['publication_errors'] = errors or [error]
        atomic_json(draft_path, draft)
        raise RuntimeError(error) from None
