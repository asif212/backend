"""Offline .wpress portfolio-only importer. Never executes SQL, PHP or plugin code.

Build in a NEW staging directory, inspect its report, then merge those files into
WEBSITE_DATA_DIR with the application stopped or its website lock held.
"""
import argparse
import hashlib
import html
import io
import json
import re
import shutil
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse, unquote, quote
from uuid import NAMESPACE_URL, uuid5
from PIL import Image, ImageOps
IMAGE_TYPES={'.png','.jpg','.jpeg','.webp','.gif'}
from .website import DEFAULT

HEADER=4377
KEEP={'posts','postmeta'}
PORTFOLIOS={'1399':'graphic-design','1401':'photo-editing','1403':'motion-graphics','1990':'website-development','1405':'video-editing'}

def uid(value):
    return uuid5(NAMESPACE_URL,'https://nial.in/migration/'+value).hex

def index_archive(path):
    entries=[];total=path.stat().st_size
    with path.open('rb') as handle:
        while True:
            block=handle.read(HEADER)
            if len(block)!=HEADER:raise ValueError('Incomplete archive header')
            name=block[:255].split(b'\0')[0].decode('utf-8')
            if not name:break
            size=int(block[255:269].split(b'\0')[0])
            prefix=block[281:4377].split(b'\0')[0].decode('utf-8')
            member=PurePosixPath(prefix)/name
            if member.is_absolute() or '..' in member.parts or '\\' in str(member):raise ValueError('Unsafe archive path')
            if size<0 or handle.tell()+size>total:raise ValueError('Truncated archive member')
            entries.append({'path':str(member),'size':size,'offset':handle.tell()})
            handle.seek(size,1)
        if handle.tell()!=total:raise ValueError('Unexpected trailing archive data')
    return entries

def sql_values(text):
    """Decode MySQL INSERT literal values without evaluating a SQL statement."""
    rows=[];row=[];i=0
    while i<len(text):
        c=text[i]
        if c in ' \t\r\n,;':i+=1;continue
        if c=='(':row=[];i+=1;continue
        if c==')':rows.append(row);i+=1;continue
        if c=="'":
            i+=1;buf=[];closed=False
            while i<len(text):
                if text[i]=='\\':
                    i+=1
                    if i>=len(text):raise ValueError('Incomplete SQL escape')
                    ch=text[i];buf.append({'n':'\n','r':'\r','t':'\t','0':'\0','Z':'\x1a'}.get(ch,ch));i+=1
                elif text[i]=="'":
                    if i+1<len(text) and text[i+1]=="'":buf.append("'");i+=2
                    else:i+=1;closed=True;break
                else:buf.append(text[i]);i+=1
            if not closed:raise ValueError('Unclosed SQL string')
            row.append(''.join(buf))
        else:
            start=i
            while i<len(text) and text[i] not in ',)':i+=1
            token=text[start:i].strip()
            if token=='NULL':row.append(None)
            elif re.fullmatch(r'-?\d+(?:\.\d+)?',token):row.append(token)
            else:raise ValueError('Unsupported SQL literal')
    return rows

def read_tables(sql):
    schemas={m.group(1):re.findall(r'^\s*`([^`]+)`',m.group(2),re.M) for m in re.finditer(r'CREATE TABLE (?:IF NOT EXISTS )?`([^`]+)`\s*\((.*?)\) ENGINE',sql,re.S)}
    result={name:[] for name in KEEP};counts=Counter()
    for line in sql.splitlines():
        match=re.match(r'INSERT INTO `([^`]+)`(?:\s*\([^)]*\))? VALUES (.*);$',line)
        if not match:continue
        table=match.group(1);suffix=next((name for name in KEEP if table.endswith('_'+name)),None)
        if suffix is None:counts[table.removeprefix('SERVMASK_PREFIX_')]+=1;continue
        for row in sql_values(match.group(2)):
            if len(row)!=len(schemas[table]):raise ValueError('SQL column count mismatch: '+table)
            result[suffix].append(dict(zip(schemas[table],row)));counts[suffix]+=1
    if not result['posts']:raise ValueError('No WordPress posts found')
    return result,dict(counts)

def plain(value):
    return html.unescape(re.sub('<[^>]+>',' ',value or '')).strip()

def widgets(value):
    if isinstance(value,list):
        for child in value:yield from widgets(child)
    elif isinstance(value,dict):
        if value.get('widgetType'):yield value
        yield from widgets(value.get('elements',[]))

