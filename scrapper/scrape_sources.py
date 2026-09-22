import json, re, time, hashlib
from pathlib import Path
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / 'data' / 'jobs.json'
HEADERS = {'User-Agent':'Mozilla/5.0 (compatible; BDJobAggregator/1.0; +https://github.com/)'}
SOURCES = [
    ('BD Govt Job','https://bdgovtjob.net/'),
    ('The CV Guy','https://thecvguy.net/jobs-and-careertips/'),
]
DELAY = 2

def clean(s): return re.sub(r'\s+', ' ', s or '').strip()

def iso_date(text):
    m=re.search(r'(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})', text or '')
    if m:
        months={'January':1,'February':2,'March':3,'April':4,'May':5,'June':6,'July':7,'August':8,'September':9,'October':10,'November':11,'December':12}
        if m.group(2) in months: return f'{m.group(3)}-{months[m.group(2)]:02d}-{int(m.group(1)):02d}'
    bn={'জানুয়ারি':1,'ফেব্রুয়ারি':2,'মার্চ':3,'এপ্রিল':4,'মে':5,'জুন':6,'জুলাই':7,'আগস্ট':8,'সেপ্টেম্বর':9,'অক্টোবর':10,'নভেম্বর':11,'ডিসেম্বর':12}
    trans=str.maketrans('০১২৩৪৫৬৭৮৯','0123456789')
    t=(text or '').translate(trans)
    for name,num in bn.items():
        m=re.search(r'(\d{1,2})\s+'+re.escape(name)+r'\s+(\d{4})',t)
        if m:return f'{m.group(2)}-{num:02d}-{int(m.group(1)):02d}'
    return None

def jid(url,title): return hashlib.sha1((url+'|'+title).encode()).hexdigest()[:16]

def fetch(url):
    r=requests.get(url,headers=HEADERS,timeout=30); r.raise_for_status(); return r.text

def scrape_bd(html, base):
    soup=BeautifulSoup(html,'html.parser'); out=[]
    for a in soup.select('article h1 a, article h2 a, article h3 a, .post h2 a, .post h3 a'):
        title=clean(a.get_text(' ',strip=True)); url=urljoin(base,a.get('href',''))
        if not title or not url.startswith('http'): continue
        article=a.find_parent(['article','div'],class_=re.compile(r'post|article',re.I)) or a.parent
        txt=clean(article.get_text(' ',strip=True))
        cat='GOVT'
        low=txt.lower()
        if 'bank' in low: cat='BANK'
        elif 'private' in low: cat='PRIVATE'
        elif 'defence' in low or 'defense' in low: cat='DEFENCE'
        elif 'university' in low or 'school' in low or 'college' in low: cat='EDUCATION'
        out.append({'id':jid(url,title),'source':'BD Govt Job','type':'job','title':title,'organization':None,'category':cat,'publish_date':iso_date(txt),'deadline':iso_date(re.search(r'আবেদনের শেষ তারিখ\s*:?\s*(.{0,80})',txt).group(1)) if re.search(r'আবেদনের শেষ তারিখ\s*:?\s*(.{0,80})',txt) else None,'vacancies':None,'source_url':url,'apply_url':url,'summary':txt[:400]})
    return out

def scrape_cvguy(html, base):
    soup=BeautifulSoup(html,'html.parser'); out=[]
    for a in soup.select('article h1 a, article h2 a, article h3 a, article a[href]'):
        title=clean(a.get_text(' ',strip=True)); url=urljoin(base,a.get('href',''))
        if len(title)<12 or any(x in title.lower() for x in ['full job description','read more']): continue
        if not url.startswith('https://thecvguy.net/'): continue
        card=a.find_parent('article') or a.find_parent(class_=re.compile(r'post|card',re.I))
        txt=clean(card.get_text(' ',strip=True) if card else a.parent.get_text(' ',strip=True))
        if not any(k in title.lower() for k in ['hiring','job','intern','trainee','executive','manager','officer','analyst','assistant','engineer','director','recruitment']): continue
        cat='JOBS_BD'; low=txt.lower()
        if 'bank' in low or 'standard chartered' in title.lower(): cat='BANK'
        elif 'intern' in title.lower() or 'traineeship' in title.lower(): cat='INTERNSHIP'
        elif 'fresher' in low: cat='FRESHERS'
        elif any(k in low for k in ['mnc','robi','foodpanda','jti','marico','dhl','nestlé','berger','reckitt']): cat='MNC'
        out.append({'id':jid(url,title),'source':'The CV Guy','type':'job','title':title,'organization':None,'category':cat,'publish_date':iso_date(txt),'deadline':None,'vacancies':'N/A','source_url':url,'apply_url':url,'summary':'Job listing collected from The CV Guy feed.'})
    seen=set(); return [x for x in out if not (x['id'] in seen or seen.add(x['id']))]

def main():
    existing={x['id']:x for x in json.loads(DATA.read_text(encoding='utf-8'))} if DATA.exists() else {}
    for name,url in SOURCES:
        try:
            html=fetch(url)
            rows=scrape_bd(html,url) if name=='BD Govt Job' else scrape_cvguy(html,url)
            for row in rows: existing[row['id']]=row
            print(f'{name}: {len(rows)} rows')
        except Exception as e: print(f'{name}: ERROR {e}')
        time.sleep(DELAY)
    rows=sorted(existing.values(), key=lambda x:x.get('publish_date') or '', reverse=True)
    DATA.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'Total: {len(rows)}')
if __name__=='__main__': main()
