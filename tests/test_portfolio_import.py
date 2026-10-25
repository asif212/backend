import io
import json
from pathlib import Path
import pytest
from PIL import Image
from my_time.import_wordpress import sql_values,index_archive,build,PORTFOLIOS

def test_sql_literals():
    assert sql_values("(1,'can\\'t','line\\nnext',NULL),(2,'a,b','back\\\\slash',4)")==[['1',"can't",'line\nnext',None],['2','a,b','back\\slash','4']]
    with pytest.raises(ValueError):sql_values('(1,SLEEP(1))')

def archive(path,files):
    with path.open('wb') as f:
        for name,data in files.items():
            p=Path(name);header=p.name.encode().ljust(255,b'\0')+str(len(data)).encode().ljust(14,b'\0')+b'0'.ljust(12,b'\0')+str(p.parent).encode().ljust(4096,b'\0')
            f.write(header);f.write(data)
        f.write(b'\0'*4377)

def test_archive_rejects_traversal_and_truncation(tmp_path):
    source=tmp_path/'bad.wpress';archive(source,{'../escape.php':b'bad'})
    with pytest.raises(ValueError,match='Unsafe'):index_archive(source)
    source.write_bytes(b'x')
    with pytest.raises(ValueError,match='Incomplete'):index_archive(source)

def test_staged_import_keeps_portfolio_and_local_media(tmp_path):
    source=tmp_path/'source.wpress';out=tmp_path/'prepared'
    columns=['ID','post_type','post_status','post_password','post_title','post_name','post_content','post_excerpt','post_date','post_modified']
    posts=[]
    for id,slug in PORTFOLIOS.items():posts.append([id,'page','publish','',slug,slug,'<img src="https://nial.in/wp-content/uploads/2023/01/example.png">','','2023-01-01 00:00:00','2023-01-01 00:00:00'])
    posts.append(['99','attachment','inherit','','Example','example','','','2023-01-01 00:00:00','2023-01-01 00:00:00'])
    posts.append(['100','post','publish','','Article','article','<script>secret()</script><p>Actual article.</p>','','2023-01-01 00:00:00','2023-01-01 00:00:00'])
    builder=[{'widgetType':'heading','settings':{'title':'Logos'}},{'widgetType':'image-gallery','settings':{'wp_gallery':[{'id':99,'url':'https://nial.in/wp-content/uploads/2023/01/example.png'}]}}]
    meta=[['1','1399','_elementor_data',json.dumps(builder)],['2','99','_wp_attached_file','2023/01/example.png']]
    def literal(s):return "'"+str(s).replace('\\','\\\\').replace("'","\\'").replace('\n','\\n')+"'"
    def table(name,cols,rows):
        s='CREATE TABLE `SERVMASK_PREFIX_'+name+'` (\n'+',\n'.join('`'+c+'` text' for c in cols)+'\n) ENGINE=InnoDB;\n'
        return s+''.join('INSERT INTO `SERVMASK_PREFIX_'+name+'` VALUES ('+','.join(literal(v) for v in row)+');\n' for row in rows)
    sql=table('posts',columns,posts)+table('postmeta',['meta_id','post_id','meta_key','meta_value'],meta)
    png=io.BytesIO();Image.new('RGB',(30,20),'blue').save(png,'PNG')
    archive(source,{'database.sql':sql.encode(),'uploads/2023/01/example.png':png.getvalue(),'plugins/evil.php':b'<?php bad();'})
    report=build(source,out)
    assert report['portfolio_sections']==6 and report['portfolio_photos']==1
    portfolio=json.loads((out/'portfolio.json').read_text())
    child=next(s for s in portfolio['sections'] if s['title']=='Logos')
    assert child['parent_id']=='graphic-design'
    assert portfolio['photos'][0]['section_id']==child['id']
    assert not (out/'wordpress.json').exists()
    assert not (out/'wordpress_assets').exists()
    assert not (out/'plugins').exists()
    with pytest.raises(ValueError,match='new staging'):build(source,out)