def build(source:Path,destination:Path):
    if destination.exists():raise ValueError('Use a new staging directory; existing data is never overwritten')
    destination.mkdir(parents=True)
    entries=index_archive(source)
    sqlentry=next((e for e in entries if e['path']=='database.sql'),None)
    if not sqlentry:raise ValueError('No database.sql in archive')
    with source.open('rb') as handle:
        handle.seek(sqlentry['offset']);tables,counts=read_tables(handle.read(sqlentry['size']).decode('utf-8'))
    posts={p['ID']:p for p in tables['posts']}
    metadata=defaultdict(dict)
    for item in tables['postmeta']:metadata[item['post_id']][item['meta_key']]=item['meta_value']
    image_root=destination/'wordpress_assets';image_root.mkdir()
    copied=set();rejected=[];resized=[]
    with source.open('rb') as handle:
        for entry in entries:
            member=PurePosixPath(entry['path'])
            if not member.parts or member.parts[0]!='uploads' or member.suffix.lower() not in IMAGE_TYPES:continue
            relative=PurePosixPath(*member.parts[1:])
            handle.seek(entry['offset']);raw=handle.read(entry['size'])
            try:
                with Image.open(io.BytesIO(raw)) as image:
                    if image.format not in {'JPEG','PNG','GIF','WEBP'}:raise ValueError('Unsupported image')
                    image.verify()
            except Image.DecompressionBombError:
                # Offline JPEG recovery uses the decoder's reduced-resolution mode.
                previous=Image.MAX_IMAGE_PIXELS;Image.MAX_IMAGE_PIXELS=None
                try:
                    with Image.open(io.BytesIO(raw)) as image:
                        if image.format!='JPEG':raise ValueError('Oversized non-JPEG')
                        image.draft('RGB',(2400,2400))
                        if image.width*image.height>20_000_000:raise ValueError('Decoder remains too large')
                        image.thumbnail((2400,2400));out=io.BytesIO();image.convert('RGB').save(out,'JPEG',quality=88);raw=out.getvalue()
                        resized.append(str(relative))
                except Exception as exc:
                    rejected.append({'path':str(relative),'reason':type(exc).__name__});continue
                finally:Image.MAX_IMAGE_PIXELS=previous
            except Exception as exc:
                rejected.append({'path':str(relative),'reason':type(exc).__name__});continue
            target=image_root/str(relative);target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw);copied.add(str(relative))
    def relative_image(url):
        path=unquote(urlparse(str(url)).path)
        marker='/wp-content/uploads/'
        if marker in path:path=path.split(marker,1)[1]
        else:path=path.lstrip('/')
        if path in copied:return path
        if 'backup/'+path in copied:return 'backup/'+path
        unscaled=re.sub(r'-scaled(?=\.[^.]+$)','',path)
        for candidate in [unscaled,'backup/'+unscaled]:
            if candidate in copied:return candidate
        stem=PurePosixPath(path).stem
        matches=[candidate for candidate in copied if PurePosixPath(candidate).stem==stem]
        if len(matches)==1:return matches[0]
        return None
    missing=set()
    def builder(id):
        try:return json.loads(metadata[id].get('_elementor_data','[]'))
        except (ValueError,TypeError):return []
    portfolio={'sections':[],'photos':[]};portfolio_root=destination/'portfolio_assets';portfolio_root.mkdir()
    for wp_id,section_id in PORTFOLIOS.items():
        original=posts[wp_id]
        title='Web Development' if section_id=='website-development' else original['post_title']
        parent={'id':section_id,'title':title,'description':'','parent_id':None,'cover_id':None,'source_wordpress_id':wp_id}
        portfolio['sections'].append(parent);active=parent;seen=set()
        def canonical(url):
            relative=relative_image(url)
            if not relative:return None
            relative=relative.removeprefix('backup/')
            return re.sub(r'-(?:\d+x\d+|scaled)$','',str(PurePosixPath(relative).with_suffix('')))
        visible={canonical(url) for url in re.findall(r'(?:src|href)=[\"\']([^\"\']+)',original['post_content']) if '/wp-content/uploads/' in url}
        visible.discard(None)
        for widget in widgets(builder(wp_id)):
            kind=widget['widgetType'];settings=widget.get('settings',{})
            if kind=='heading':
                heading=plain(settings.get('title',''))
                if not heading or heading.casefold() in {title.casefold(),original['post_title'].casefold()}:continue
                child_id=uid('section/'+wp_id+'/'+heading)
                active=next((s for s in portfolio['sections'] if s['id']==child_id),None)
                if active is None:
                    active={'id':child_id,'title':heading,'description':'','parent_id':section_id,'cover_id':None,'source_wordpress_id':wp_id}
                    portfolio['sections'].append(active)
            pictures=[]
            for key in ['gallery','wp_gallery']:
                value=settings.get(key,[])
                if isinstance(value,list):pictures+=value
            if kind=='image' and isinstance(settings.get('image'),dict):pictures.append(settings['image'])
            for picture in pictures:
                if original['post_content'].strip() and canonical(picture.get('url','')) not in visible:continue
                attachment_id=str(picture.get('id',''));rel=relative_image('https://nial.in/wp-content/uploads/'+metadata[attachment_id].get('_wp_attached_file','')) or relative_image(picture.get('url',''))
                if rel not in copied:missing.add(str(picture.get('url') or rel));continue
                key=(active['id'],rel)
                if key in seen:continue
                seen.add(key);photo_id=uid('photo/'+active['id']+'/'+rel)
                src=image_root/rel
                try:
                    with Image.open(src) as image:
                        if image.format=='GIF' and getattr(image,'is_animated',False):
                            extension='.gif';shutil.copyfile(src,portfolio_root/(photo_id+extension))
                        else:
                            image.thumbnail((2400,2400));normalized=ImageOps.exif_transpose(image).convert('RGB');extension='.webp'
                            normalized.save(portfolio_root/(photo_id+extension),'WEBP',quality=85)
                except Exception as exc:
                    rejected.append({'path':rel,'reason':'Portfolio: '+type(exc).__name__});continue
                p=posts.get(attachment_id,{})
                portfolio['photos'].append({'id':photo_id,'section_id':active['id'],'name':p.get('post_title') or Path(rel).name,'extension':extension,'source_wordpress_id':attachment_id,'source_path':rel})
                active['cover_id']=active['cover_id'] or photo_id;parent['cover_id']=parent['cover_id'] or photo_id
    with source.open('rb') as handle:digest=hashlib.file_digest(handle,'sha256').hexdigest()
    report={'source':'nial.in portfolio only','sha256':digest,'portfolio_sections':len(portfolio['sections']),'portfolio_photos':len(portfolio['photos']),'animated_portfolio_gifs':sum(p['extension']=='.gif' for p in portfolio['photos']),'missing_media':sorted(missing),'rejected_images':rejected,'scope':'Portfolio parent/child sections and their published gallery images only.'}
    (destination/'portfolio.json').write_text(json.dumps(portfolio,ensure_ascii=False,indent=2))
    (destination/'migration-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    shutil.rmtree(image_root)
    print(json.dumps(report,indent=2))
    return report

def apply_prepared(prepared:Path):
    """Merge a verified prepared import; preserve current edits and take a snapshot."""
    from datetime import datetime, timezone
    from .website import root, locked, atomic_write
    prepared=prepared.resolve()
    report=json.loads((prepared/'migration-report.json').read_text())
    if report['missing_media'] or report['rejected_images']:
        raise ValueError('Resolve missing or rejected media before applying this import')
    with locked():
        target=root().resolve()
        snapshot=target.parent/'website_import_backups'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        snapshot.mkdir(parents=True)
        shutil.copytree(target,snapshot/'website_data')
        for folder in ['portfolio_assets']:
            shutil.copytree(prepared/folder,target/folder,dirs_exist_ok=True)
        incoming=json.loads((prepared/'portfolio.json').read_text())
        path=target/'portfolio.json'
        current=json.loads(path.read_text()) if path.exists() else {'sections':[],'photos':[]}
        for key in ['sections','photos']:
            known={item['id'] for item in current[key]}
            current[key]+=[item for item in incoming[key] if item['id'] not in known]
        # Replace starter examples with actual portfolio covers on a fresh website.
        if not (target/'content.json').exists():
            content=DEFAULT.model_copy(deep=True)
            featured=[s for s in incoming['sections'] if s['parent_id'] and s['cover_id']][:4]
            for card,section in zip(content.cards[:4],featured):
                card.title=section['title'];card.category='PORTFOLIO';card.description='Explore the '+section['title']+' collection.';card.portfolio_section_id=section['id']
                photo=next(p for p in incoming['photos'] if p['id']==section['cover_id'])
                with Image.open(prepared/'portfolio_assets'/(photo['id']+photo.get('extension','.webp'))) as image:
                    image.convert('RGB').save(target/(card.slot+'.webp'),'WEBP',quality=85)
            atomic_write(target/'content.json',content.model_dump_json(indent=2).encode())
        atomic_write(target/'portfolio.json',json.dumps(current,ensure_ascii=False).encode())
        atomic_write(target/'migration-report.json',json.dumps(report,ensure_ascii=False,indent=2).encode())
        print('Website import applied. Previous website data snapshot:',snapshot)
        return snapshot

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--apply',action='store_true',help='Merge the prepared import into WEBSITE_DATA_DIR after validation')
    args=parser.parse_args();build(args.source,args.output)
    if args.apply:apply_prepared(args.output)

if __name__=='__main__':main()
